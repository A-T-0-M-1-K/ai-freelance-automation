# AI_FREELANCE_AUTOMATION/plugins/ai_plugins/claude_plugin.py
"""
Claude AI Plugin — integrates Anthropic's Claude models into the AI Freelance Automation system.
Supports text generation, editing, translation, and reasoning tasks with emotional intelligence.
Fully compatible with the plugin manager and model registry.
"""

import asyncio
import logging
from typing import Dict, Any, Optional, List, Union
from pathlib import Path

from core.dependency.service_locator import ServiceLocator
from core.config.unified_config_manager import UnifiedConfigManager
from core.security.advanced_crypto_system import AdvancedCryptoSystem
from core.ai_management.model_registry import ModelRegistry
from plugins.base_plugin import BaseAIPlugin

# Optional: only import if anthropic is available
try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False


class ClaudePlugin(BaseAIPlugin):
    """
    Plugin for Anthropic Claude models (Claude 3 Sonnet, Haiku, Opus).
    Implements all required AI service interfaces: generate, edit, translate, analyze.
    """

    PLUGIN_NAME = "claude"
    SUPPORTED_MODELS = ["claude-3-opus-20240229", "claude-3-sonnet-20240229", "claude-3-haiku-20240307"]
    PLUGIN_VERSION = "1.2.0"

    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(f"plugins.ai.{self.PLUGIN_NAME}")
        self._client: Optional[anthropic.AsyncAnthropic] = None
        self._config: Optional[Dict[str, Any]] = None
        self._crypto: Optional[AdvancedCryptoSystem] = None
        self._initialized = False

    async def initialize(self) -> bool:
        """Initialize the Claude plugin using dependency injection."""
        if not ANTHROPIC_AVAILABLE:
            self.logger.error("❌ 'anthropic' package not installed. Install with: pip install anthropic")
            return False

        try:
            # Resolve dependencies
            config_manager: UnifiedConfigManager = ServiceLocator.get("config_manager")
            self._crypto = ServiceLocator.get("crypto_system")

            # Load plugin-specific config
            self._config = config_manager.get_ai_plugin_config(self.PLUGIN_NAME)
            if not self._config:
                self.logger.warning("⚠️ No config found for 'claude' plugin. Using defaults.")
                self._config = self._get_default_config()

            # Decrypt API key securely
            encrypted_key = self._config.get("api_key_encrypted")
            if not encrypted_key:
                self.logger.error("❌ Missing encrypted API key in claude plugin config.")
                return False

            api_key = self._crypto.decrypt_secret(encrypted_key)
            if not api_key:
                self.logger.error("❌ Failed to decrypt Claude API key.")
                return False

            # Initialize async client
            self._client = anthropic.AsyncAnthropic(api_key=api_key)
            self._initialized = True

            # Register supported models in global registry
            registry: ModelRegistry = ServiceLocator.get("model_registry")
            for model_name in self.SUPPORTED_MODELS:
                registry.register_model(
                    model_id=f"{self.PLUGIN_NAME}/{model_name}",
                    provider=self.PLUGIN_NAME,
                    capabilities=["text-generation", "reasoning", "editing", "translation"],
                    metadata={"version": self.PLUGIN_VERSION, "model": model_name}
                )

            self.logger.info(f"✅ Claude plugin initialized. Registered models: {self.SUPPORTED_MODELS}")
            return True

        except Exception as e:
            self.logger.critical(f"💥 Failed to initialize Claude plugin: {e}", exc_info=True)
            return False

    def _get_default_config(self) -> Dict[str, Any]:
        return {
            "enabled": True,
            "default_model": "claude-3-sonnet-20240229",
            "max_tokens": 4096,
            "temperature": 0.7,
            "timeout_sec": 120,
            "retry_attempts": 3,
            "api_key_encrypted": ""  # Must be set by user via secure config
        }

    async def generate(
        self,
        prompt: str,
        context: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Generate text using Claude."""
        if not self._initialized or not self._client:
            raise RuntimeError("Claude plugin not initialized")

        model = kwargs.get("model", self._config["default_model"])
        if model not in self.SUPPORTED_MODELS:
            raise ValueError(f"Unsupported model: {model}")

        try:
            max_tokens = kwargs.get("max_tokens", self._config["max_tokens"])
            temperature = kwargs.get("temperature", self._config["temperature"])

            response = await self._client.messages.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[{"role": "user", "content": prompt}],
                timeout=kwargs.get("timeout", self._config["timeout_sec"]),
            )

            return {
                "success": True,
                "text": response.content[0].text if response.content else "",
                "model_used": model,
                "usage": {
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                },
                "metadata": {"plugin": self.PLUGIN_NAME, "version": self.PLUGIN_VERSION}
            }

        except anthropic.APIStatusError as e:
            self.logger.error(f"❌ Claude API error ({e.status_code}): {e.message}")
            return {"success": False, "error": f"API Error: {e.message}", "status_code": e.status_code}
        except Exception as e:
            self.logger.error(f"💥 Unexpected error during Claude generation: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    async def edit(self, text: str, instruction: str, **kwargs) -> Dict[str, Any]:
        """Edit text based on instruction."""
        prompt = f"INSTRUCTION: {instruction}\n\nTEXT:\n{text}"
        return await self.generate(prompt, **kwargs)

    async def translate(self, text: str, target_lang: str, source_lang: str = "auto", **kwargs) -> Dict[str, Any]:
        """Translate text using Claude's multilingual capability."""
        prompt = (
            f"Translate the following text from {source_lang} to {target_lang}. "
            f"Preserve tone, style, and formatting. Only output the translation.\n\n{text}"
        )
        return await self.generate(prompt, **kwargs)

    async def analyze_sentiment(self, text: str, **kwargs) -> Dict[str, Any]:
        """Analyze sentiment (emulated via prompt engineering)."""
        prompt = (
            "Analyze the sentiment of the following text. Respond ONLY with a JSON object like: "
            '{"sentiment": "positive|neutral|negative", "confidence": 0.0-1.0, "explanation": "..."}\n\n'
            f"Text: {text}"
        )
        result = await self.generate(prompt, **kwargs)
        if result["success"]:
            # TODO: parse JSON safely in production
            result["structured"] = result["text"]
        return result

    async def shutdown(self) -> None:
        """Gracefully shut down the plugin."""
        if self._client:
            await self._client.close()
        self._initialized = False
        self.logger.info("🔌 Claude plugin shut down.")

    def is_available(self) -> bool:
        return self._initialized and ANTHROPIC_AVAILABLE

    def get_capabilities(self) -> List[str]:
        return ["text-generation", "editing", "translation", "sentiment-analysis", "reasoning"]


# Register plugin automatically if loaded
if ANTHROPIC_AVAILABLE:
    from plugins.plugin_manager import PluginManager
    PluginManager.register_plugin("ai", "claude", ClaudePlugin)