# AI_FREELANCE_AUTOMATION/core/analytics/price_predictor.py

"""
Price Predictor Module
======================

Predicts optimal bid prices for freelance jobs based on:
- Historical job data
- Market trends
- Client behavior
- Competition analysis
- Service type (transcription, translation, copywriting)
- Urgency and complexity

Integrates with:
- market_analyzer for real-time platform rates
- predictive_analytics for trend forecasting
- AI models for dynamic pricing strategy
- job history from data/jobs/

Follows security, logging, and monitoring standards.
"""

import json
import logging
from typing import Dict, Any, Optional, List, Union
from pathlib import Path
from datetime import datetime, timedelta

import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error

from core.config.unified_config_manager import UnifiedConfigManager
from core.monitoring.intelligent_monitoring_system import MetricsCollector
from core.security.audit_logger import AuditLogger
from core.ai_management.intelligent_model_manager import IntelligentModelManager
from core.analytics.market_analyzer import MarketAnalyzer


class PricePredictor:
    """
    AI-powered price prediction engine for freelance bidding.
    Continuously learns from historical data and market signals.
    """

    def __init__(
        self,
        config_manager: UnifiedConfigManager,
        model_manager: Optional[IntelligentModelManager] = None,
        market_analyzer: Optional[MarketAnalyzer] = None,
        metrics_collector: Optional[MetricsCollector] = None,
        audit_logger: Optional[AuditLogger] = None,
    ):
        self.config = config_manager
        self.logger = logging.getLogger("PricePredictor")
        self.model_manager = model_manager or IntelligentModelManager(self.config)
        self.market_analyzer = market_analyzer or MarketAnalyzer(self.config)
        self.metrics = metrics_collector or MetricsCollector()
        self.audit_logger = audit_logger or AuditLogger()

        # Internal state
        self._model: Optional[RandomForestRegressor] = None
        self._scaler: Optional[StandardScaler] = None
        self._is_trained = False
        self._last_training = None
        self._data_path = Path("data/jobs/jobs_index.json")

        # Load configuration
        self._load_config()
        self._ensure_directories()

        self.logger.info("✅ PricePredictor initialized.")

    def _load_config(self):
        """Load predictor-specific settings."""
        analytics_cfg = self.config.get("analytics", {})
        self.retrain_threshold = analytics_cfg.get("price_predictor_retrain_threshold", 50)
        self.min_training_samples = analytics_cfg.get("min_training_samples", 100)
        self.default_markup = analytics_cfg.get("default_markup_percent", 20)
        self.max_price_cap = analytics_cfg.get("max_price_cap_usd", 500.0)
        self.min_price_floor = analytics_cfg.get("min_price_floor_usd", 5.0)

    def _ensure_directories(self):
        """Ensure required directories exist."""
        self._data_path.parent.mkdir(parents=True, exist_ok=True)

    def _load_historical_data(self) -> List[Dict[str, Any]]:
        """Load historical job data for training."""
        if not self._data_path.exists():
            self.logger.warning("No historical job data found for price prediction.")
            return []

        try:
            with open(self._data_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return list(data.values()) if isinstance(data, dict) else data
        except Exception as e:
            self.logger.error(f"Failed to load historical job data: {e}")
            self.audit_logger.log_security_event(
                "PRICE_PREDICTOR_DATA_LOAD_FAILURE",
                {"error": str(e), "path": str(self._data_path)}
            )
            return []

    def _extract_features(self, job: Dict[str, Any]) -> Optional[np.ndarray]:
        """
        Extract numerical features from a job for ML model.
        Returns None if job is not suitable for pricing.
        """
        try:
            # Normalize service type
            service_type = job.get("service_type", "").lower()
            service_map = {"transcription": 0, "translation": 1, "copywriting": 2, "editing": 3}
            service_encoded = service_map.get(service_type, -1)
            if service_encoded == -1:
                return None

            # Features
            word_count = job.get("word_count", 0)
            duration_sec = job.get("duration_seconds", 0)
            urgency_hours = job.get("urgency_hours", 168)  # default: 1 week
            client_rating = job.get("client_rating", 4.5)
            client_jobs = job.get("client_total_jobs", 10)
            complexity_score = job.get("complexity_score", 0.5)

            # Market context
            market_rate = self.market_analyzer.get_average_rate_for(service_type)
            competition_level = self.market_analyzer.get_competition_level(job)

            features = np.array([
                service_encoded,
                word_count,
                duration_sec,
                urgency_hours,
                client_rating,
                client_jobs,
                complexity_score,
                market_rate,
                competition_level
            ], dtype=np.float32)

            return features

        except Exception as e:
            self.logger.debug(f"Feature extraction failed for job {job.get('job_id')}: {e}")
            return None

    def _prepare_training_data(self) -> tuple[Optional[np.ndarray], Optional[np.ndarray]]:
        """Prepare X (features) and y (labels) for training."""
        jobs = self._load_historical_data()
        if len(jobs) < self.min_training_samples:
            self.logger.info(f"Insufficient data for training ({len(jobs)} < {self.min_training_samples})")
            return None, None

        X, y = [], []
        for job in jobs:
            if job.get("status") != "completed":
                continue
            price = job.get("final_price_usd")
            if price is None or price <= 0:
                continue
            features = self._extract_features(job)
            if features is not None:
                X.append(features)
                y.append(price)

        if len(X) < self.min_training_samples:
            self.logger.info(f"Not enough valid samples after filtering ({len(X)})")
            return None, None

        return np.array(X), np.array(y)

    def train(self, force: bool = False) -> bool:
        """
        Train the price prediction model.
        Returns True if training was successful.
        """
        if not force and self._is_trained and self._last_training:
            # Check if retraining is needed
            jobs_since = self._count_new_jobs_since(self._last_training)
            if jobs_since < self.retrain_threshold:
                self.logger.debug("Retraining not needed yet.")
                return True

        self.logger.info("🔄 Starting price prediction model training...")

        X, y = self._prepare_training_data()
        if X is None or y is None:
            self.logger.warning("Training aborted: insufficient data.")
            return False

        try:
            # Split and scale
            X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
            self._scaler = StandardScaler()
            X_train_scaled = self._scaler.fit_transform(X_train)
            X_test_scaled = self._scaler.transform(X_test)

            # Train model
            self._model = RandomForestRegressor(
                n_estimators=100,
                max_depth=10,
                random_state=42,
                n_jobs=-1
            )
            self._model.fit(X_train_scaled, y_train)

            # Evaluate
            y_pred = self._model.predict(X_test_scaled)
            mae = mean_absolute_error(y_test, y_pred)
            self.logger.info(f"✅ Model trained. MAE: ${mae:.2f}")

            # Log metrics
            self.metrics.record("price_predictor.mae", mae)
            self.metrics.record("price_predictor.training_samples", len(y))

            self._is_trained = True
            self._last_training = datetime.utcnow()
            return True

        except Exception as e:
            self.logger.error(f"Training failed: {e}", exc_info=True)
            self.audit_logger.log_security_event(
                "PRICE_PREDICTOR_TRAINING_FAILURE",
                {"error": str(e)}
            )
            return False

    def _count_new_jobs_since(self, since: datetime) -> int:
        """Count how many completed jobs were added since last training."""
        try:
            jobs = self._load_historical_data()
            count = 0
            for job in jobs:
                if job.get("status") == "completed":
                    updated_str = job.get("updated_at", job.get("created_at"))
                    if updated_str:
                        updated = datetime.fromisoformat(updated_str.replace("Z", "+00:00"))
                        if updated > since:
                            count += 1
            return count
        except Exception:
            return 0

    def predict_price(self, job: Dict[str, Any]) -> Dict[str, Union[float, str, bool]]:
        """
        Predict optimal bid price for a new job.
        Returns structured result with confidence and metadata.
        """
        # Ensure model is ready
        if not self._is_trained:
            success = self.train()
            if not success:
                # Fallback to rule-based pricing
                return self._fallback_pricing(job)

        features = self._extract_features(job)
        if features is None:
            self.logger.warning("Could not extract features; using fallback pricing.")
            return self._fallback_pricing(job)

        try:
            scaled_features = self._scaler.transform(features.reshape(1, -1))
            predicted = float(self._model.predict(scaled_features)[0])

            # Apply business rules
            predicted = max(self.min_price_floor, min(self.max_price_cap, predicted))
            final_price = round(predicted, 2)

            # Confidence estimation (simplified)
            # In production, use quantile regression or ensemble variance
            confidence = 0.85  # placeholder; could be improved

            result = {
                "predicted_price_usd": final_price,
                "confidence": confidence,
                "method": "ml_model",
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }

            self.logger.info(f"Predicted price for job {job.get('job_id')}: ${final_price}")
            self.metrics.record("price_predictor.prediction_count", 1)
            return result

        except Exception as e:
            self.logger.error(f"Prediction error: {e}", exc_info=True)
            return self._fallback_pricing(job)

    def _fallback_pricing(self, job: Dict[str, Any]) -> Dict[str, Union[float, str, bool]]:
        """Rule-based fallback pricing when ML fails."""
        base_rate = self.market_analyzer.get_average_rate_for(job.get("service_type", "copywriting"))
        word_count = job.get("word_count", 500)
        duration = job.get("duration_seconds", 0)

        if job.get("service_type") == "transcription":
            price = max(0.1, base_rate) * (duration / 60)  # per minute
        elif job.get("service_type") == "translation":
            price = max(0.05, base_rate) * word_count
        else:
            price = max(0.03, base_rate) * word_count

        # Apply markup
        price *= (1 + self.default_markup / 100)

        final_price = round(max(self.min_price_floor, min(self.max_price_cap, price)), 2)

        result = {
            "predicted_price_usd": final_price,
            "confidence": 0.6,
            "method": "rule_based_fallback",
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }

        self.logger.warning(f"Used fallback pricing: ${final_price}")
        self.metrics.record("price_predictor.fallback_usage", 1)
        return result

    def get_model_info(self) -> Dict[str, Any]:
        """Return metadata about current model state."""
        return {
            "is_trained": self._is_trained,
            "last_training": self._last_training.isoformat() + "Z" if self._last_training else None,
            "training_samples": len(self._load_historical_data()) if self._is_trained else 0,
            "config": {
                "retrain_threshold": self.retrain_threshold,
                "min_samples": self.min_training_samples,
                "price_range": [self.min_price_floor, self.max_price_cap]
            }
        }


# For module-level usage
def create_price_predictor(config_manager: UnifiedConfigManager) -> PricePredictor:
    """Factory function for DI container."""
    return PricePredictor(config_manager=config_manager)