# config/config_manager.py
"""
Unified Configuration Manager Interface
Provides a clean, validated, and reloadable interface to all system configurations.
Integrates with core.config.unified_config_manager for actual logic.
"""

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional, Union

from jsonschema import validate, ValidationError
from dotenv import load_dotenv

# Load environment variables early (before any config usage)
load_dotenv()

# Configure logger
logger = logging.getLogger("ConfigManager")

# Constants
CONFIG_DIR = Path(__file__).parent.resolve()
SCHEMAS_DIR = CONFIG_DIR / "schemas"
PROFILES_DIR = CONFIG_DIR / "profiles"


class ConfigManager:
    """
    High-level configuration manager that delegates to core UnifiedConfigManager.
    This file acts as the public API for config access across the application.
    """

    _instance: Optional["ConfigManager"] = None
    _initialized: bool = False

    def __new__(cls) -> "ConfigManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._config_cache: Dict[str, Any] = {}
        self._schema_cache: Dict[str, Any] = {}
        self._initialized = True

    def get(self, key: str, default: Any = None) -> Any:
        """
        Get a configuration value by dotted key (e.g., 'security.encryption.enabled').
        Falls back to environment variables if not found in config files.
        """
        try:
            # Try to resolve from loaded configs
            parts = key.split(".")
            current = self._load_or_get_config(parts[0])
            for part in parts[1:]:
                if isinstance(current, dict) and part in current:
                    current = current[part]
                else:
                    raise KeyError(f"Key '{key}' not found in config")
            return current
        except (KeyError, FileNotFoundError, json.JSONDecodeError) as e:
            logger.debug(f"Config key '{key}' not found in files: {e}")
            # Fallback to environment variable
            env_key = key.replace(".", "_").upper()
            env_value = os.getenv(env_key)
            if env_value is not None:
                return self._parse_env_value(env_value)
            return default

    def reload(self, config_name: Optional[str] = None) -> None:
        """Reload one or all configuration files."""
        if config_name:
            self._config_cache.pop(config_name, None)
            logger.info(f"🔁 Reloaded config: {config_name}")
        else:
            self._config_cache.clear()
            logger.info("🔁 Reloaded all configurations")

    def validate_all(self) -> bool:
        """Validate all config files against their schemas. Returns True if all valid."""
        config_files = [f for f in CONFIG_DIR.glob("*.json") if f.name != "config_manager.py"]
        all_valid = True
        for config_file in config_files:
            if not self._validate_config_file(config_file):
                all_valid = False
        return all_valid

    def _load_or_get_config(self, config_name: str) -> Dict[str, Any]:
        """Load config from file or return cached version."""
        if config_name in self._config_cache:
            return self._config_cache[config_name]

        config_path = CONFIG_DIR / f"{config_name}.json"
        if not config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_path}")

        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

        # Validate
        schema_path = SCHEMAS_DIR / f"{config_name}.schema.json"
        if schema_path.exists():
            schema = self._load_schema(schema_path)
            try:
                validate(instance=config, schema=schema)
            except ValidationError as ve:
                logger.error(f"❌ Validation failed for {config_name}: {ve.message}")
                raise ValueError(f"Invalid config in {config_name}: {ve.message}") from ve

        self._config_cache[config_name] = config
        return config

    def _load_schema(self, schema_path: Path) -> Dict[str, Any]:
        """Load and cache JSON schema."""
        if schema_path in self._schema_cache:
            return self._schema_cache[schema_path]

        with open(schema_path, "r", encoding="utf-8") as f:
            schema = json.load(f)
        self._schema_cache[schema_path] = schema
        return schema

    def _validate_config_file(self, config_path: Path) -> bool:
        """Validate a single config file. Logs errors but does not raise."""
        try:
            config_name = config_path.stem
            self._load_or_get_config(config_name)
            logger.debug(f"✅ {config_name} is valid")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to validate {config_path}: {e}")
            return False

    def _parse_env_value(self, value: str) -> Union[str, int, float, bool, None]:
        """Parse environment variable string into appropriate type."""
        if value.lower() in ("true", "1", "yes", "on"):
            return True
        if value.lower() in ("false", "0", "no", "off"):
            return False
        if value.isdigit():
            return int(value)
        try:
            return float(value)
        except ValueError:
            pass
        if value == "null":
            return None
        return value


# Global instance for easy import
config_manager = ConfigManager()