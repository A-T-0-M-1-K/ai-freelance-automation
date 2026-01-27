"""
Anomaly Detection System for AI Freelance Automation.
Detects behavioral, performance, and security anomalies using statistical and ML-based methods.
Integrates with IntelligentMonitoringSystem and AlertManager.
"""

import logging
import math
from typing import Dict, List, Any, Optional, Tuple, Union
from dataclasses import dataclass
from datetime import datetime, timedelta
import numpy as np
from scipy import stats

# Local imports (relative to core/)
from .alert_manager import AlertManager
from ..config.unified_config_manager import UnifiedConfigManager
from ..security.audit_logger import AuditLogger

logger = logging.getLogger(__name__)


@dataclass
class Anomaly:
    """Represents a detected anomaly."""
    metric_name: str
    timestamp: datetime
    severity: str  # 'low', 'medium', 'high', 'critical'
    value: float
    expected_range: Tuple[float, float]
    description: str
    component: str
    metadata: Dict[str, Any]


class AnomalyDetectionEngine:
    """
    Core engine for real-time anomaly detection across system metrics.
    Uses adaptive thresholds, Z-score, IQR, and exponential moving average.
    """

    def __init__(
        self,
        config: UnifiedConfigManager,
        alert_manager: AlertManager,
        audit_logger: Optional[AuditLogger] = None
    ):
        self.config = config
        self.alert_manager = alert_manager
        self.audit_logger = audit_logger or AuditLogger()
        self._history: Dict[str, List[float]] = {}
        self._timestamps: Dict[str, List[datetime]] = {}
        self._ema: Dict[str, float] = {}  # Exponential Moving Average
        self._ema_alpha = config.get("monitoring.anomaly_detection.ema_alpha", 0.3)
        self._window_size = config.get("monitoring.anomaly_detection.window_size", 50)
        self._z_threshold = config.get("monitoring.anomaly_detection.z_score_threshold", 3.0)
        self._iqr_factor = config.get("monitoring.anomaly_detection.iqr_factor", 1.5)

        logger.info("Intialized AnomalyDetectionEngine with EMA α=%.2f, window=%d",
                    self._ema_alpha, self._window_size)

    def _update_history(self, metric_name: str, value: float, timestamp: datetime):
        """Maintain sliding window of recent values."""
        if metric_name not in self._history:
            self._history[metric_name] = []
            self._timestamps[metric_name] = []
            self._ema[metric_name] = value

        # Update EMA
        self._ema[metric_name] = (
            self._ema_alpha * value + (1 - self._ema_alpha) * self._ema[metric_name]
        )

        # Append new value
        self._history[metric_name].append(value)
        self._timestamps[metric_name].append(timestamp)

        # Trim window
        if len(self._history[metric_name]) > self._window_size:
            self._history[metric_name].pop(0)
            self._timestamps[metric_name].pop(0)

    def _calculate_expected_range(self, metric_name: str) -> Tuple[float, float]:
        """Calculate dynamic expected range using IQR and EMA."""
        values = self._history[metric_name]
        if len(values) < 5:
            # Not enough data — use EMA ± 3σ (assume normality)
            ema = self._ema[metric_name]
            std = np.std(values) if len(values) > 1 else 0.1
            return ema - 3 * std, ema + 3 * std

        # IQR method
        q75, q25 = np.percentile(values, [75, 25])
        iqr = q75 - q25
        lower = q25 - self._iqr_factor * iqr
        upper = q75 + self._iqr_factor * iqr

        # Also respect EMA trend
        ema = self._ema[metric_name]
        buffer = max(0.1, 0.1 * abs(ema))  # 10% buffer or 0.1, whichever is larger
        lower = max(lower, ema - buffer)
        upper = min(upper, ema + buffer)

        return float(lower), float(upper)

    def _assess_severity(self, z_score: float) -> str:
        """Map Z-score to severity level."""
        abs_z = abs(z_score)
        if abs_z >= 4.0:
            return "critical"
        elif abs_z >= 3.0:
            return "high"
        elif abs_z >= 2.0:
            return "medium"
        else:
            return "low"

    def detect(
        self,
        metric_name: str,
        value: float,
        component: str = "unknown",
        metadata: Optional[Dict[str, Any]] = None,
        timestamp: Optional[datetime] = None
    ) -> Optional[Anomaly]:
        """
        Detect anomaly in a single metric value.
        Returns Anomaly object if detected, None otherwise.
        """
        if timestamp is None:
            timestamp = datetime.utcnow()

        self._update_history(metric_name, value, timestamp)

        if len(self._history[metric_name]) < 5:
            return None  # Not enough data

        lower, upper = self._calculate_expected_range(metric_name)

        if lower <= value <= upper:
            return None  # Normal

        # Calculate Z-score for severity
        mean = np.mean(self._history[metric_name])
        std = np.std(self._history[metric_name])
        z_score = (value - mean) / (std if std > 1e-6 else 1e-6)

        severity = self._assess_severity(z_score)
        description = (
            f"Metric '{metric_name}' ({component}) deviated from expected range "
            f"[{lower:.3f}, {upper:.3f}] with value {value:.3f} (Z={z_score:.2f})"
        )

        anomaly = Anomaly(
            metric_name=metric_name,
            timestamp=timestamp,
            severity=severity,
            value=value,
            expected_range=(lower, upper),
            description=description,
            component=component,
            metadata=metadata or {}
        )

        logger.warning("🚨 Anomaly detected: %s", anomaly.description)
        self.audit_logger.log_security_event(
            event_type="ANOMALY_DETECTED",
            details={
                "metric": metric_name,
                "value": value,
                "severity": severity,
                "component": component
            }
        )

        # Trigger alert
        self.alert_manager.send_alert(
            title=f"Anomaly in {component}: {metric_name}",
            message=anomaly.description,
            severity=severity,
            category="system_anomaly",
            metadata={
                "metric": metric_name,
                "value": value,
                "expected_min": lower,
                "expected_max": upper,
                "z_score": z_score,
                "component": component,
                **(metadata or {})
            }
        )

        return anomaly

    def get_recent_anomalies(self, last_minutes: int = 60) -> List[Anomaly]:
        """Return anomalies from the last N minutes (stub for future integration)."""
        # In a full system, this would query a persistent store.
        # For now, it's a placeholder.
        return []


# Factory function for DI compatibility
def create_anomaly_detector(
    config: UnifiedConfigManager,
    alert_manager: AlertManager,
    audit_logger: Optional[AuditLogger] = None
) -> AnomalyDetectionEngine:
    """Factory to support dependency injection."""
    return AnomalyDetectionEngine(config, alert_manager, audit_logger)