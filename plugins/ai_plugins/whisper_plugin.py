# plugins/ai_plugins/whisper_plugin.py
"""
Whisper AI Plugin — integrates OpenAI Whisper (or compatible forks) for high-accuracy transcription.
Implements the standard AI plugin interface for seamless integration with the AI service layer.
Supports dynamic model loading, GPU/CPU fallback, and real-time performance monitoring.
"""

import logging
import os
import time
from pathlib import Path
from typing import Optional, Dict, Any, Union

import torch
from transformers import pipeline
from transformers.utils import is_offline_mode

from plugins.base_plugin import BaseAIPlugin
from core.config.config import UnifiedConfigManager
from core.monitoring.metrics_collector import MetricsCollector
from core.security.audit_logger import AuditLogger
from core.performance.intelligent_cache_system import IntelligentCacheSystem

logger = logging.getLogger("WhisperPlugin")


class WhisperPlugin(BaseAIPlugin):
    """
    Whisper-based transcription plugin compliant with the AI plugin architecture.
    Supports multiple model sizes (tiny, base, small, medium, large) and languages.
    """

    PLUGIN_NAME = "whisper"
    SUPPORTED_TASKS = ["transcription", "audio_to_text"]
    REQUIRED_CONFIG_KEYS = ["model_name", "device", "chunk_length_s", "language"]

    def __init__(self, config_manager: UnifiedConfigManager):
        super().__init__()
        self.config_manager = config_manager
        self._config = self._load_config()
        self._model = None
        self._pipeline = None
        self._is_loaded = False
        self._metrics = MetricsCollector()
        self._audit = AuditLogger()
        self._cache = IntelligentCacheSystem()

        self._validate_config()
        logger.info(f"Intialized {self.PLUGIN_NAME} plugin with config: {self._config}")

    def _load_config(self) -> Dict[str, Any]:
        """Load plugin-specific configuration from ai_config.json or platform defaults."""
        ai_config = self.config_manager.get("ai_config", {})
        whisper_config = ai_config.get("whisper", {})

        # Fallback to legacy if needed (for backward compatibility)
        if not whisper_config:
            whisper_config = self.config_manager.get("whisper_config", {})

        # Default values
        defaults = {
            "model_name": "openai/whisper-medium",
            "device": "cuda" if torch.cuda.is_available() else "cpu",
            "chunk_length_s": 30,
            "language": None,  # Auto-detect if None
            "use_cache": True,
            "max_workers": 1,
            "torch_dtype": "float16" if torch.cuda.is_available() else "float32",
        }

        # Merge defaults with user config
        for key, value in defaults.items():
            whisper_config.setdefault(key, value)

        return whisper_config

    def _validate_config(self):
        """Validate required keys and types."""
        for key in self.REQUIRED_CONFIG_KEYS:
            if key not in self._config:
                raise ValueError(f"Missing required config key in whisper plugin: '{key}'")
        if self._config["device"] not in ("cpu", "cuda", "mps"):
            logger.warning(f"Unsupported device '{self._config['device']}', falling back to CPU")
            self._config["device"] = "cpu"

    def load_model(self) -> bool:
        """Load Whisper model into memory. Idempotent and safe to call multiple times."""
        if self._is_loaded:
            return True

        try:
            self._audit.log("MODEL_LOAD_START", {"plugin": self.PLUGIN_NAME, "model": self._config["model_name"]})

            model_kwargs = {}
            if self._config["device"] == "cuda":
                model_kwargs["torch_dtype"] = getattr(torch, self._config["torch_dtype"])
                model_kwargs["use_flash_attention_2"] = False  # Optional optimization

            start_time = time.time()

            # Use offline mode if no internet
            local_files_only = is_offline_mode()

            self._pipeline = pipeline(
                "automatic-speech-recognition",
                model=self._config["model_name"],
                device=self._config["device"],
                chunk_length_s=self._config["chunk_length_s"],
                torch_dtype=model_kwargs.get("torch_dtype"),
                local_files_only=local_files_only,
            )

            load_time = time.time() - start_time
            self._metrics.record("model_load_time", load_time, tags={"model": "whisper"})
            self._is_loaded = True

            self._audit.log("MODEL_LOAD_SUCCESS", {
                "plugin": self.PLUGIN_NAME,
                "model": self._config["model_name"],
                "device": self._config["device"],
                "load_time_sec": round(load_time, 2)
            })
            logger.info(f"✅ Whisper model loaded on {self._config['device']} in {load_time:.2f}s")
            return True

        except Exception as e:
            self._audit.log("MODEL_LOAD_FAILURE", {
                "plugin": self.PLUGIN_NAME,
                "error": str(e),
                "model": self._config["model_name"]
            })
            logger.error(f"❌ Failed to load Whisper model: {e}", exc_info=True)
            return False

    def transcribe(
        self,
        audio_path: Union[str, Path],
        language: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Transcribe audio file to text.

        Args:
            audio_path (str | Path): Path to audio file (WAV, MP3, etc.)
            language (str, optional): Force language (e.g., 'en', 'ru'). If None — auto-detect.
            **kwargs: Additional args passed to pipeline (e.g., `return_timestamps`)

        Returns:
            dict: {
                "text": str,
                "segments": list[dict],  # if return_timestamps=True
                "language": str,
                "duration_sec": float,
                "processing_time_sec": float
            }
        """
        if not self._is_loaded:
            if not self.load_model():
                raise RuntimeError("Whisper model failed to load. Cannot transcribe.")

        audio_path = Path(audio_path)
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        cache_key = f"whisper_{audio_path.stem}_{language or 'auto'}"
        if self._config.get("use_cache", True):
            cached = self._cache.get(cache_key)
            if cached:
                logger.debug(f"📥 Cache hit for {audio_path}")
                return cached

        try:
            self._audit.log("TRANSCRIPTION_START", {
                "plugin": self.PLUGIN_NAME,
                "audio_file": str(audio_path.name),
                "language": language
            })

            start_time = time.time()
            params = {
                "return_timestamps": kwargs.get("return_timestamps", False),
                "generate_kwargs": {}
            }

            if language:
                params["generate_kwargs"]["language"] = language
            elif self._config["language"]:
                params["generate_kwargs"]["language"] = self._config["language"]

            result = self._pipeline(str(audio_path), **params)
            processing_time = time.time() - start_time

            output = {
                "text": result["text"].strip(),
                "language": language or self._config["language"] or "auto",
                "duration_sec": processing_time,
                "processing_time_sec": round(processing_time, 2),
            }

            if "chunks" in result:
                output["segments"] = result["chunks"]

            # Cache result
            if self._config.get("use_cache", True):
                self._cache.set(cache_key, output, ttl=86400)  # 24h

            self._metrics.record("transcription_duration", processing_time)
            self._metrics.increment("transcriptions_total", tags={"success": "true"})

            self._audit.log("TRANSCRIPTION_SUCCESS", {
                "plugin": self.PLUGIN_NAME,
                "audio_file": str(audio_path.name),
                "chars": len(output["text"]),
                "time_sec": round(processing_time, 2)
            })

            return output

        except Exception as e:
            self._metrics.increment("transcriptions_total", tags={"success": "false"})
            self._audit.log("TRANSCRIPTION_ERROR", {
                "plugin": self.PLUGIN_NAME,
                "audio_file": str(audio_path.name),
                "error": str(e)
            })
            logger.error(f"Transcription failed for {audio_path}: {e}", exc_info=True)
            raise

    def unload_model(self):
        """Unload model from memory to free resources."""
        if self._model or self._pipeline:
            del self._pipeline
            del self._model
            self._pipeline = None
            self._model = None
            self._is_loaded = False
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            logger.info("🧹 Whisper model unloaded and memory freed.")

    def get_capabilities(self) -> Dict[str, Any]:
        """Return plugin metadata for service discovery."""
        return {
            "name": self.PLUGIN_NAME,
            "version": "1.0.0",
            "supported_tasks": self.SUPPORTED_TASKS,
            "model": self._config["model_name"],
            "device": self._config["device"],
            "languages": ["auto", "en", "ru", "es", "fr", "de", "zh", "ja", "ko", "ar"],  # Extend as needed
            "max_audio_duration_sec": 7200,  # 2 hours
            "real_time": False,
        }

    def health_check(self) -> Dict[str, Any]:
        """Return health status for monitoring system."""
        return {
            "status": "healthy" if self._is_loaded else "unloaded",
            "model_loaded": self._is_loaded,
            "device": self._config["device"],
            "last_error": None  # Could be extended with error history
        }