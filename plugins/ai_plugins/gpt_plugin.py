# AI_FREELANCE_AUTOMATION/plugins/ai_plugins/gpt_plugin.py
"""
GPT Plugin — AI plugin for OpenAI GPT models (GPT-3.5, GPT-4, GPT-4o, etc.)
Integrates with the core AI management system and supports:
- Text generation
- Copywriting
- Editing
- Translation refinement
- Client communication drafting

Fully compliant with plugin architecture:
- Hot-swappable
- Isolated execution
- Configurable via unified config
- Secure (API keys never logged)
- Self-monitoring & error recovery
"""

import asyncio
import logging
import os
from typing import Any, Dict, Optional, Union, List
from abc import ABC

import openai
from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from plugins.base_plugin import BaseAIPlugin
from core.config.unified_config_manager import UnifiedConfigManager
from core.security.advanced_crypto_system import AdvancedCryptoSystem
from core.monitoring.intelligent_monitoring_system import MetricsCollector

logger = logging.getLogger(__name__)


class GPTPlugin(BaseAIPlugin, ABC):
    """
    GPT-based AI plugin implementing the standard AI plugin interface.
    Supports multiple GPT models and is optimized for freelance tasks.
    """

    PLUGIN_NAME = "gpt"
    SUPPORTED_TASKS = {
        "copywriting",
        "editing",
        "proofreading",
        "translation_refinement",
        "client_communication",
        "bid_generation",
        "report_writing"
    }

    def __init__(
            self,
            config_manager: UnifiedConfigManager,
            crypto_system: Optional[AdvancedCryptoSystem] = None,
            metrics_collector: Optional[MetricsCollector] = None
    ):
        super().__init__()
        self.config_manager = config_manager
        self.crypto_system = crypto_system
        self.metrics = metrics_collector or MetricsCollector()

        # Load plugin-specific config
        self.plugin_config = self.config_manager.get("ai_plugins.gpt", default={})
        self._validate_config()

        # Initialize OpenAI client
        self.client: Optional[AsyncOpenAI] = None
        self._initialized = False

    def _validate_config(self) -> None:
        """Validate required configuration fields."""
        required_keys = ["api_key_encrypted", "default_model", "timeout_seconds"]
        for key in required_keys:
            if key not in self.plugin_config:
                raise ValueError(f"Missing required config key in 'ai_plugins.gpt': {key}")

    async def initialize(self) -> bool:
        """
        Initialize the GPT plugin: decrypt API key, set up client, test connectivity.
        Returns True if successful.
        """
        if self._initialized:
            return True

        try:
            # Decrypt API key securely
            encrypted_key = self.plugin_config["api_key_encrypted"]
            if self.crypto_system is None:
                raise RuntimeError("Crypto system required to decrypt API key")

            api_key = self.crypto_system.decrypt(encrypted_key)
            if not api_key or not isinstance(api_key, str):
                raise ValueError("Decrypted API key is invalid")

            # Initialize async OpenAI client
            self.client = AsyncOpenAI(
                api_key=api_key,
                timeout=self.plugin_config.get("timeout_seconds", 30),
                max_retries=2
            )

            # Test minimal connectivity
            await self.client.models.retrieve(self.plugin_config["default_model"])
            self._initialized = True
            logger.info(f"✅ GPT plugin initialized with model: {self.plugin_config['default_model']}")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to initialize GPT plugin: {e}", exc_info=True)
            self.metrics.increment_counter("ai_plugin_init_failures", {"plugin": "gpt"})
            return False

    async def shutdown(self) -> None:
        """Gracefully shut down the plugin."""
        self._initialized = False
        if self.client:
            await self.client.close()
        logger.info("🔌 GPT plugin shut down.")

    def supports_task(self, task_type: str) -> bool:
        """Check if this plugin can handle the given task type."""
        return task_type in self.SUPPORTED_TASKS

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((openai.RateLimitError, openai.APIConnectionError))
    )
    async def generate(
            self,
            prompt: str,
            task_type: str,
            context: Optional[Dict[str, Any]] = None,
            **kwargs
    ) -> Dict[str, Any]:
        """
        Generate AI response using GPT.

        Args:
            prompt (str): The input prompt.
            task_type (str): Type of task (must be in SUPPORTED_TASKS).
            context (dict, optional): Additional context (client tone, language, etc.).
            **kwargs: Extra parameters (max_tokens, temperature, etc.)

        Returns:
            dict: Result with keys: 'text', 'model_used', 'tokens_used', 'success'
        """
        if not self._initialized or self.client is None:
            raise RuntimeError("GPT plugin not initialized. Call initialize() first.")

        if not self.supports_task(task_type):
            raise ValueError(f"Unsupported task type: {task_type}")

        # Build messages
        system_prompt = self._get_system_prompt(task_type, context)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ]

        # Merge defaults with overrides
        params = {
            "model": self.plugin_config.get("default_model", "gpt-4o"),
            "max_tokens": kwargs.get("max_tokens", 1000),
            "temperature": kwargs.get("temperature", 0.7),
            "top_p": kwargs.get("top_p", 1.0),
            "frequency_penalty": kwargs.get("frequency_penalty", 0.0),
            "presence_penalty": kwargs.get("presence_penalty", 0.0),
        }

        try:
            logger.debug(f"🧠 GPT generating for task '{task_type}' with model {params['model']}")

            response = await self.client.chat.completions.create(
                messages=messages,
                **params
            )

            result_text = response.choices[0].message.content or ""
            tokens_used = response.usage.total_tokens if response.usage else 0

            # Log usage metric
            self.metrics.record_histogram(
                "ai_tokens_used",
                tokens_used,
                tags={"model": params["model"], "task": task_type}
            )

            return {
                "text": result_text,
                "model_used": params["model"],
                "tokens_used": tokens_used,
                "success": True
            }

        except openai.AuthenticationError:
            logger.critical("🔑 GPT API authentication failed. Check encrypted API key.")
            self.metrics.increment_counter("ai_auth_failures", {"plugin": "gpt"})
            raise
        except openai.RateLimitError:
            logger.warning("⚠️ GPT rate limit hit. Retrying...")
            self.metrics.increment_counter("ai_rate_limit_hits", {"plugin": "gpt"})
            raise
        except Exception as e:
            logger.error(f"💥 GPT generation error: {e}", exc_info=True)
            self.metrics.increment_counter("ai_generation_errors", {"plugin": "gpt", "task": task_type})
            return {
                "text": "",
                "model_used": params["model"],
                "tokens_used": 0,
                "success": False,
                "error": str(e)
            }

    def _get_system_prompt(self, task_type: str, context: Optional[Dict[str, Any]] = None) -> str:
        """Generate appropriate system prompt based on task and context."""
        base_prompts = {
            "copywriting": (
                "You are a professional copywriter. Write engaging, original, and persuasive content "
                "tailored to the client's industry and audience. Avoid fluff."
            ),
            "editing": (
                "You are an expert editor. Improve clarity, flow, and professionalism while preserving the author's voice."
            ),
            "proofreading": (
                "Correct grammar, spelling, punctuation, and syntax errors. Do not rewrite unless necessary."
            ),
            "translation_refinement": (
                "Refine the provided translation to sound natural, fluent, and culturally appropriate in the target language."
            ),
            "client_communication": (
                "Write polite, clear, and professional messages to clients. Show empathy and reliability."
            ),
            "bid_generation": (
                "Write a compelling, unique, and concise proposal for a freelance job. Highlight relevant skills and confidence."
            ),
            "report_writing": (
                "Generate structured, factual, and insightful reports. Use bullet points where appropriate."
            )
        }

        prompt = base_prompts.get(task_type, "You are a helpful AI assistant.")

        if context:
            if lang := context.get("language"):
                prompt += f" Respond in {lang}."
            if tone := context.get("tone"):
                prompt += f" Use a {tone} tone."
            if style := context.get("style"):
                prompt += f" Follow {style} style guidelines."

        return prompt

    async def health_check(self) -> Dict[str, Any]:
        """Return plugin health status."""
        return {
            "name": self.PLUGIN_NAME,
            "initialized": self._initialized,
            "supports_tasks": list(self.SUPPORTED_TASKS),
            "model": self.plugin_config.get("default_model", "unknown")
        }