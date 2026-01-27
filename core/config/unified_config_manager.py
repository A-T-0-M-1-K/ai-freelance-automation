# core/config/unified_config_manager.py
"""
Unified Configuration Manager for AI Freelance Automation System.
Provides a single source of truth for all system configurations with:
- Hot-reloading without restart
- Profile-based configuration (dev/staging/prod)
- Schema validation (JSON Schema)
- Environment variable override support
- Legacy config migration
- Thread-safe access
"""

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional, Union
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

import logging

from .config_validator import ConfigValidator
from .env_loader import EnvLoader
from .legacy_config_adapter import LegacyConfigAdapter
from .config_migrator import ConfigMigrator

logger = logging.getLogger("UnifiedConfigManager")


class ConfigReloadHandler(FileSystemEventHandler):
    """Handles file system events to trigger hot-reload."""

    def __init__(self, config_manager: "UnifiedConfigManager"):
        self.config_manager = config_manager

    def on_modified(self, event):
        if not event.is_directory and event.src_path.endswith(".json"):
            logger.info(f"🔄 Detected config change: {event.src_path}")
            try:
                self.config_manager._reload_config_safely()
            except Exception as e:
                logger.error(f"❌ Failed to reload config after file change: {e}", exc_info=True)


class UnifiedConfigManager:
    """
    Centralized, thread-safe configuration manager with hot-reload,
    validation, and profile support.
    """

    def __init__(
        self,
        base_config_dir: Union[str, Path] = "config",
        profile: Optional[str] = None,
        enable_hot_reload: bool = True,
    ):
        self._lock = threading.RLock()
        self._base_config_dir = Path(base_config_dir).resolve()
        self._profile = profile or os.getenv("APP_PROFILE", "default")
        self._enable_hot_reload = enable_hot_reload
        self._config: Dict[str, Any] = {}
        self._validator = ConfigValidator(self._base_config_dir / "schemas")
        self._env_loader = EnvLoader()
        self._legacy_adapter = LegacyConfigAdapter(self._base_config_dir)
        self._migrator = ConfigMigrator()

        # Initialize
        self._load_config()
        if self._enable_hot_reload:
            self._start_hot_reload_watcher()

    def _load_config(self) -> None:
        """Load and merge configs from base + profile + env."""
        with self._lock:
            # 1. Load base config
            base_config = self._load_json_file(self._base_config_dir / "settings.json")

            # 2. Load profile config (if exists)
            profile_path = self._base_config_dir / "profiles" / f"{self._profile}.json"
            profile_config = {}
            if profile_path.exists():
                profile_config = self._load_json_file(profile_path)
                logger.info(f"✅ Loaded profile config: {self._profile}")

            # 3. Merge base + profile
            merged = self._deep_merge(base_config, profile_config)

            # 4. Apply environment overrides
            env_overrides = self._env_loader.load_env_overrides()
            merged = self._deep_merge(merged, env_overrides)

            # 5. Migrate legacy configs if needed
            merged = self._migrator.migrate_if_needed(merged)

            # 6. Validate final config
            if not self._validator.validate(merged):
                raise ValueError("❌ Configuration validation failed!")

            # 7. Store
            self._config = merged
            logger.info(f"✅ Configuration loaded successfully (profile: {self._profile})")

    def _load_json_file(self, path: Path) -> Dict[str, Any]:
        """Safely load a JSON file."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            logger.warning(f"⚠️ Config file not found: {path}")
            return {}
        except json.JSONDecodeError as e:
            logger.error(f"❌ Invalid JSON in {path}: {e}")
            raise

    def _deep_merge(self, base: Dict, override: Dict) -> Dict:
        """Recursively merge two dictionaries."""
        result = base.copy()
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value
        return result

    def _reload_config_safely(self) -> None:
        """Reload config in a safe way without breaking running operations."""
        try:
            old_config = self._config.copy()
            self._load_config()
            logger.info("✅ Hot-reload completed successfully.")
        except Exception as e:
            logger.error(f"⚠️ Hot-reload failed, reverting to previous config: {e}")
            with self._lock:
                self._config = old_config

    def _start_hot_reload_watcher(self) -> None:
        """Start file system watcher for hot-reload."""
        self._observer = Observer()
        handler = ConfigReloadHandler(self)
        self._observer.schedule(handler, str(self._base_config_dir), recursive=True)
        self._observer.start()
        logger.info(f"👁️  Hot-reload enabled for config directory: {self._base_config_dir}")

    def get(self, key_path: str, default: Any = None) -> Any:
        """
        Get config value by dot-separated key path.
        Example: get("ai.models.whisper.device")
        """
        with self._lock:
            keys = key_path.split(".")
            value = self._config
            try:
                for k in keys:
                    value = value[k]
                return value
            except (KeyError, TypeError):
                if default is not None:
                    return default
                raise KeyError(f"Config key not found: {key_path}")

    def set_profile(self, profile: str) -> None:
        """Switch to a new profile and reload config."""
        logger.info(f"🔄 Switching config profile to: {profile}")
        self._profile = profile
        self._reload_config_safely()

    def get_all(self) -> Dict[str, Any]:
        """Return a deep copy of the entire config (safe for external use)."""
        import copy
        with self._lock:
            return copy.deepcopy(self._config)

    def shutdown(self) -> None:
        """Gracefully shut down hot-reload observer."""
        if hasattr(self, "_observer") and self._observer.is_alive():
            self._observer.stop()
            self._observer.join()
            logger.info("⏹️  Config watcher stopped.")

    def __del__(self):
        self.shutdown()