# AI_FREELANCE_AUTOMATION/core/security/fraud_detector.py
"""
Fraud Detection System for AI Freelance Automation.
Uses machine learning and rule-based heuristics to detect:
- Suspicious client behavior
- Payment fraud
- Fake job postings
- Reputation manipulation
- Platform API abuse

Integrates with anomaly detection, audit logging, and emergency recovery.
"""

import asyncio
import json
import logging
from typing import Dict, Any, List, Optional, Union
from datetime import datetime, timedelta
import hashlib

from core.config.unified_config_manager import UnifiedConfigManager
from core.security.audit_logger import AuditLogger
from core.monitoring.anomaly_detection import AnomalyDetector
from core.learning.continuous_learning_system import ContinuousLearningSystem


class FraudDetector:
    """
    Advanced fraud detection engine using hybrid approach:
    - Statistical anomaly detection
    - Behavioral pattern analysis
    - Reputation scoring
    - Real-time transaction monitoring
    """

    def __init__(
        self,
        config_manager: UnifiedConfigManager,
        audit_logger: Optional[AuditLogger] = None,
        anomaly_detector: Optional[AnomalyDetector] = None,
        learning_system: Optional[ContinuousLearningSystem] = None
    ):
        self.config = config_manager.get_section("security.fraud_detection")
        self.logger = logging.getLogger("FraudDetector")
        self.audit_logger = audit_logger or AuditLogger()
        self.anomaly_detector = anomaly_detector or AnomalyDetector(config_manager)
        self.learning_system = learning_system or ContinuousLearningSystem(config_manager)

        # In-memory risk profiles (persistent storage handled by data layer)
        self.client_risk_cache: Dict[str, Dict[str, Any]] = {}
        self.job_risk_cache: Dict[str, Dict[str, Any]] = {}

        # Load thresholds from config
        self.risk_thresholds = self.config.get("risk_thresholds", {
            "low": 0.3,
            "medium": 0.6,
            "high": 0.85
        })

        self.logger.info("🛡️ FraudDetector initialized with config: %s", self.config.get("detection_mode", "hybrid"))

    async def assess_client_risk(self, client_id: str, client_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Assess fraud risk for a client based on historical and behavioral data.
        Returns structured risk report.
        """
        try:
            risk_score = 0.0
            risk_factors = []

            # 1. Check known bad actors
            if self._is_known_fraudster(client_id):
                risk_score += 0.9
                risk_factors.append("Known fraudster")

            # 2. Analyze behavior patterns
            behavior_risk = await self._analyze_behavioral_patterns(client_data)
            risk_score += behavior_risk * 0.4
            if behavior_risk > 0.7:
                risk_factors.append("Suspicious behavior pattern")

            # 3. Reputation check
            rep_score = client_data.get("reputation_score", 0.5)
            if rep_score < 0.3:
                risk_score += (0.3 - rep_score) * 2
                risk_factors.append("Low reputation score")

            # 4. Anomaly detection via ML
            ml_risk = await self.anomaly_detector.detect_anomalies(
                entity_type="client",
                entity_id=client_id,
                features=client_data
            )
            risk_score += ml_risk * 0.5
            if ml_risk > 0.6:
                risk_factors.append("ML-detected anomaly")

            # Normalize score
            risk_score = min(risk_score, 1.0)

            risk_level = self._classify_risk_level(risk_score)

            report = {
                "client_id": client_id,
                "timestamp": datetime.utcnow().isoformat(),
                "risk_score": round(risk_score, 3),
                "risk_level": risk_level,
                "risk_factors": risk_factors,
                "recommendation": self._get_recommendation(risk_level)
            }

            # Cache result
            self.client_risk_cache[client_id] = report

            # Log to audit trail
            await self.audit_logger.log_security_event(
                event_type="CLIENT_RISK_ASSESSMENT",
                entity_id=client_id,
                details=report
            )

            self.logger.info("🔍 Client risk assessed: %s → %s (%.3f)", client_id, risk_level, risk_score)
            return report

        except Exception as e:
            self.logger.error("💥 Error assessing client risk for %s: %s", client_id, e, exc_info=True)
            await self.audit_logger.log_security_event(
                event_type="FRAUD_DETECTION_ERROR",
                entity_id=client_id,
                details={"error": str(e)}
            )
            # Fail-safe: assume medium risk
            return {
                "client_id": client_id,
                "timestamp": datetime.utcnow().isoformat(),
                "risk_score": 0.6,
                "risk_level": "medium",
                "risk_factors": ["Detection error – fallback applied"],
                "recommendation": "Proceed with caution; manual review recommended"
            }

    async def assess_job_fraud_risk(self, job_id: str, job_data: Dict[str, Any]) -> Dict[str, Any]:
        """Detect fraudulent job postings (e.g., fake budgets, phishing, spam)."""
        try:
            risk_score = 0.0
            risk_factors = []

            title = job_data.get("title", "").lower()
            description = job_data.get("description", "").lower()
            budget = job_data.get("budget", 0)
            platform = job_data.get("platform", "unknown")

            # Red flags in text
            scam_keywords = ["free", "urgent", "no experience", "pay me", "send money", "password", "login"]
            if any(kw in description or kw in title for kw in scam_keywords):
                risk_score += 0.7
                risk_factors.append("Scam keywords detected")

            # Unrealistic budget
            if budget > 0 and budget < 5:
                risk_score += 0.5
                risk_factors.append("Unrealistically low budget")

            # Missing critical fields
            if not job_data.get("requirements") or len(description) < 50:
                risk_score += 0.3
                risk_factors.append("Incomplete job description")

            # ML-based classification
            ml_risk = await self.anomaly_detector.detect_anomalies(
                entity_type="job",
                entity_id=job_id,
                features=job_data
            )
            risk_score += ml_risk * 0.6

            risk_score = min(risk_score, 1.0)
            risk_level = self._classify_risk_level(risk_score)

            report = {
                "job_id": job_id,
                "timestamp": datetime.utcnow().isoformat(),
                "risk_score": round(risk_score, 3),
                "risk_level": risk_level,
                "risk_factors": risk_factors,
                "recommendation": self._get_recommendation(risk_level)
            }

            self.job_risk_cache[job_id] = report

            await self.audit_logger.log_security_event(
                event_type="JOB_FRAUD_ASSESSMENT",
                entity_id=job_id,
                details=report
            )

            self.logger.info("🕵️ Job fraud risk assessed: %s → %s (%.3f)", job_id, risk_level, risk_score)
            return report

        except Exception as e:
            self.logger.error("💥 Error assessing job fraud for %s: %s", job_id, e, exc_info=True)
            await self.audit_logger.log_security_event(
                event_type="FRAUD_DETECTION_ERROR",
                entity_id=job_id,
                details={"error": str(e)}
            )
            return {
                "job_id": job_id,
                "timestamp": datetime.utcnow().isoformat(),
                "risk_score": 0.5,
                "risk_level": "medium",
                "risk_factors": ["Detection error"],
                "recommendation": "Manual review advised"
            }

    async def assess_payment_fraud(self, payment_data: Dict[str, Any]) -> Dict[str, Any]:
        """Real-time payment fraud detection."""
        try:
            amount = payment_data.get("amount", 0)
            method = payment_data.get("method", "unknown")
            client_id = payment_data.get("client_id", "unknown")
            ip_hash = payment_data.get("ip_hash", "")

            risk_score = 0.0
            risk_factors = []

            # Unusual amount
            if amount > 10000:  # configurable threshold
                risk_score += 0.4
                risk_factors.append("High-value transaction")

            # New payment method from client
            if not self._is_known_payment_method(client_id, method):
                risk_score += 0.3
                risk_factors.append("New payment method")

            # IP geolocation mismatch (simplified)
            if ip_hash and self._is_suspicious_ip(ip_hash):
                risk_score += 0.5
                risk_factors.append("Suspicious IP origin")

            # ML anomaly
            ml_risk = await self.anomaly_detector.detect_anomalies(
                entity_type="payment",
                entity_id=hashlib.sha256(json.dumps(payment_data, sort_keys=True).encode()).hexdigest()[:16],
                features=payment_data
            )
            risk_score += ml_risk * 0.7

            risk_score = min(risk_score, 1.0)
            risk_level = self._classify_risk_level(risk_score)

            report = {
                "payment_id": payment_data.get("id", "unknown"),
                "timestamp": datetime.utcnow().isoformat(),
                "risk_score": round(risk_score, 3),
                "risk_level": risk_level,
                "risk_factors": risk_factors,
                "recommendation": self._get_recommendation(risk_level, context="payment")
            }

            await self.audit_logger.log_security_event(
                event_type="PAYMENT_FRAUD_ASSESSMENT",
                entity_id=payment_data.get("id", "unknown"),
                details=report
            )

            return report

        except Exception as e:
            self.logger.error("💥 Payment fraud assessment failed: %s", e, exc_info=True)
            return {
                "risk_score": 0.6,
                "risk_level": "medium",
                "risk_factors": ["System error"],
                "recommendation": "Hold payment; manual verification required"
            }

    def _is_known_fraudster(self, client_id: str) -> bool:
        # In real system: query blacklists, external APIs, or internal DB
        # For now: simulate with config
        blacklisted = self.config.get("blacklisted_clients", [])
        return client_id in blacklisted

    def _is_known_payment_method(self, client_id: str, method: str) -> bool:
        # Placeholder — would integrate with client profile service
        return True  # optimistic default

    def _is_suspicious_ip(self, ip_hash: str) -> bool:
        # In production: integrate with threat intelligence feeds
        suspicious_hashes = self.config.get("suspicious_ip_hashes", [])
        return ip_hash in suspicious_hashes

    async def _analyze_behavioral_patterns(self, client_data: Dict[str, Any]) -> float:
        """Return risk score [0.0–1.0] based on behavior."""
        # Example: rapid job posting, inconsistent communication style
        messages = client_data.get("recent_messages", [])
        if len(messages) > 10 and all(len(m) < 10 for m in messages):
            return 0.8  # likely bot
        return 0.2

    def _classify_risk_level(self, score: float) -> str:
        if score >= self.risk_thresholds["high"]:
            return "high"
        elif score >= self.risk_thresholds["medium"]:
            return "medium"
        else:
            return "low"

    def _get_recommendation(self, level: str, context: str = "general") -> str:
        if level == "high":
            if context == "payment":
                return "Block transaction immediately; notify security team"
            return "Reject engagement; flag account for review"
        elif level == "medium":
            if context == "payment":
                return "Hold funds; request identity verification"
            return "Proceed with caution; enable enhanced monitoring"
        else:
            return "Proceed normally"

    async def get_cached_client_risk(self, client_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve cached risk assessment (valid for 24h)."""
        cached = self.client_risk_cache.get(client_id)
        if cached:
            ts = datetime.fromisoformat(cached["timestamp"])
            if datetime.utcnow() - ts < timedelta(hours=24):
                return cached
            del self.client_risk_cache[client_id]
        return None

    async def clear_cache(self):
        """Clear internal caches (e.g., after model update)."""
        self.client_risk_cache.clear()
        self.job_risk_cache.clear()
        self.logger.info("🧹 FraudDetector cache cleared")


# Make module import-safe
if __name__ == "__main__":
    # Example usage (not executed in production)
    pass