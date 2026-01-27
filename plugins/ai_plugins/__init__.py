"""
AI Plugins Package Initialization
=================================

This package contains pluggable AI model integrations for the AI Freelance Automation system.
Each plugin implements a standardized interface to enable hot-swapping, dynamic loading,
and unified management of diverse AI providers (OpenAI, Anthropic, Google, local models, etc.).

Key Responsibilities:
- Define base interfaces for AI plugins
- Provide discovery and validation utilities
- Ensure compatibility with core/ai_management/model_registry.py
- Support lazy loading and isolated execution contexts

All AI plugins must inherit from `base_plugin.BasePlugin` and implement the `AIModelPluginInterface`.

DO NOT remove or modify this file unless you fully understand the plugin architecture.
"""

from typing import Dict, Type
from plugins.base_plugin import BasePlugin

# Registry of available AI plugins (populated dynamically by plugin_manager)
AI_PLUGIN_REGISTRY: Dict[str, Type[BasePlugin]] = {}

# Plugin metadata schema version (used for compatibility checks)
PLUGIN_SCHEMA_VERSION = "1.2.0"

# Supported AI capabilities that plugins can declare
SUPPORTED_CAPABILITIES = {
    "text_generation",
    "transcription",
    "translation",
    "summarization",
    "proofreading",
    "sentiment_analysis",
    "multilingual_support",
    "contextual_understanding",
    "emotional_tone_adaptation"
}


def register_ai_plugin(plugin_name: str, plugin_class: Type[BasePlugin]) -> None:
    """
    Register an AI plugin in the global registry.
    Called automatically during plugin discovery.

    Args:
        plugin_name (str): Unique identifier for the plugin (e.g., 'gpt4', 'whisper_medium')
        plugin_class (Type[BasePlugin]): The plugin class implementing AIModelPluginInterface

    Raises:
        ValueError: If plugin name is already registered or invalid
    """
    if not isinstance(plugin_name, str) or not plugin_name.strip():
        raise ValueError("Plugin name must be a non-empty string")

    if plugin_name in AI_PLUGIN_REGISTRY:
        raise ValueError(f"AI plugin '{plugin_name}' is already registered")

    # Validate that the plugin declares at least one supported capability
    if not hasattr(plugin_class, 'capabilities') or not isinstance(plugin_class.capabilities, set):
        raise ValueError(f"Plugin '{plugin_name}' must define a 'capabilities' set")

    if not plugin_class.capabilities & SUPPORTED_CAPABILITIES:
        raise ValueError(
            f"Plugin '{plugin_name}' does not declare any supported capabilities. "
            f"Supported: {SUPPORTED_CAPABILITIES}"
        )

    AI_PLUGIN_REGISTRY[plugin_name] = plugin_class


def get_registered_plugins() -> Dict[str, Type[BasePlugin]]:
    """Return a copy of the current AI plugin registry."""
    return AI_PLUGIN_REGISTRY.copy()


# Explicitly export public symbols
__all__ = [
    "AI_PLUGIN_REGISTRY",
    "PLUGIN_SCHEMA_VERSION",
    "SUPPORTED_CAPABILITIES",
    "register_ai_plugin",
    "get_registered_plugins"
]