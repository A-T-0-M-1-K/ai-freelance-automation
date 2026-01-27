# AI_FREELANCE_AUTOMATION/plugins/integration_plugins/__init__.py
"""
Integration Plugins Module
~~~~~~~~~~~~~~~~~~~~~~~~~~

This package contains pluggable integrations with external communication and notification services
(e.g., Email, Telegram, Discord, Slack). Each plugin must inherit from BasePlugin and implement
the required interface to ensure compatibility with the PluginManager.

All plugins are dynamically loaded at runtime and operate in isolated execution contexts.
"""

from typing import TYPE_CHECKING

# Prevent circular imports during type checking
if TYPE_CHECKING:
    from ...plugins.base_plugin import BasePlugin

# Public API — explicitly exported symbols
__all__ = [
    "BaseIntegrationPlugin",
]

# Define a common base class alias for clarity and consistency
# Actual implementation is in base_plugin.py to avoid duplication
from ..base_plugin import BasePlugin as BaseIntegrationPlugin

# Optional: register known integration plugins for static analysis or IDE support
# (dynamic loading is still handled by PluginManager)
try:
    from .email_plugin import EmailIntegrationPlugin
    from .telegram_plugin import TelegramIntegrationPlugin
    from .discord_plugin import DiscordIntegrationPlugin
    from .slack_plugin import SlackIntegrationPlugin
except ImportError:
    # Plugins may not be installed or enabled — this is expected
    pass

# Ensure module is namespace-safe and idempotent
def __getattr__(name):
    """Lazy attribute resolution for optional plugins (PEP 562)."""
    if name == "EmailIntegrationPlugin":
        from .email_plugin import EmailIntegrationPlugin
        return EmailIntegrationPlugin
    elif name == "TelegramIntegrationPlugin":
        from .telegram_plugin import TelegramIntegrationPlugin
        return TelegramIntegrationPlugin
    elif name == "DiscordIntegrationPlugin":
        from .discord_plugin import DiscordIntegrationPlugin
        return DiscordIntegrationPlugin
    elif name == "SlackIntegrationPlugin":
        from .slack_plugin import SlackIntegrationPlugin
        return SlackIntegrationPlugin
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")