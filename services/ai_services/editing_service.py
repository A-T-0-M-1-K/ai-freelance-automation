"""
AI-Powered Editing Service
==========================
Provides advanced text editing capabilities:
- Grammar & style correction
- Tone adjustment
- Readability optimization
- Plagiarism-aware rewriting
- Context-aware refinement

Integrates with core systems: AI models, monitoring, logging, config, and security.
Fully autonomous, self-monitoring, and recoverable.
"""

import asyncio
import logging
import time
from typing import Dict, Any, Optional, List, Union
from pathlib import Path

from core.config.unified_config_manager import UnifiedConfigManager
from core.security.advanced_crypto_system import AdvancedCryptoSystem
from core.monitoring.intelligent_monitoring_system import IntelligentMonitoringSystem
from core.ai_management.intelligent_model_manager import IntelligentModelManager
from core.dependency.service_locator import ServiceLocator
from core.learning.continuous_learning_system import ContinuousLearningSystem


class EditingService:
    """
    Autonomous AI service for professional-grade text editing.
    Supports multiple languages, tones, and client-specific styles.
    """

    def __init__(
        self,
        config_manager: Optional[UnifiedConfigManager] = None,
        crypto_system: Optional[AdvancedCryptoSystem] = None,
        monitor: Optional[IntelligentMonitoringSystem] = None,
        model_manager: Optional[IntelligentModelManager] = None,
        learning_system: Optional[ContinuousLearningSystem] = None,
    ):
        # Use ServiceLocator if dependencies not injected (supports lazy/DI)
        self.config = config_manager or ServiceLocator.get("config")
        self.crypto = crypto_system or ServiceLocator.get("crypto")
        self.monitor = monitor or ServiceLocator.get("monitor")
        self.model_manager = model_manager or ServiceLocator.get("ai_models")
        self.learning = learning_system or ServiceLocator.get("learning")

        self.logger = logging.getLogger("EditingService")
        self._initialized = False
        self._model_name = self.config.get("ai.editing.model", default="gpt-4o")
        self._max_retries = self.config.get("ai.editing.max_retries", default=3)

        # Metrics tracking
        self.metrics = {
            "total_edits": 0,
            "avg_processing_time_sec": 0.0,
            "error_count": 0,
            "success_rate": 1.0,
        }

    async def initialize(self) -> bool:
        """Initialize required AI models and validate configuration."""
        if self._initialized:
            return True

        try:
            self.logger.info("🔧 Initializing Editing Service...")
            await self.model_manager.load_model(self._model_name)
            self._initialized = True
            self.logger.info("✅ Editing Service ready.")
            return True
        except Exception as e:
            self.logger.error(f"❌ Failed to initialize Editing Service: {e}", exc_info=True)
            self.monitor.log_anomaly("editing_init_failure", {"error": str(e)})
            return False

    async def edit_text(
        self,
        text: str,
        job_id: str,
        client_id: str,
        style_guide: Optional[Dict[str, Any]] = None,
        tone: str = "professional",
        language: str = "en",
        max_length: Optional[int] = None,
        preserve_terms: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Perform intelligent editing of input text.

        Returns:
            {
                "edited_text": str,
                "changes_made": List[Dict],  # e.g., {"type": "grammar", "original": "...", "suggestion": "..."}
                "metrics": {...},
                "status": "success" | "partial" | "failed"
            }
        """
        start_time = time.time()
        attempt = 0

        if not self._initialized:
            await self.initialize()

        while attempt < self._max_retries:
            try:
                self.logger.info(f"🖋️ Editing job {job_id} for client {client_id} (attempt {attempt + 1})")

                # Prepare prompt with context
                prompt = self._build_editing_prompt(
                    text=text,
                    tone=tone,
                    language=language,
                    style_guide=style_guide or {},
                    max_length=max_length,
                    preserve_terms=preserve_terms or [],
                )

                # Run inference
                response = await self.model_manager.infer(
                    model_name=self._model_name,
                    prompt=prompt,
                    temperature=0.3,
                    max_tokens=4096,
                    response_format={"type": "json_object"},
                )

                # Parse and validate
                result = self._parse_model_response(response)
                if not result.get("edited_text"):
                    raise ValueError("Model returned empty or invalid response")

                # Log success
                processing_time = time.time() - start_time
                self._update_metrics(success=True, duration=processing_time)

                # Feed into continuous learning
                await self.learning.analyze_task_outcome(
                    task_type="editing",
                    input_data={"text": text, "params": locals()},
                    output_data=result,
                    client_id=client_id,
                    job_id=job_id,
                    success=True,
                )

                self.logger.info(f"✅ Successfully edited job {job_id} in {processing_time:.2f}s")
                return {
                    "edited_text": result["edited_text"],
                    "changes_made": result.get("changes_made", []),
                    "metrics": {
                        "processing_time_sec": processing_time,
                        "model_used": self._model_name,
                        "tokens_used": len(response.split()) if isinstance(response, str) else 0,
                    },
                    "status": "success",
                }

            except Exception as e:
                attempt += 1
                self.logger.warning(f"⚠️ Editing attempt {attempt} failed: {e}")
                self._update_metrics(success=False)

                if attempt >= self._max_retries:
                    error_msg = f"Editing failed after {self._max_retries} attempts: {e}"
                    self.logger.error(error_msg)
                    self.monitor.log_anomaly("editing_failure", {"job_id": job_id, "error": str(e)})

                    # Still attempt learning (even on failure)
                    await self.learning.analyze_task_outcome(
                        task_type="editing",
                        input_data={"text": text, "params": locals()},
                        output_data={"error": str(e)},
                        client_id=client_id,
                        job_id=job_id,
                        success=False,
                    )

                    return {
                        "edited_text": text,  # fallback
                        "changes_made": [],
                        "metrics": {"error": str(e), "retries": attempt},
                        "status": "failed",
                    }

                await asyncio.sleep(2 ** attempt)  # exponential backoff

    def _build_editing_prompt(self, **kwargs) -> str:
        """Construct a structured prompt for the LLM."""
        text = kwargs["text"]
        tone = kwargs["tone"]
        lang = kwargs["language"]
        style = kwargs["style_guide"]
        max_len = kwargs["max_length"]
        preserve = kwargs["preserve_terms"]

        instructions = [
            "You are an expert editor. Improve the following text while preserving its core meaning.",
            f"Target tone: {tone}",
            f"Language: {lang}",
            "Output ONLY valid JSON with keys: 'edited_text' (string), 'changes_made' (list of objects).",
            "Each change must have: 'type' (e.g., 'grammar', 'clarity', 'tone'), 'original', 'suggestion'.",
        ]

        if max_len:
            instructions.append(f"Ensure final text is no longer than {max_len} characters.")
        if preserve:
            instructions.append(f"NEVER modify these terms: {', '.join(preserve)}")
        if style:
            instructions.append(f"Follow this style guide: {style}")

        instructions.append("\nText to edit:\n" + text)
        return "\n".join(instructions)

    def _parse_model_response(self, raw_response: Union[str, Dict]) -> Dict[str, Any]:
        """Safely parse and validate model output."""
        import json

        if isinstance(raw_response, dict):
            data = raw_response
        else:
            try:
                data = json.loads(raw_response)
            except json.JSONDecodeError:
                # Fallback: treat as plain text
                return {"edited_text": raw_response.strip(), "changes_made": []}

        edited = data.get("edited_text", "").strip()
        changes = data.get("changes_made", [])

        if not isinstance(changes, list):
            changes = []

        return {"edited_text": edited, "changes_made": changes}

    def _update_metrics(self, success: bool, duration: float = 0.0):
        """Update internal performance metrics."""
        self.metrics["total_edits"] += 1
        if success:
            n = self.metrics["total_edits"]
            avg = self.metrics["avg_processing_time_sec"]
            self.metrics["avg_processing_time_sec"] = (avg * (n - 1) + duration) / n
        else:
            self.metrics["error_count"] += 1

        total = self.metrics["total_edits"]
        errors = self.metrics["error_count"]
        self.metrics["success_rate"] = max(0.0, (total - errors) / max(1, total))

        # Push to monitoring system
        self.monitor.record_metric("editing.success_rate", self.metrics["success_rate"])
        self.monitor.record_metric("editing.avg_time_sec", self.metrics["avg_processing_time_sec"])

    async def get_capabilities(self) -> Dict[str, Any]:
        """Return service metadata for orchestration."""
        return {
            "service": "editing",
            "version": "1.0",
            "supported_languages": ["en", "ru", "es", "fr", "de", "zh", "ar"],
            "tones": ["professional", "casual", "academic", "marketing", "technical"],
            "max_input_chars": 50000,
            "model": self._model_name,
            "metrics": self.metrics.copy(),
        }


# Singleton-like access (optional, for legacy compatibility)
_editing_service_instance: Optional[EditingService] = None


async def get_editing_service() -> EditingService:
    """Global async accessor (use only if DI not available)."""
    global _editing_service_instance
    if _editing_service_instance is None:
        _editing_service_instance = EditingService()
        await _editing_service_instance.initialize()
    return _editing_service_instance