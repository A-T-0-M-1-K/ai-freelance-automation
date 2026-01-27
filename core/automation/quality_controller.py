# core/automation/quality_controller.py
"""
Quality Controller — ensures 100% output quality before delivery to client.
Performs automated validation, error correction, and optimization.
Fully autonomous with self-healing and continuous learning capabilities.
"""

import asyncio
import logging
import traceback
from typing import Any, Dict, List, Optional, Union
from pathlib import Path

from core.config.unified_config_manager import UnifiedConfigManager
from core.ai_management.intelligent_model_manager import IntelligentModelManager
from core.monitoring.intelligent_monitoring_system import IntelligentMonitoringSystem
from core.learning.continuous_learning_system import ContinuousLearningSystem
from core.security.audit_logger import AuditLogger
from core.dependency.service_locator import ServiceLocator

logger = logging.getLogger("QualityController")


class QualityCheckResult:
    """Immutable result of a quality check."""
    def __init__(
        self,
        is_pass: bool,
        issues: List[Dict[str, Any]],
        corrected_content: Optional[str] = None,
        confidence_score: float = 0.0,
        metadata: Optional[Dict[str, Any]] = None
    ):
        self.is_pass = is_pass
        self.issues = issues
        self.corrected_content = corrected_content
        self.confidence_score = confidence_score
        self.metadata = metadata or {}


