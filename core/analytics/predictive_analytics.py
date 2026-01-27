# AI_FREELANCE_AUTOMATION/core/analytics/predictive_analytics.py

"""
Predictive Analytics Engine — Core component for forecasting system behavior,
market trends, job success probability, and resource needs.

Features:
- Predicts job acceptance likelihood
- Forecasts income & workload
- Detects upcoming bottlenecks
- Recommends optimal bidding strategy
- Integrates with monitoring & AI systems
- Self-validates predictions against outcomes

Designed for 100% autonomy and continuous learning.
"""

import logging
import json
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timedelta
import numpy as np

# Local imports (relative to core/)
from ..config.unified_config_manager import UnifiedConfigManager
from ..monitoring.intelligent_monitoring_system import IntelligentMonitoringSystem
from ..ai_management.intelligent_model_manager import IntelligentModelManager
from ..learning.continuous_learning_system import ContinuousLearningSystem
from ..security.audit_logger import AuditLogger

# Type alias for clarity
PredictionResult = Dict[str, Any]

class PredictiveAnalyticsEngine:
    """
    Central predictive engine using hybrid approach:
    - Statistical models (for short-term, high-confidence forecasts)
    - Lightweight ML models (for pattern-based predictions)
    - Rule-based heuristics (for edge cases and safety)

    All predictions are logged, validated, and fed back into the learning loop.
    """

    def __init__(
        self,
        config_manager: UnifiedConfigManager,
        monitoring_system: IntelligentMonitoringSystem,
        model_manager: IntelligentModelManager,
        learning_system: Optional[ContinuousLearningSystem] = None,
        audit_logger: Optional[AuditLogger] = None
    ):
        self.config = config_manager
        self.monitoring = monitoring_system
        self.model_manager = model_manager
        self.learning_system = learning_system
        self.audit_logger = audit_logger or AuditLogger()

        self.logger = logging.getLogger("PredictiveAnalytics")
        self._initialized = False

        # Load prediction-specific config
        self.prediction_config = self.config.get_subconfig("analytics.predictive")
        self.enabled = self.prediction_config.get("enabled", True)
        self.confidence_threshold = self.prediction_config.get("confidence_threshold", 0.75)

        if not self.enabled:
            self.logger.warning("⚠️ Predictive Analytics is DISABLED in config.")
            return

        self._initialize_models()
        self._initialized = True
        self.logger.info("✅ Predictive Analytics Engine initialized.")

    def _initialize_models(self) -> None:
        """Load or initialize internal prediction models."""
        try:
            # For MVP: use rule-based + statistical fallback
            # In production: load trained ML models via model_manager
            self.logger.debug("Loading predictive models...")
            # Example: self._income_model = self.model_manager.load_model("income_forecast_v2")
            self.logger.info("Intialized rule-based predictive heuristics.")
        except Exception as e:
            self.logger.error(f"❌ Failed to initialize predictive models: {e}", exc_info=True)
            raise

    def predict_job_success_probability(self, job_data: Dict[str, Any]) -> PredictionResult:
        """
        Predicts the probability of successfully completing a job and getting paid.

        Factors considered:
        - Client history (rating, payment speed)
        - Job complexity vs. current capacity
        - Platform reputation
        - Historical success on similar tasks
        - Sentiment in job description

        Returns:
        {
            "probability": 0.92,
            "confidence": 0.88,
            "factors": {...},
            "recommendation": "accept|decline|negotiate"
        }
        """
        if not self._initialized or not self.enabled:
            return self._fallback_prediction(job_data, reason="engine_disabled")

        try:
            client_id = job_data.get("client_id")
            platform = job_data.get("platform")
            budget = job_data.get("budget", 0)
            deadline_hours = job_data.get("deadline_hours", 72)
            task_type = job_data.get("task_type", "unknown")  # e.g., 'transcription'

            # Fetch historical data
            client_history = self.monitoring.get_client_metrics(client_id) if client_id else {}
            system_load = self.monitoring.get_current_load()
            recent_success_rate = self.monitoring.get_success_rate_last_30d(task_type)

            # Heuristic scoring
            score = 0.5  # base
            confidence = 0.6

            # Client trust
            if client_history:
                avg_rating = client_history.get("avg_rating", 4.0)
                payment_speed = client_history.get("avg_payment_hours", 48)
                if avg_rating >= 4.5:
                    score += 0.2
                if payment_speed <= 24:
                    score += 0.15
                confidence += 0.1

            # System capacity
            if system_load["active_jobs"] < 10:
                score += 0.1
            elif system_load["active_jobs"] > 30:
                score -= 0.2

            # Budget & deadline sanity
            if budget > 50 and deadline_hours > 24:
                score += 0.1
            elif deadline_hours < 12:
                score -= 0.15

            # Task expertise
            if recent_success_rate > 0.9:
                score += 0.1
                confidence += 0.1

            # Clamp values
            probability = min(max(score, 0.0), 1.0)
            confidence = min(max(confidence, 0.5), 1.0)

            # Recommendation
            if probability >= 0.8 and confidence >= self.confidence_threshold:
                recommendation = "accept"
            elif probability >= 0.6:
                recommendation = "negotiate"
            else:
                recommendation = "decline"

            result = {
                "probability": round(probability, 3),
                "confidence": round(confidence, 3),
                "factors": {
                    "client_trust": avg_rating if client_history else None,
                    "system_load": system_load["active_jobs"],
                    "task_expertise": recent_success_rate,
                    "budget_deadline_ratio": budget / max(deadline_hours, 1)
                },
                "recommendation": recommendation,
                "timestamp": datetime.utcnow().isoformat()
            }

            self.audit_logger.log(
                action="predict_job_success",
                entity="job",
                details={"job_id": job_data.get("job_id"), "result": result}
            )

            return result

        except Exception as e:
            self.logger.error(f"Error in job success prediction: {e}", exc_info=True)
            return self._fallback_prediction(job_data, reason="prediction_error")

    def forecast_income_next_7d(self) -> PredictionResult:
        """Forecast expected income for the next 7 days."""
        try:
            active_jobs = self.monitoring.get_active_jobs()
            pending_bids = self.monitoring.get_pending_bids()
            historical_daily_avg = self.monitoring.get_avg_daily_income_30d()

            # Simple projection
            committed_income = sum(j.get("budget", 0) for j in active_jobs)
            expected_from_bids = sum(
                b.get("budget", 0) * b.get("win_probability", 0.3)
                for b in pending_bids
            )
            baseline = historical_daily_avg * 7

            total_forecast = committed_income + expected_from_bids + baseline * 0.2  # conservative

            return {
                "forecast_usd": round(total_forecast, 2),
                "committed": round(committed_income, 2),
                "expected_from_bids": round(expected_from_bids, 2),
                "baseline_contribution": round(baseline * 0.2, 2),
                "confidence": 0.8,
                "timestamp": datetime.utcnow().isoformat()
            }

        except Exception as e:
            self.logger.error(f"Income forecast failed: {e}", exc_info=True)
            return {"error": str(e), "forecast_usd": 0.0, "confidence": 0.0}

    def detect_upcoming_bottlenecks(self) -> List[Dict[str, Any]]:
        """Detect potential resource or timeline bottlenecks in next 48h."""
        try:
            jobs_due_soon = self.monitoring.get_jobs_due_in(hours=48)
            system_capacity = self.monitoring.get_system_capacity()

            bottlenecks = []
            for job in jobs_due_soon:
                required_resources = self._estimate_resources(job)
                if required_resources["gpu"] > system_capacity["available_gpu"]:
                    bottlenecks.append({
                        "type": "gpu_shortage",
                        "job_id": job["job_id"],
                        "severity": "high"
                    })
                if required_resources["cpu_cores"] > system_capacity["available_cpu"]:
                    bottlenecks.append({
                        "type": "cpu_overload",
                        "job_id": job["job_id"],
                        "severity": "medium"
                    })

            return bottlenecks
        except Exception as e:
            self.logger.error(f"Bottleneck detection failed: {e}", exc_info=True)
            return []

    def _estimate_resources(self, job: Dict[str, Any]) -> Dict[str, float]:
        """Estimate required compute resources for a job."""
        task_type = job.get("task_type", "generic")
        size = job.get("size_estimate", 1.0)  # normalized unit

        # Rough estimates
        mapping = {
            "transcription": {"cpu_cores": 2 * size, "gpu": 0.0, "ram_gb": 4 * size},
            "translation": {"cpu_cores": 1 * size, "gpu": 0.0, "ram_gb": 2 * size},
            "copywriting": {"cpu_cores": 1 * size, "gpu": 0.0, "ram_gb": 1 * size},
            "editing": {"cpu_cores": 1.5 * size, "gpu": 0.0, "ram_gb": 3 * size}
        }
        return mapping.get(task_type, {"cpu_cores": 1, "gpu": 0, "ram_gb": 2})

    def _fallback_prediction(self, job_data: Dict[str, Any], reason: str) -> PredictionResult:
        """Safe fallback when prediction fails."""
        self.logger.warning(f"Using fallback prediction due to: {reason}")
        return {
            "probability": 0.5,
            "confidence": 0.3,
            "factors": {"reason": reason},
            "recommendation": "decline",
            "timestamp": datetime.utcnow().isoformat(),
            "fallback": True
        }

    def validate_and_learn(self, prediction: PredictionResult, actual_outcome: Dict[str, Any]) -> None:
        """
        Compare prediction vs reality and feed into continuous learning.
        Called by monitoring or workflow orchestrator after job completion.
        """
        if not self.learning_system:
            return

        try:
            error = abs(prediction["probability"] - actual_outcome.get("success", 0.0))
            self.learning_system.ingest_feedback(
                context="job_success_prediction",
                input_data=prediction.get("factors", {}),
                predicted=prediction["probability"],
                actual=actual_outcome.get("success", 0.0),
                error=error
            )
            self.logger.debug(f"Feedback ingested for prediction validation. Error: {error:.3f}")
        except Exception as e:
            self.logger.error(f"Failed to ingest prediction feedback: {e}", exc_info=True)


# Module-level convenience function (for service locator or DI)
def create_predictive_analytics_engine(
    config_manager: UnifiedConfigManager,
    monitoring_system: IntelligentMonitoringSystem,
    model_manager: IntelligentModelManager,
    learning_system: Optional[ContinuousLearningSystem] = None
) -> PredictiveAnalyticsEngine:
    """Factory function for DI container."""
    return PredictiveAnalyticsEngine(
        config_manager=config_manager,
        monitoring_system=monitoring_system,
        model_manager=model_manager,
        learning_system=learning_system
    )