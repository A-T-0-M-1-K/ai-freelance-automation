# AI_FREELANCE_AUTOMATION/plugins/ai_plugins/gemini_plugin.py
"""
Gemini AI Plugin — integrates Google's Gemini models into the AI Freelance Automation system.
Supports text generation, translation, summarization, and reasoning tasks.
Fully compatible with the plugin architecture and AI service registry.
"""

import logging
import os
from typing import Any, Dict, Optional, Union, List
from abc import ABC

from plugins.base_plugin import BaseAIPlugin
from core.config.unified_config_manager import UnifiedConfigManager
from core.security.advanced_crypto_system import AdvancedCryptoSystem
from core.dependency.service_locator import ServiceLocator

try:
    import google.generativeai as genai
except ImportError:
    raise ImportError(
        "Google Generative AI SDK not installed. "
        "Run: pip install google-generativeai"
    )

logger = logging.getLogger("GeminiPlugin")


class GeminiPlugin(BaseAIPlugin, ABC):
    """
    Plugin for Google Gemini models (e.g., gemini-1.5-pro, gemini-1.0-flash).
    Implements all required AI service interfaces: generate, translate, summarize, etc.
    """

    PLUGIN_NAME = "gemini"
    SUPPORTED_MODELS = {
        "gemini-1.5-pro": {"context_window": 2_000_000, "supports_vision": True},
        "gemini-1.5-flash": {"context_window": 1_000_000, "supports_vision": True},
        "gemini-1.0-pro": {"context_window": 32_768, "supports_vision": False},
    }

    def __init__(
        self,
        config_manager: Optional[UnifiedConfigManager] = None,
        crypto_system: Optional[AdvancedCryptoSystem] = None,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.config_manager = config_manager or ServiceLocator.get("config")
        self.crypto_system = crypto_system or ServiceLocator.get("crypto")

        # Load plugin-specific config
        self.plugin_config = self.config_manager.get("ai_plugins", {}).get("gemini", {})
        self.api_key = self._load_api_key()
        self.model_name = self.plugin_config.get("model", "gemini-1.5-flash")
        self.timeout = self.plugin_config.get("timeout", 120)
        self.max_retries = self.plugin_config.get("max_retries", 3)

        if self.model_name not in self.SUPPORTED_MODELS:
            raise ValueError(f"Unsupported Gemini model: {self.model_name}")

        self._initialize_client()
        self._is_ready = False
        self._health_check()

    def _load_api_key(self) -> str:
        """Securely load and decrypt API key."""
        encrypted_key = self.plugin_config.get("encrypted_api_key")
        if not encrypted_key:
            # Fallback to environment (for dev only)
            raw_key = os.getenv("GEMINI_API_KEY")
            if not raw_key:
                raise RuntimeError(
                    "Gemini API key not found in config or environment."
                )
            return raw_key

        decrypted = self.crypto_system.decrypt(encrypted_key)
        if not decrypted:
            raise RuntimeError("Failed to decrypt Gemini API key.")
        return decrypted

    def _initialize_client(self):
        """Initialize the Gemini client."""
        genai.configure(api_key=self.api_key)
        self.client = genai.GenerativeModel(self.model_name)
        logger.info(f"✅ Gemini client initialized for model: {self.model_name}")

    def _health_check(self) -> bool:
        """Perform a lightweight health check."""
        try:
            response = self.client.generate_content("Ping", generation_config={"max_output_tokens": 5})
            if response.text.strip().lower() in ("ping", "pong"):
                self._is_ready = True
                logger.info("🟢 Gemini plugin health check passed.")
                return True
        except Exception as e:
            logger.error(f"🔴 Gemini health check failed: {e}")
            self._is_ready = False
            return False

    def is_available(self) -> bool:
        """Check if plugin is ready for inference."""
        return self._is_ready

    async def generate(
        self,
        prompt: str,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        top_p: float = 0.9,
        **kwargs
    ) -> str:
        """Generate text using Gemini."""
        if not self.is_available():
            raise RuntimeError("Gemini plugin is not ready.")

        config = genai.types.GenerationConfig(
            max_output_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
        )

        for attempt in range(self.max_retries):
            try:
                response = await self.client.generate_content_async(
                    prompt, generation_config=config
                )
                if response.text:
                    return response.text.strip()
            except Exception as e:
                logger.warning(f"Gemini generation attempt {attempt + 1} failed: {e}")
                if attempt == self.max_retries - 1:
                    raise RuntimeError(f"Gemini generation failed after {self.max_retries} retries") from e
        raise RuntimeError("Unexpected state in Gemini generation")

    async def translate(
        self,
        text: str,
        source_lang: str = "auto",
        target_lang: str = "en",
        **kwargs
    ) -> str:
        """Translate text using contextual prompting."""
        prompt = (
            f"Translate the following text from {source_lang} to {target_lang}. "
            f"Return ONLY the translated text, no explanations:\n\n{text}"
        )
        return await self.generate(prompt, temperature=0.3, max_tokens=min(2048, len(text) * 2))

    async def summarize(
        self,
        text: str,
        max_length: int = 300,
        **kwargs
    ) -> str:
        """Summarize input text."""
        prompt = (
            f"Summarize the following text in no more than {max_length} words. "
            f"Be concise and preserve key facts:\n\n{text}"
        )
        return await self.generate(prompt, temperature=0.5, max_tokens=max_length * 2)

    async def analyze_sentiment(self, text: str) -> Dict[str, Any]:
        """Analyze sentiment (used by communication system)."""
        prompt = (
            "Analyze the sentiment of this message. Respond in JSON format with keys: "
            "'sentiment' (positive/neutral/negative), 'confidence' (0.0-1.0), 'explanation'.\n\n"
            f"Text: {text}"
        )
        raw = await self.generate(prompt, temperature=0.2, max_tokens=200)
        try:
            import json
            return json.loads(raw)
        except Exception:
            # Fallback structured parsing
            return {
                "sentiment": "neutral",
                "confidence": 0.5,
                "explanation": "Failed to parse structured response; defaulting to neutral."
            }

    async def transcribe_audio(self, audio_path: str, language: str = "en") -> str:
        """Gemini does not support native audio transcription. Delegate or raise."""
        raise NotImplementedError(
            "Gemini plugin does not support audio transcription. "
            "Use Whisper plugin instead."
        )

    def get_model_info(self) -> Dict[str, Any]:
        """Return metadata about the model."""
        return {
            "name": self.model_name,
            "provider": "Google",
            "plugin": self.PLUGIN_NAME,
            "capabilities": ["text_generation", "translation", "summarization", "reasoning"],
            "context_window": self.SUPPORTED_MODELS[self.model_name]["context_window"],
            "supports_vision": self.SUPPORTED_MODELS[self.model_name]["supports_vision"],
        }

    def shutdown(self):
        """Graceful shutdown (no-op for Gemini, but required by interface)."""
        logger.info("🔌 Gemini plugin shut down.")
        self._is_ready = False