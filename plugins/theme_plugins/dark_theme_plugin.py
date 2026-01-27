# AI_FREELANCE_AUTOMATION/plugins/theme_plugins/dark_theme_plugin.py
"""
Dark Theme Plugin — provides a professional dark UI theme for the AI Freelance Automation system.

This plugin implements the standard theme interface and integrates seamlessly with
the ThemeManager in the UI subsystem. It supports hot-swapping, validation,
and safe fallback mechanisms.

Follows:
- Plugin architecture (base_plugin.py)
- Theme contract (ui/theme_manager.py)
- Security & logging standards
- Zero external side effects on import
"""

import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional

from plugins.base_plugin import BasePlugin
from core.config.unified_config_manager import UnifiedConfigManager
from core.security.audit_logger import AuditLogger

# Configure module-specific logger
logger = logging.getLogger(__name__)


class DarkThemePlugin(BasePlugin):
    """
    Professional dark theme optimized for long-term usage, reduced eye strain,
    and high contrast for data-rich dashboards.

    Implements all required methods from BasePlugin and provides a complete
    theme definition compliant with ui/theme_manager.py expectations.
    """

    PLUGIN_NAME = "dark_theme"
    PLUGIN_VERSION = "1.2.0"
    PLUGIN_AUTHOR = "AI Freelance Automation Core Team"
    PLUGIN_DESCRIPTION = "Professional dark theme with enhanced readability and accessibility."

    def __init__(self, config_manager: Optional[UnifiedConfigManager] = None):
        super().__init__()
        self.config_manager = config_manager or UnifiedConfigManager()
        self._theme_data: Optional[Dict[str, Any]] = None
        self._loaded = False
        self._audit_logger = AuditLogger()

    def load(self) -> bool:
        """
        Load theme definition from embedded JSON or file.
        Safe to call multiple times (idempotent).

        Returns:
            bool: True if loaded successfully, False otherwise.
        """
        if self._loaded:
            return True

        try:
            # Prefer embedded definition for reliability (no file I/O dependency)
            self._theme_data = self._get_embedded_theme()
            self._loaded = True
            logger.info("✅ Dark theme loaded successfully.")
            self._audit_logger.log("THEME_LOAD", {"theme": self.PLUGIN_NAME, "status": "success"})
            return True

        except Exception as e:
            logger.error(f"❌ Failed to load dark theme: {e}", exc_info=True)
            self._audit_logger.log("THEME_LOAD", {
                "theme": self.PLUGIN_NAME,
                "status": "error",
                "error": str(e)
            })
            return False

    def _get_embedded_theme(self) -> Dict[str, Any]:
        """
        Return the complete dark theme specification as a Python dict.
        This avoids file system dependencies and ensures portability.
        """
        return {
            "name": "dark_theme",
            "display_name": "Dark Mode",
            "version": self.PLUGIN_VERSION,
            "author": self.PLUGIN_AUTHOR,
            "type": "builtin",
            "colors": {
                "background": "#121212",
                "surface": "#1E1E1E",
                "primary": "#BB86FC",  # Purple 300 (Material Design)
                "secondary": "#03DAC6",  # Teal A700
                "accent": "#CF6679",  # Pink 400
                "error": "#CF6679",
                "warning": "#FFD740",
                "info": "#4CAF50",
                "text_primary": "#FFFFFF",
                "text_secondary": "#B0B0B0",
                "text_disabled": "#616161",
                "border": "#333333",
                "hover": "#2A2A2A",
                "selected": "#2D2D2D",
                "success": "#4CAF50",
                "on_primary": "#000000",
                "on_surface": "#FFFFFF"
            },
            "typography": {
                "font_family": "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
                "font_size_base": "14px",
                "line_height": "1.5",
                "heading_font_weight": "600",
                "monospace_font": "JetBrains Mono, Consolas, monospace"
            },
            "spacing": {
                "unit": "8px",
                "padding_small": "8px",
                "padding_medium": "16px",
                "padding_large": "24px",
                "margin_small": "8px",
                "margin_medium": "16px",
                "margin_large": "24px"
            },
            "shadows": {
                "card": "0 2px 8px rgba(0, 0, 0, 0.4)",
                "modal": "0 8px 32px rgba(0, 0, 0, 0.5)",
                "button": "0 1px 3px rgba(0, 0, 0, 0.3)"
            },
            "animations": {
                "enabled": True,
                "duration_short": "150ms",
                "duration_medium": "300ms",
                "easing": "cubic-bezier(0.4, 0, 0.2, 1)"
            },
            "accessibility": {
                "high_contrast_support": True,
                "reduced_motion_support": True,
                "screen_reader_optimized": True
            }
        }

    def get_theme_data(self) -> Optional[Dict[str, Any]]:
        """
        Return the loaded theme data.
        Must be called after `load()`.

        Returns:
            Dict or None if not loaded.
        """
        if not self._loaded:
            logger.warning("Attempted to get theme data before loading.")
            return None
        return self._theme_data.copy()  # Defensive copy

    def validate(self) -> bool:
        """
        Validate theme structure against expected schema.
        Ensures compatibility with UI renderer.
        """
        if not self._loaded or not self._theme_data:
            return False

        required_keys = {"name", "colors", "typography"}
        if not required_keys.issubset(self._theme_data.keys()):
            logger.error("Dark theme missing required keys.")
            return False

        # Validate critical color presence
        required_colors = {"background", "text_primary", "primary"}
        if not required_colors.issubset(self._theme_data["colors"].keys()):
            logger.error("Dark theme missing required color definitions.")
            return False

        return True

    def unload(self) -> None:
        """Clean up resources (noop for this theme)."""
        self._theme_data = None
        self._loaded = False
        logger.debug("Dark theme unloaded.")

    def get_metadata(self) -> Dict[str, Any]:
        """Return plugin metadata for registry."""
        return {
            "name": self.PLUGIN_NAME,
            "version": self.PLUGIN_VERSION,
            "author": self.PLUGIN_AUTHOR,
            "description": self.PLUGIN_DESCRIPTION,
            "type": "theme",
            "status": "active" if self._loaded else "inactive"
        }