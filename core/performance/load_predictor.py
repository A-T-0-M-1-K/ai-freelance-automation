# core/performance/load_predictor.py
"""
Load Predictor — predicts future system load based on historical metrics.
Used by auto-scaler and resource optimizer to anticipate demand spikes.
Integrates with monitoring system and performance cache.
"""

import logging
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from pathlib import Path

import numpy as np
from sklearn.linear_model import LinearRegression
from sklearn.preprocessing import StandardScaler

from core.config.unified_config_manager import UnifiedConfigManager
from core.monitoring.metrics_collector import MetricsCollector


class LoadPredictor:
    """
    Predicts system load (CPU%, memory usage, active jobs, etc.) for the next N minutes.
    Uses lightweight ML model trained on recent metrics.
    """

    def __init__(self, config: UnifiedConfigManager):
        self.config = config
        self.logger = logging.getLogger("LoadPredictor")
        self.model_cache: Dict[str, Tuple[LinearRegression, StandardScaler]] = {}
        self._metrics_collector = None  # Lazy-loaded via property
        self._prediction_window_minutes = self.config.get("performance.prediction_window_minutes", default=15)
        self._history_window_hours = self.config.get("performance.history_window_hours", default=24)
        self._model_retrain_interval = self.config.get("performance.model_retrain_interval_minutes", default=60)
        self._last_retrain: Dict[str, datetime] = {}

        self.logger.info("Intialized LoadPredictor with window=%d min, history=%d h",
                         self._prediction_window_minutes, self._history_window_hours)

    @property
    def metrics_collector(self) -> MetricsCollector:
        """Lazy-load MetricsCollector to avoid circular imports."""
        if self._metrics_collector is None:
            from core.monitoring.metrics_collector import MetricsCollector
            self._metrics_collector = MetricsCollector(self.config)
        return self._metrics_collector

    def _prepare_features(self, metric_name: str, hours: int = 24) -> Tuple[np.ndarray, np.ndarray]:
        """
        Prepare time-series features for training/prediction.
        Features: hour_of_day, day_of_week, trend, rolling averages.
        """
        now = datetime.utcnow()
        cutoff = now - timedelta(hours=hours)
        raw_data = self.metrics_collector.get_metric_history(
            metric_name=metric_name,
            since=cutoff
        )

        if not raw_data:
            self.logger.warning("No historical data for metric '%s' — returning zero prediction", metric_name)
            return np.array([]), np.array([])

        # Sort by timestamp
        raw_data.sort(key=lambda x: x["timestamp"])
        timestamps = [datetime.fromisoformat(d["timestamp"]) for d in raw_data]
        values = np.array([float(d["value"]) for d in raw_data])

        # Feature engineering
        features = []
        for ts in timestamps:
            features.append([
                ts.hour,
                ts.weekday(),
                (ts - timestamps[0]).total_seconds() / 3600,  # Trend (hours since start)
                np.mean(values[max(0, len(features)-5):len(features)]) if features else values[0],  # Rolling avg (5 points)
            ])

        X = np.array(features)
        y = values

        return X, y

    def _ensure_model(self, metric_name: str) -> Tuple[LinearRegression, StandardScaler]:
        """Ensure a trained model exists for the given metric."""
        now = datetime.utcnow()

        if metric_name not in self._last_retrain:
            self._last_retrain[metric_name] = now - timedelta(minutes=self._model_retrain_interval + 1)

        needs_retrain = (
            metric_name not in self.model_cache or
            (now - self._last_retrain[metric_name]).total_seconds() / 60 > self._model_retrain_interval
        )

        if needs_retrain:
            self.logger.debug("Retraining model for metric '%s'", metric_name)
            X, y = self._prepare_features(metric_name, self._history_window_hours)
            if X.size == 0:
                # Fallback: return dummy model that predicts last known value
                dummy_model = LinearRegression()
                dummy_model.fit(np.array([[0]]), np.array([0]))
                scaler = StandardScaler()
                scaler.fit(np.array([[0]]))
                self.model_cache[metric_name] = (dummy_model, scaler)
                self._last_retrain[metric_name] = now
                return dummy_model, scaler

            scaler = StandardScaler()
            X_scaled = scaler.fit_transform(X)
            model = LinearRegression()
            model.fit(X_scaled, y)
            self.model_cache[metric_name] = (model, scaler)
            self._last_retrain[metric_name] = now
            self.logger.info("Trained new model for metric '%s' on %d samples", metric_name, len(y))

        return self.model_cache[metric_name]

    def predict_load(self, metric_name: str, future_minutes: Optional[int] = None) -> float:
        """
        Predict metric value in `future_minutes` (default: config.prediction_window_minutes).
        Returns predicted value (e.g., CPU% = 72.3).
        """
        if future_minutes is None:
            future_minutes = self._prediction_window_minutes

        model, scaler = self._ensure_model(metric_name)

        # Build future feature vector
        future_time = datetime.utcnow() + timedelta(minutes=future_minutes)
        last_known_value = self.metrics_collector.get_latest_metric(metric_name)
        rolling_avg = last_known_value if last_known_value is not None else 0.0

        future_features = np.array([[
            future_time.hour,
            future_time.weekday(),
            (future_time - datetime.utcnow()).total_seconds() / 3600 + 0.1,  # Small trend increment
            rolling_avg
        ]])

        try:
            future_scaled = scaler.transform(future_features)
            prediction = model.predict(future_scaled)[0]
            prediction = max(0.0, min(100.0, prediction))  # Clamp to [0, 100] for percentages
            self.logger.debug("Predicted %s in %d min: %.2f", metric_name, future_minutes, prediction)
            return float(prediction)
        except Exception as e:
            self.logger.error("Prediction failed for '%s': %s — falling back to latest value", metric_name, e)
            return float(last_known_value) if last_known_value is not None else 0.0

    def predict_multiple(self, metric_names: List[str], future_minutes: int = 15) -> Dict[str, float]:
        """Predict multiple metrics at once."""
        return {
            name: self.predict_load(name, future_minutes)
            for name in metric_names
        }

    def get_critical_threshold(self, metric_name: str) -> float:
        """Get configured critical threshold for a metric (e.g., CPU > 85%)."""
        thresholds = self.config.get("performance.critical_thresholds", default={})
        return float(thresholds.get(metric_name, 85.0))


# Example usage (not executed in production):
if __name__ == "__main__":
    from core.config.unified_config_manager import UnifiedConfigManager
    logging.basicConfig(level=logging.DEBUG)
    config = UnifiedConfigManager()
    predictor = LoadPredictor(config)
    cpu_pred = predictor.predict_load("cpu_usage_percent", future_minutes=10)
    print(f"Predicted CPU in 10 min: {cpu_pred:.2f}%")