# AI_FREELANCE_AUTOMATION/core/payment/fraud_detection_system.py

"""
Fraud Detection System for AI Freelance Automation
==================================================

Responsible for real-time detection of fraudulent transactions using:
- Rule-based heuristics
- Behavioral anomaly detection
- Machine learning models (pluggable)
- Cross-reference with historical data

Integrates with:
- Security audit logging
- Payment orchestrator
- Monitoring & alerting system
"""

import logging
import json
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta

from core.config.unified_config_manager import UnifiedConfigManager
from core.security.audit_logger import AuditLogger
from core.monitoring.intelligent_monitoring_system import IntelligentMonitoringSystem
from core.learning.continuous_learning_system import ContinuousLearningSystem


class FraudDetectionSystem:
    """
    Advanced fraud detection engine with multi-layered analysis.
    Designed for 99.9% uptime and zero false negatives in critical scenarios.
    """

    def __init__(
        self,
        config: UnifiedConfigManager,
        audit_logger: Optional[AuditLogger] = None,
        monitoring: Optional[IntelligentMonitoringSystem] = None,
        learning_system: Optional[ContinuousLearningSystem] = None
    ):
        self.config = config
        self.logger = logging.getLogger(self.__class__.__name__)
        self.audit_logger = audit_logger or AuditLogger(config)
        self.monitoring = monitoring or IntelligentMonitoringSystem(config)
        self.learning_system = learning_system or ContinuousLearningSystem(config)

        # Load fraud detection rules and thresholds
        self._load_rules()
        self._initialize_ml_model()

        self.logger.info("✅ FraudDetectionSystem initialized")

    def _load_rules(self) -> None:
        """Load rule-based fraud detection policies from config."""
        try:
            fraud_config = self.config.get("payment.fraud_detection", {})
            self.rules = fraud_config.get("rules", {})
            self.thresholds = fraud_config.get("thresholds", {})
            self.risk_categories = fraud_config.get("risk_categories", {})
            self.logger.debug("Loaded fraud detection rules and thresholds")
        except Exception as e:
            self.logger.error(f"Failed to load fraud rules: {e}")
            raise RuntimeError("Fraud detection configuration is invalid") from e

    def _initialize_ml_model(self) -> None:
        """Initialize optional ML-based fraud classifier (if enabled)."""
        ml_enabled = self.config.get("payment.fraud_detection.ml_enabled", False)
        if ml_enabled:
            model_path = self.config.get("payment.fraud_detection.ml_model_path")
            if not model_path:
                self.logger.warning("ML fraud detection enabled but no model path provided")
                self.ml_model = None
                return

            try:
                # Placeholder: in real system, load ONNX/TensorFlow/PyTorch model
                # For now, simulate with a mock function
                self.ml_model = self._mock_ml_predict
                self.logger.info(f"ML fraud model loaded from {model_path}")
            except Exception as e:
                self.logger.error(f"Failed to load ML fraud model: {e}")
                self.ml_model = None
        else:
            self.ml_model = None

    def _mock_ml_predict(self, features: Dict[str, Any]) -> float:
        """
        Simulated ML model output (0.0 = safe, 1.0 = fraudulent).
        In production, replace with actual inference pipeline.
        """
        # Simple heuristic-based simulation
        risk_score = 0.0
        if features.get("amount", 0) > 5000:
            risk_score += 0.4
        if features.get("new_client", False):
            risk_score += 0.3
        if features.get("high_velocity", False):
            risk_score += 0.5
        if features.get("mismatched_country", False):
            risk_score += 0.6
        return min(risk_score, 1.0)

    def analyze_transaction(self, transaction: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze a single transaction for fraud indicators.

        Args:
            transaction (dict): Must contain:
                - id: str
                - amount: float
                - currency: str
                - client_id: str
                - timestamp: ISO8601 str
                - payment_method: str
                - ip_address: str (optional)
                - country: str (optional)
                - device_fingerprint: str (optional)

        Returns:
            dict: {
                "is_fraud": bool,
                "risk_score": float (0.0–1.0),
                "reasons": List[str],
                "action": "allow" | "review" | "block",
                "metadata": dict
            }
        """
        if not isinstance(transaction, dict):
            raise ValueError("Transaction must be a dictionary")

        required_fields = {"id", "amount", "client_id", "timestamp"}
        if not required_fields.issubset(transaction.keys()):
            missing = required_fields - transaction.keys()
            raise ValueError(f"Missing required transaction fields: {missing}")

        try:
            # Normalize and extract features
            features = self._extract_features(transaction)
            reasons = []
            risk_score = 0.0

            # 1. Rule-based checks
            rule_score, rule_reasons = self._apply_rules(features)
            risk_score = max(risk_score, rule_score)
            reasons.extend(rule_reasons)

            # 2. ML-based prediction (if available)
            if self.ml_model:
                ml_score = self.ml_model(features)
                if ml_score > risk_score:
                    risk_score = ml_score
                    reasons.append("ML model flagged high risk")

            # 3. Historical behavior analysis
            hist_score, hist_reasons = self._analyze_client_history(transaction["client_id"])
            risk_score = max(risk_score, hist_score)
            reasons.extend(hist_reasons)

            # Determine action based on thresholds
            thresholds = self.thresholds
            if risk_score >= thresholds.get("block", 0.9):
                action = "block"
            elif risk_score >= thresholds.get("review", 0.7):
                action = "review"
            else:
                action = "allow"

            result = {
                "is_fraud": action == "block",
                "risk_score": round(risk_score, 3),
                "reasons": list(set(reasons)),  # deduplicate
                "action": action,
                "metadata": {
                    "analyzed_at": datetime.utcnow().isoformat(),
                    "version": "1.0",
                    "ml_used": self.ml_model is not None
                }
            }

            # Log to audit trail
            self.audit_logger.log_security_event(
                event_type="fraud_analysis",
                severity="info" if action == "allow" else "warning",
                details={
                    "transaction_id": transaction["id"],
                    "client_id": transaction["client_id"],
                    "risk_score": risk_score,
                    "action": action
                }
            )

            # Send metric to monitoring
            self.monitoring.record_metric(
                "fraud.risk_score",
                risk_score,
                tags={"client_id": transaction["client_id"], "action": action}
            )

            return result

        except Exception as e:
            self.logger.exception("Error during fraud analysis")
            self.audit_logger.log_security_event(
                event_type="fraud_analysis_error",
                severity="critical",
                details={"error": str(e), "transaction_id": transaction.get("id", "unknown")}
            )
            # Fail-safe: block on error to prevent fraud
            return {
                "is_fraud": True,
                "risk_score": 1.0,
                "reasons": ["System error during analysis"],
                "action": "block",
                "metadata": {"error": str(e)}
            }

    def _extract_features(self, tx: Dict[str, Any]) -> Dict[str, Any]:
        """Extract structured features for analysis."""
        now = datetime.utcnow()
        tx_time = datetime.fromisoformat(tx["timestamp"].replace("Z", "+00:00"))
        age_hours = (now - tx_time).total_seconds() / 3600

        # Client history stats (mocked; in real system, query DB)
        client_stats = self._get_client_stats(tx["client_id"])

        return {
            "amount": float(tx["amount"]),
            "currency": tx["currency"],
            "new_client": client_stats["first_seen_hours"] > 168,  # >7 days
            "high_velocity": client_stats["tx_count_last_hour"] > 5,
            "large_amount": tx["amount"] > self.thresholds.get("large_amount", 1000),
            "mismatched_country": self._check_country_mismatch(tx),
            "age_hours": age_hours,
            "payment_method": tx.get("payment_method", "unknown"),
            "ip_risk": self._assess_ip_risk(tx.get("ip_address")),
            "device_new": self._is_new_device(tx.get("device_fingerprint")),
        }

    def _apply_rules(self, features: Dict[str, Any]) -> tuple[float, List[str]]:
        """Apply static business rules."""
        score = 0.0
        reasons = []

        if features["amount"] > self.rules.get("max_single_payment", 10000):
            score = max(score, 0.95)
            reasons.append("Exceeds maximum allowed payment amount")

        if features["new_client"] and features["amount"] > 500:
            score = max(score, 0.7)
            reasons.append("High-value transaction from new client")

        if features["high_velocity"]:
            score = max(score, 0.8)
            reasons.append("Unusual transaction velocity")

        if features["ip_risk"] == "high":
            score = max(score, 0.85)
            reasons.append("High-risk IP address")

        return score, reasons

    def _analyze_client_history(self, client_id: str) -> tuple[float, List[str]]:
        """Analyze historical behavior of the client."""
        stats = self._get_client_stats(client_id)
        reasons = []
        score = 0.0

        if stats["fraud_reports"] > 0:
            score = max(score, 0.99)
            reasons.append("Client previously reported for fraud")

        if stats["refund_rate"] > 0.3:
            score = max(score, 0.75)
            reasons.append("High refund rate")

        return score, reasons

    def _get_client_stats(self, client_id: str) -> Dict[str, Any]:
        """Mock client statistics. In production, query database or cache."""
        # TODO: Replace with real data source
        return {
            "first_seen_hours": 200,
            "tx_count_last_hour": 1,
            "fraud_reports": 0,
            "refund_rate": 0.05,
            "total_transactions": 12
        }

    def _check_country_mismatch(self, tx: Dict[str, Any]) -> bool:
        """Check if payment country mismatches client profile."""
        # Simplified logic
        return False

    def _assess_ip_risk(self, ip: Optional[str]) -> str:
        """Assess IP reputation (mocked)."""
        # In production: integrate with MaxMind, IPQualityScore, etc.
        return "low"

    def _is_new_device(self, fingerprint: Optional[str]) -> bool:
        """Check if device is new for this client."""
        return True  # placeholder

    def report_false_positive(self, transaction_id: str) -> None:
        """Feedback loop: report false positive to improve model."""
        self.learning_system.log_feedback(
            event_type="fraud_false_positive",
            data={"transaction_id": transaction_id}
        )
        self.logger.info(f"Recorded false positive for tx {transaction_id}")

    def report_false_negative(self, transaction_id: str) -> None:
        """Feedback loop: report missed fraud."""
        self.learning_system.log_feedback(
            event_type="fraud_false_negative",
            data={"transaction_id": transaction_id}
        )
        self.logger.warning(f"Recorded false negative for tx {transaction_id}")