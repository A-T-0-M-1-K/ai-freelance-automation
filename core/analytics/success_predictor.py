# AI_FREELANCE_AUTOMATION/core/analytics/success_predictor.py
"""
Success Predictor — predicts the likelihood of successful completion and client satisfaction
for a given freelance job based on historical data, market conditions, and real-time signals.

Integrates with:
- Learning system (for feedback patterns)
- Monitoring system (for performance metrics)
- AI Model Manager (for inference)
- Config system (for thresholds and models)

Ensures:
✅ No circular imports
✅ Type safety
✅ Error resilience
✅ Audit logging
✅ Self-diagnosis capability
"""

import logging
import json
from typing import Dict, Any, Optional, Tuple
from pathlib import Path

from core.config.unified_config_manager import UnifiedConfigManager
from core.monitoring.intelligent_monitoring_system import IntelligentMonitoringSystem
from core.ai_management.intelligent_model_manager import IntelligentModelManager
from core.learning.continuous_learning_system import ContinuousLearningSystem
from core.security.audit_logger import AuditLogger

logger = logging.getLogger("SuccessPredictor")


class SuccessPredictor:
    """
    Predicts job success probability using ensemble of signals:
    - Historical performance on similar jobs
    - Client reputation & payment history
    - Market competition level
    - Internal resource availability
    - Sentiment from initial client messages
    """

    def __init__(
        self,
        config_manager: UnifiedConfigManager,
        monitoring_system: IntelligentMonitoringSystem,
        model_manager: IntelligentModelManager,
        learning_system: ContinuousLearningSystem,
        audit_logger: Optional[AuditLogger] = None
    ):
        self.config = config_manager.get_subconfig("analytics.success_predictor")
        self.monitoring = monitoring_system
        self.model_manager = model_manager
        self.learning = learning_system
        self.audit_logger = audit_logger or AuditLogger()
        self._model = None
        self._initialized = False
        logger.info("Intialized SuccessPredictor with config: %s", self.config)

    async def initialize(self) -> bool:
        """Lazy-load prediction model and validate dependencies."""
        if self._initialized:
            return True

        try:
            model_name = self.config.get("model.name", "success_predictor_v1")
            model_version = self.config.get("model.version", "latest")

            self._model = await self.model_manager.load_model(
                model_name=model_name,
                version=model_version,
                purpose="success_prediction"
            )

            if not self._model:
                raise RuntimeError(f"Failed to load success prediction model: {model_name}@{model_version}")

            self._initialized = True
            logger.info("✅ Success prediction model loaded successfully.")
            self.audit_logger.log("MODEL_LOAD", {"model": model_name, "version": model_version})
            return True

        except Exception as e:
            logger.error("❌ Failed to initialize SuccessPredictor: %s", e, exc_info=True)
            self.audit_logger.log("ERROR", {"component": "SuccessPredictor", "error": str(e)})
            await self._trigger_recovery(e)
            return False

    async def predict_success(
        self,
        job_data: Dict[str, Any],
        client_profile: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Predict success probability for a job.

        Args:
            job_data: {
                "job_id": str,
                "platform": str,
                "title": str,
                "description": str,
                "budget": float,
                "deadline_hours": int,
                "category": str,
                "skills": List[str],
                "competition_level": float  # 0.0–1.0
            }
            client_profile: {
                "client_id": str,
                "rating": float,
                "payment_score": float,  # 0–100
                "repeat_client": bool,
                "avg_response_time_hours": float
            }
            context: optional runtime context (e.g., current workload)

        Returns:
            {
                "success_probability": float (0.0–1.0),
                "confidence": float (0.0–1.0),
                "risk_factors": List[str],
                "recommendations": List[str],
                "model_version": str
            }
        """
        if not self._initialized:
            init_ok = await self.initialize()
            if not init_ok:
                return self._fallback_prediction(job_data)

        try:
            # Enrich input with historical patterns
            enriched_data = await self._enrich_with_historical_insights(job_data, client_profile)

            # Run inference
            prediction = await self._run_inference(enriched_data, context)

            # Post-process
            result = self._post_process_prediction(prediction, job_data, client_profile)

            # Log non-sensitive metrics
            self.monitoring.record_metric("success_prediction_count", 1)
            self.monitoring.record_metric("avg_success_probability", result["success_probability"])

            logger.info(
                "📈 Predicted success=%.2f for job=%s (platform=%s)",
                result["success_probability"],
                job_data.get("job_id", "unknown"),
                job_data.get("platform", "unknown")
            )

            return result

        except Exception as e:
            logger.warning("⚠️ Prediction failed, using fallback: %s", e)
            self.audit_logger.log("PREDICTION_ERROR", {"job_id": job_data.get("job_id"), "error": str(e)})
            return self._fallback_prediction(job_data)

    async def _enrich_with_historical_insights(
        self,
        job_data: Dict[str, Any],
        client_profile: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Enrich raw job data with learned patterns."""
        enriched = job_data.copy()

        # Add historical success rate for this category
        category = job_data.get("category", "general")
        hist_success = await self.learning.get_pattern(
            pattern_type="category_success_rate",
            key=category
        )
        enriched["historical_success_rate"] = hist_success or 0.65

        # Add client reliability score
        if client_profile:
            client_id = client_profile.get("client_id")
            reliability = await self.learning.get_pattern(
                pattern_type="client_reliability",
                key=client_id
            )
            enriched["client_reliability_score"] = reliability or client_profile.get("payment_score", 50.0) / 100.0
        else:
            enriched["client_reliability_score"] = 0.5

        # Add system load factor
        current_load = self.monitoring.get_current_load()
        enriched["system_load_factor"] = min(current_load.get("cpu", 0.5), 1.0)

        return enriched

    async def _run_inference(
        self,
        data: Dict[str, Any],
        context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Run model inference."""
        input_vector = self._prepare_input_vector(data, context)
        raw_output = await self._model.infer(input_vector)
        return raw_output

    def _prepare_input_vector(self, data: Dict[str, Any], context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Convert structured data into model-ready format."""
        return {
            "budget_normalized": min(data.get("budget", 0) / 500.0, 1.0),
            "deadline_urgency": max(1.0 - (data.get("deadline_hours", 168) / 168.0), 0.0),
            "competition": data.get("competition_level", 0.5),
            "historical_success": data.get("historical_success_rate", 0.65),
            "client_reliability": data.get("client_reliability_score", 0.5),
            "system_load": data.get("system_load_factor", 0.5),
            "is_repeat_client": int(data.get("client_profile", {}).get("repeat_client", False))
        }

    def _post_process_prediction(
        self,
        raw_pred: Dict[str, Any],
        job_data: Dict[str, Any],
        client_profile: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Refine raw model output into actionable insights."""
        prob = float(raw_pred.get("success_probability", 0.5))
        confidence = float(raw_pred.get("confidence", 0.7))

        risk_factors = []
        recommendations = []

        if job_data.get("budget", 0) < 20:
            risk_factors.append("low_budget")
            recommendations.append("Consider minimum viable bid or decline")

        if job_data.get("deadline_hours", 168) < 24:
            risk_factors.append("tight_deadline")
            recommendations.append("Verify resource availability before bidding")

        if client_profile and client_profile.get("rating", 5.0) < 4.0:
            risk_factors.append("low_client_rating")
            recommendations.append("Request milestone payments")

        if prob < 0.4:
            risk_factors.append("high_failure_risk")
            recommendations.append("Avoid unless strategic value exists")

        return {
            "success_probability": max(0.0, min(1.0, prob)),
            "confidence": max(0.0, min(1.0, confidence)),
            "risk_factors": risk_factors,
            "recommendations": recommendations,
            "model_version": self._model.version if self._model else "fallback"
        }

    def _fallback_prediction(self, job_data: Dict[str, Any]) -> Dict[str, Any]:
        """Safe fallback when model is unavailable."""
        budget = job_data.get("budget", 0)
        deadline = job_data.get("deadline_hours", 168)

        # Simple heuristic-based fallback
        base_prob = 0.6
        if budget >= 100:
            base_prob += 0.2
        if deadline >= 72:
            base_prob += 0.1
        if budget < 10 or deadline < 12:
            base_prob -= 0.3

        return {
            "success_probability": max(0.1, min(0.9, base_prob)),
            "confidence": 0.4,
            "risk_factors": ["model_unavailable"],
            "recommendations": ["Use with caution — prediction model offline"],
            "model_version": "fallback_heuristic"
        }

    async def _trigger_recovery(self, error: Exception):
        """Notify recovery system about failure."""
        from core.emergency_recovery import EmergencyRecovery  # Late import to avoid cycles
        recovery = EmergencyRecovery.get_instance()
        await recovery.handle_component_failure("SuccessPredictor", error)

    def get_health_status(self) -> Dict[str, Any]:
        """Return health status for monitoring system."""
        return {
            "component": "SuccessPredictor",
            "status": "healthy" if self._initialized and self._model else "degraded",
            "model_loaded": self._initialized,
            "last_prediction_time": getattr(self, "_last_pred_time", None)
        }


# Optional: expose as module-level function for plugin use
async def predict_job_success(
    job_data: Dict[str, Any],
    client_profile: Optional[Dict[str, Any]] = None,
    context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Convenience function for external use (e.g., plugins)."""
    # Note: In real system, this would fetch shared instances via ServiceLocator
    # For now, assume caller provides initialized predictor
    raise NotImplementedError("Use instance method instead. Shared instance available via ServiceLocator.")