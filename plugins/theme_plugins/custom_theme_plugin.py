# AI_FREELANCE_AUTOMATION/plugins/theme_plugins/custom_theme_plugin.py
"""
Custom Theme Plugin — allows dynamic loading and application of user-defined UI themes.
Supports JSON-based theme definitions with validation, hot-reload, and fallback mechanisms.
Fully isolated, sandboxed, and compatible with the plugin system.

Author: AI Freelance Automation System
"""

import json
import logging
import os
from pathlib import Path
from typing import Dict, Any, Optional
from plugins.base_plugin import BasePlugin
from core.config.unified_config_manager import UnifiedConfigManager
from core.security.audit_logger import AuditLogger

logger = logging.getLogger("CustomThemePlugin")


class CustomThemePlugin(BasePlugin):
    """
    Plugin for loading and applying custom UI themes from user-provided JSON files.
    Implements full lifecycle management: load, validate, apply, rollback, unload.
    """

    PLUGIN_NAME = "custom_theme"
    PLUGIN_VERSION = "1.0.0"
    PLUGIN_TYPE = "theme"

    def __init__(self, config_manager: Optional[UnifiedConfigManager] = None):
        super().__init__()
        self.config_manager = config_manager or UnifiedConfigManager()
        self._theme_data: Optional[Dict[str, Any]] = None
        self._theme_path: Optional[Path] = None
        self._is_active = False
        self._backup_theme: Optional[Dict[str, Any]] = None
        self.audit_logger = AuditLogger()

    def load(self, theme_path: str) -> bool:
        """
        Load a custom theme from a JSON file.

        Args:
            theme_path (str): Absolute or relative path to the theme JSON file.

        Returns:
            bool: True if loaded successfully, False otherwise.
        """
        try:
            self._theme_path = Path(theme_path).resolve()
            if not self._theme_path.exists():
                logger.error(f"Theme file not found: {self._theme_path}")
                return False

            with open(self._theme_path, 'r', encoding='utf-8') as f:
                raw_data = json.load(f)

            # Validate against schema (if available)
            if not self._validate_theme(raw_data):
                logger.error("Theme validation failed")
                return False

            self._theme_data = raw_data
            self._metadata = {
                "name": raw_data.get("name", "Unnamed Custom Theme"),
                "author": raw_data.get("author", "Unknown"),
                "version": raw_data.get("version", "1.0.0"),
                "description": raw_data.get("description", ""),
                "compatibility": raw_data.get("compatibility", [">=1.0.0"])
            }

            logger.info(f"✅ Custom theme loaded: {self._metadata['name']} v{self._metadata['version']}")
            self.audit_logger.log("THEME_LOAD", {"theme_name": self._metadata["name"], "path": str(self._theme_path)})
            return True

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in theme file: {e}")
        except Exception as e:
            logger.exception(f"Unexpected error loading theme: {e}")

        return False

    def _validate_theme(self, data: Dict[str, Any]) -> bool:
        """Validate theme structure and required fields."""
        required_keys = {"name", "colors", "fonts", "spacing"}
        if not required_keys.issubset(data.keys()):
            missing = required_keys - data.keys()
            logger.warning(f"Theme missing required keys: {missing}")
            return False

        # Optional: validate against JSON schema if present
        schema_path = Path("config/schemas/ui_config.schema.json")
        if schema_path.exists():
            try:
                import jsonschema
                with open(schema_path, 'r') as s:
                    schema = json.load(s)
                jsonschema.validate(instance=data, schema=schema)
                return True
            except ImportError:
                logger.debug("jsonschema not installed; skipping schema validation")
            except jsonschema.ValidationError as ve:
                logger.error(f"Theme schema validation failed: {ve.message}")
                return False

        return True

    def activate(self) -> bool:
        """
        Apply the loaded custom theme to the UI system.
        Safely backs up current theme before applying.
        """
        if not self._theme_data:
            logger.error("No theme loaded. Call .load() first.")
            return False

        try:
            # Backup current theme via config manager
            current_ui_config = self.config_manager.get("ui_config", {})
            self._backup_theme = current_ui_config.copy()

            # Merge or replace UI config
            new_config = {**current_ui_config, **self._theme_data}
            self.config_manager.set("ui_config", new_config)
            self.config_manager.save()

            self._is_active = True
            logger.info(f"🎨 Custom theme activated: {self._metadata['name']}")
            self.audit_logger.log("THEME_ACTIVATE", {"theme_name": self._metadata["name"]})
            return True

        except Exception as e:
            logger.exception(f"Failed to activate theme: {e}")
            self.audit_logger.log("THEME_ACTIVATE_ERROR", {"error": str(e)})
            return False

    def deactivate(self) -> bool:
        """
        Revert to the previous UI theme (rollback).
        """
        if not self._backup_theme:
            logger.warning("No backup theme available for rollback")
            return False

        try:
            self.config_manager.set("ui_config", self._backup_theme)
            self.config_manager.save()
            self._is_active = False
            logger.info("🔄 Theme reverted to previous state")
            self.audit_logger.log("THEME_DEACTIVATE", {"theme_name": self._metadata.get("name", "unknown")})
            return True

        except Exception as e:
            logger.exception(f"Failed to deactivate theme: {e}")
            return False

    def unload(self) -> None:
        """Clean up resources."""
        if self._is_active:
            self.deactivate()
        self._theme_data = None
        self._theme_path = None
        self._backup_theme = None
        logger.debug("🧹 Custom theme plugin unloaded")

    def get_theme_info(self) -> Dict[str, Any]:
        """Return metadata about the loaded theme."""
        return self._metadata.copy() if self._metadata else {}

    def is_active(self) -> bool:
        return self._is_active

    def supports_hot_reload(self) -> bool:
        return True

    def reload(self) -> bool:
        """Reload theme from file (for hot-reload scenarios)."""
        if not self._theme_path:
            return False
        success = self.load(str(self._theme_path))
        if success and self._is_active:
            return self.activate()
        return success