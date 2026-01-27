# AI_FREELANCE_AUTOMATION/plugins/platform_plugins/__init__.py
"""
Platform Plugins Package Initialization

This package contains pluggable modules for integrating with freelance platforms
such as Upwork, Freelance.ru, Kwork, Fiverr, and custom platforms.

Each plugin must:
- Inherit from BasePlatformPlugin (defined in plugins.base_plugin)
- Implement required abstract methods
- Be isolated via sandboxing (handled by PluginManager)
- Support hot-swap without system restart

Plugins are dynamically loaded by PluginManager at runtime based on config/platforms.json.
"""

from typing import Dict, Type
from plugins.base_plugin import BasePlugin

# Registry of available platform plugins (populated dynamically by PluginManager)
# Format: {"platform_name": PluginClass}
PLATFORM_PLUGIN_REGISTRY: Dict[str, Type[BasePlugin]] = {}

# Explicit exports for static analysis and IDE support
__all__ = [
    "PLATFORM_PLUGIN_REGISTRY",
]

# Note: Individual plugin modules (e.g., upwork_plugin.py) register themselves
# into PLATFORM_PLUGIN_REGISTRY during their module initialization via metaclass
# or explicit registration call. This avoids circular imports and enables lazy loading.