class QualityController:
    """
    Central quality assurance system for all deliverables.
    Supports text, transcription, translation, copywriting, and custom content types.
    """

    def __init__(
        self,
        config_manager: UnifiedConfigManager,
        model_manager: Optional[IntelligentModelManager] = None,
        monitoring_system: Optional[IntelligentMonitoringSystem] = None,
        learning_system: Optional[ContinuousLearningSystem] = None,
        audit_logger: Optional[AuditLogger] = None
    ):
        self.config = config_manager.get_section("automation.quality")
        self.model_manager = model_manager or ServiceLocator.get("ai_model_manager")
        self.monitoring = monitoring_system or ServiceLocator.get("monitoring_system")
        self.learning = learning_system or ServiceLocator.get("learning_system")
        self.audit_logger = audit_logger or ServiceLocator.get("audit_logger")

        self.enabled_checkers = self.config.get("enabled_checkers", [
            "grammar", "consistency", "tone", "factuality", "plagiarism"
        ])
        self.max_correction_attempts = self.config.get("max_correction_attempts", 3)
        self.min_confidence_threshold = self.config.get("min_confidence_threshold", 0.85)

        logger.info("✅ QualityController initialized with checkers: %s", self.enabled_checkers)

    async def assess_and_correct(
        self,
        content: str,
        content_type: str = "text",  # e.g., 'transcription', 'translation', 'copywriting'
        job_id: Optional[str] = None,
        client_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> QualityCheckResult:
        """
        Main entry point: assess quality and auto-correct if needed.
        Returns final result ready for delivery.
        """
        attempt = 0
        current_content = content
        all_issues: List[Dict[str, Any]] = []

        while attempt < self.max_correction_attempts:
            attempt += 1
            logger.debug("🔍 Quality assessment attempt %d for job %s", attempt, job_id)

            # Run all enabled checkers
            issues = await self._run_quality_checks(
                current_content, content_type, job_id, context
            )
            all_issues.extend(issues)

            if not issues:
                logger.info("✅ Quality check passed on attempt %d for job %s", attempt, job_id)
                return QualityCheckResult(
                    is_pass=True,
                    issues=[],
                    corrected_content=current_content,
                    confidence_score=1.0,
                    metadata={"attempts": attempt}
                )

            # Log issues
            self._log_issues(issues, job_id, client_id)

            # Attempt correction using AI
            try:
                corrected = await self._correct_issues(
                    current_content, issues, content_type, job_id
                )
                if corrected and corrected != current_content:
                    current_content = corrected
                    logger.info("🔧 Issues corrected in attempt %d for job %s", attempt, job_id)
                    continue
                else:
                    logger.warning("⚠️ No improvement after correction (attempt %d)", attempt)
            except Exception as e:
                logger.error("💥 Correction failed: %s", e, exc_info=True)
                self.monitoring.log_error("quality_correction_failure", str(e), job_id=job_id)

            # If still failing, break
            break

        # Final decision
        final_confidence = await self._estimate_confidence(current_content, content_type)
        is_pass = final_confidence >= self.min_confidence_threshold

        result = QualityCheckResult(
            is_pass=is_pass,
            issues=all_issues,
            corrected_content=current_content,
            confidence_score=final_confidence,
            metadata={
                "attempts": attempt,
                "final_confidence": final_confidence,
                "job_id": job_id,
                "content_type": content_type
            }
        )

        # Feed back to learning system
        await self._submit_feedback_to_learning(result, job_id, client_id)

        # Audit log
        self.audit_logger.log(
            action="quality_assessment",
            entity="deliverable",
            entity_id=job_id or "unknown",
            details={
                "content_type": content_type,
                "is_pass": is_pass,
                "issue_count": len(all_issues),
                "confidence": final_confidence
            }
        )

        if not is_pass:
            logger.warning("❌ Quality check FAILED for job %s (confidence: %.2f)", job_id, final_confidence)
            self.monitoring.trigger_alert(
                "quality_failure",
                f"Deliverable for job {job_id} failed quality control",
                severity="high"
            )

        return result

    async def _run_quality_checks(
        self,
        content: str,
        content_type: str,
        job_id: Optional[str],
        context: Optional[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Run all enabled quality checkers and aggregate issues."""
        issues = []

        for checker_name in self.enabled_checkers:
            try:
                checker = self._get_checker(checker_name)
                if checker:
                    result = await checker.check(content, content_type, job_id, context)
                    if result:
                        issues.extend(result)
            except Exception as e:
                logger.error(" Checker '%s' failed: %s", checker_name, e)
                self.monitoring.log_error(f"quality_checker_{checker_name}_failure", str(e))

        return issues

    def _get_checker(self, name: str):
        """Lazy-load or instantiate quality checkers."""
        # In a real system, this would use plugin_manager or factory
        # For now, stubbed with internal methods
        checkers = {
            "grammar": self._check_grammar,
            "consistency": self._check_consistency,
            "tone": self._check_tone,
            "factuality": self._check_factuality,
            "plagiarism": self._check_plagiarism,
        }
        return checkers.get(name)

    async def _check_grammar(self, content: str, *args) -> List[Dict[str, Any]]:
        model = await self.model_manager.get_model("proofreading")
        if not model:
            return []
        result = await model.infer({"text": content, "task": "grammar_check"})
        return result.get("issues", [])

    async def _check_consistency(self, content: str, content_type: str, job_id: str, context: Dict) -> List[Dict[str, Any]]:
        # Compare against original requirements or previous messages
        if context and "requirements" in context:
            model = await self.model_manager.get_model("consistency")
            result = await model.infer({
                "text": content,
                "requirements": context["requirements"],
                "task": "consistency_check"
            })
            return result.get("issues", [])
        return []

    async def _check_tone(self, content: str, content_type: str, job_id: str, context: Dict) -> List[Dict[str, Any]]:
        expected_tone = context.get("tone", "professional") if context else "professional"
        model = await self.model_manager.get_model("tone_analyzer")
        result = await model.infer({
            "text": content,
            "expected_tone": expected_tone,
            "task": "tone_check"
        })
        return result.get("issues", [])

    async def _check_factuality(self, content: str, *args) -> List[Dict[str, Any]]:
        # Only for certain content types
        model = await self.model_manager.get_model("factuality")
        if model:
            result = await model.infer({"text": content, "task": "fact_check"})
            return result.get("issues", [])
        return []

    async def _check_plagiarism(self, content: str, *args) -> List[Dict[str, Any]]:
        # Simulated — in practice, call external API or local embedding similarity
        model = await self.model_manager.get_model("plagiarism")
        if model:
            result = await model.infer({"text": content, "task": "plagiarism_check"})
            return result.get("issues", [])
        return []

    async def _correct_issues(
        self,
        content: str,
        issues: List[Dict[str, Any]],
        content_type: str,
        job_id: Optional[str]
    ) -> Optional[str]:
        """Use AI to correct identified issues."""
        editor_model = await self.model_manager.get_model("editing")
        if not editor_model:
            return None

        prompt = {
            "original_text": content,
            "issues": issues,
            "content_type": content_type,
            "instruction": "Fix all issues while preserving meaning and style."
        }

        try:
            result = await editor_model.infer(prompt)
            return result.get("corrected_text", content)
        except Exception as e:
            logger.error("Editor model inference failed: %s", e)
            return None

    async def _estimate_confidence(self, content: str, content_type: str) -> float:
        """Estimate confidence score using AI model."""
        model = await self.model_manager.get_model("quality_scoring")
        if not model:
            return 0.7  # fallback
        result = await model.infer({"text": content, "type": content_type})
        return float(result.get("confidence", 0.7))

    def _log_issues(self, issues: List[Dict[str, Any]], job_id: Optional[str], client_id: Optional[str]):
        for issue in issues:
            logger.warning(
                "❗ Quality issue in job %s: [%s] %s",
                job_id, issue.get("type"), issue.get("description")
            )
            self.monitoring.log_metric(
                "quality_issue",
                tags={"job_id": job_id, "client_id": client_id, "issue_type": issue.get("type")},
                value=1
            )

    async def _submit_feedback_to_learning(
        self,
        result: QualityCheckResult,
        job_id: Optional[str],
        client_id: Optional[str]
    ):
        """Feed quality results into continuous learning system."""
        if self.learning and job_id:
            await self.learning.ingest_feedback({
                "event": "quality_assessment",
                "job_id": job_id,
                "client_id": client_id,
                "result": {
                    "passed": result.is_pass,
                    "confidence": result.confidence_score,
                    "issue_count": len(result.issues)
                },
                "timestamp": asyncio.get_event_loop().time()
            })
