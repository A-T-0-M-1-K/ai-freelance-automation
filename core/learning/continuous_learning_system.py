# AI_FREELANCE_AUTOMATION/core/learning/continuous_learning_system.py

"""
Continuous Learning System — Core module for autonomous skill improvement.
Analyzes completed jobs, client feedback, and system performance to refine AI behavior,
update knowledge base, and optimize future decisions without human intervention.

Key Features:
- Self-improvement via reinforcement from real-world outcomes
- Dynamic knowledge base updates
- Pattern extraction from successful/failure cases
- Model fine-tuning triggers (local or cloud-based)
- GDPR-compliant data handling
"""

import asyncio
import logging
import json
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta

from core.learning.feedback_analyzer import FeedbackAnalyzer
from core.learning.knowledge_base import KnowledgeBase
from core.learning.pattern_extractor import PatternExtractor
from core.config.unified_config_manager import UnifiedConfigManager
from core.security.audit_logger import AuditLogger
from core.monitoring.intelligent_monitoring_system import IntelligentMonitoringSystem
from core.dependency.service_locator import ServiceLocator

# Инициализация логгера
logger = logging.getLogger(__name__)


class ContinuousLearningSystem:
    """
    Orchestrates the continuous learning loop of the autonomous freelancer.
    Runs periodically or on-demand after job completion.
    """

    def __init__(
        self,
        config_manager: UnifiedConfigManager,
        monitoring_system: Optional[IntelligentMonitoringSystem] = None,
        feedback_analyzer: Optional[FeedbackAnalyzer] = None,
        knowledge_base: Optional[KnowledgeBase] = None,
        pattern_extractor: Optional[PatternExtractor] = None,
        audit_logger: Optional[AuditLogger] = None,
    ):
        self.config = config_manager
        self.monitoring = monitoring_system or ServiceLocator.get("monitoring")
        self.feedback_analyzer = feedback_analyzer or FeedbackAnalyzer(config_manager)
        self.knowledge_base = knowledge_base or KnowledgeBase(config_manager)
        self.pattern_extractor = pattern_extractor or PatternExtractor(config_manager)
        self.audit_logger = audit_logger or ServiceLocator.get("audit_logger") or AuditLogger()

        self.enabled = self.config.get("learning.enabled", True)
        self.min_feedback_threshold = self.config.get("learning.min_feedback_for_update", 3)
        self.update_interval_hours = self.config.get("learning.update_interval_hours", 24)
        self.last_update = datetime.min

        self.data_dir = Path(self.config.get("data.root", "data")) / "learning"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.learning_log_path = self.data_dir / "learning_history.jsonl"

        logger.info("🧠 ContinuousLearningSystem initialized.")

    async def run_learning_cycle(self, force: bool = False) -> bool:
        """
        Executes a full learning cycle if conditions are met.
        Returns True if update was performed.
        """
        if not self.enabled:
            logger.debug("Learning system is disabled.")
            return False

        now = datetime.utcnow()
        if not force and (now - self.last_update) < timedelta(hours=self.update_interval_hours):
            logger.debug("Skipping learning cycle: too soon since last update.")
            return False

        try:
            logger.info("🔄 Starting continuous learning cycle...")
            await self._collect_learning_data()
            await self._analyze_and_extract_insights()
            await self._update_knowledge_and_models()
            await self._log_learning_outcome()

            self.last_update = now
            self.audit_logger.log("learning_cycle_completed", {"timestamp": now.isoformat()})
            logger.info("✅ Learning cycle completed successfully.")
            return True

        except Exception as e:
            error_msg = f"❌ Learning cycle failed: {e}"
            logger.error(error_msg, exc_info=True)
            self.audit_logger.log("learning_cycle_failed", {"error": str(e)})
            # Trigger recovery if needed
            emergency_recovery = ServiceLocator.get("emergency_recovery")
            if emergency_recovery:
                await emergency_recovery.handle_component_failure("continuous_learning", e)
            return False

    async def _collect_learning_data(self) -> Dict[str, Any]:
        """
        Gathers data from completed jobs, client feedback, and system metrics.
        """
        logger.debug("📥 Collecting learning data from storage and monitoring...")

        # Load recent job results (last 7 days)
        jobs_index_path = Path(self.config.get("data.root", "data")) / "jobs" / "jobs_index.json"
        feedback_data = []

        if jobs_index_path.exists():
            with open(jobs_index_path, "r", encoding="utf-8") as f:
                jobs_index = json.load(f)

            cutoff = datetime.utcnow() - timedelta(days=7)
            for job_id, meta in jobs_index.items():
                job_time = datetime.fromisoformat(meta["completed_at"]) if meta.get("completed_at") else None
                if job_time and job_time > cutoff:
                    job_dir = Path(self.config.get("data.root")) / "jobs" / job_id
                    feedback_path = job_dir / "feedback.json"
                    if feedback_path.exists():
                        with open(feedback_path, "r", encoding="utf-8") as ff:
                            feedback = json.load(ff)
                            feedback["job_id"] = job_id
                            feedback_data.append(feedback)

        # Get system performance anomalies
        anomalies = []
        if self.monitoring:
            anomalies = await self.monitoring.get_recent_anomalies(hours=168)  # 7 days

        self._collected_data = {
            "feedback": feedback_data,
            "anomalies": anomalies,
            "metrics": await self.monitoring.get_aggregated_metrics(hours=168) if self.monitoring else {},
        }
        return self._collected_data

    async def _analyze_and_extract_insights(self):
        """
        Uses internal analyzers to extract actionable insights.
        """
        logger.debug("🔍 Analyzing feedback and extracting patterns...")

        feedback = self._collected_data.get("feedback", [])
        if len(feedback) < self.min_feedback_threshold:
            logger.warning(f"Not enough feedback ({len(feedback)}) to trigger model update.")
            self._insights = {"patterns": [], "recommendations": []}
            return

        # Analyze sentiment & quality signals
        analysis = await self.feedback_analyzer.analyze_batch(feedback)
        patterns = await self.pattern_extractor.extract_patterns(analysis)

        self._insights = {
            "analysis": analysis,
            "patterns": patterns,
            "requires_model_update": len(patterns.get("critical_failures", [])) > 0
            or patterns.get("success_rate", 0) < 0.85,
        }

    async def _update_knowledge_and_models(self):
        """
        Updates knowledge base and triggers model retraining if needed.
        """
        logger.debug("📚 Updating knowledge base and models...")

        # Update structured knowledge
        await self.knowledge_base.ingest_insights(self._insights)

        # If critical patterns detected, notify AI manager to consider fine-tuning
        if self._insights.get("requires_model_update"):
            ai_manager = ServiceLocator.get("ai_manager")
            if ai_manager:
                await ai_manager.request_model_optimization(
                    reason="Low success rate or repeated failures detected",
                    context=self._insights
                )
            logger.info("⚠️ Model optimization requested due to learning insights.")

    async def _log_learning_outcome(self):
        """
        Appends learning outcome to persistent log for audit and analytics.
        """
        record = {
            "timestamp": datetime.utcnow().isoformat(),
            "feedback_count": len(self._collected_data.get("feedback", [])),
            "anomalies_count": len(self._collected_data.get("anomalies", [])),
            "patterns_found": len(self._insights.get("patterns", {}).get("all", [])),
            "model_update_requested": self._insights.get("requires_model_update", False),
        }

        with open(self.learning_log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

        # Also push to monitoring for dashboards
        if self.monitoring:
            await self.monitoring.record_metric("learning.cycles_completed", 1)
            await self.monitoring.record_metric("learning.feedback_processed", record["feedback_count"])

    async def on_job_completion(self, job_id: str):
        """
        Hook called by TaskOrchestrator when a job finishes.
        May trigger immediate lightweight learning (e.g., update client profile).
        """
        if not self.enabled:
            return

        # Lightweight: update client reputation or preferences
        client_service = ServiceLocator.get("client_service")
        if client_service:
            await client_service.update_client_from_job(job_id)

        # Schedule full cycle if enough jobs accumulated
        # (deferred to avoid blocking job delivery)
        asyncio.create_task(self.run_learning_cycle(force=False))


# Entry point for testing or manual invocation
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    config = UnifiedConfigManager()
    learner = ContinuousLearningSystem(config)
    asyncio.run(learner.run_learning_cycle(force=True))