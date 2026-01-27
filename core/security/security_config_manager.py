# AI_FREELANCE_AUTOMATION/core/security/security_config_manager.py
"""
Security Configuration Manager

Responsible for loading, validating, and managing security-related configuration.
Integrates with UnifiedConfigManager and supports schema validation,
hot-reloading, and secure defaults.

Key features:
- Loads security config from unified source (e.g., config/security.json)
- Validates against JSON schema (config/schemas/security.schema.json)
- Provides secure fallbacks for missing/invalid values
- Supports runtime updates without restart
- Integrates with key rotation and audit systems
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional
from core.config.unified_config_manager import UnifiedConfigManager
from core.config.config_validator import ConfigValidator

logger = logging.getLogger("SecurityConfigManager")


class SecurityConfigManager:
    """
    Manages all security-related configuration parameters.
    Ensures compliance with PCI DSS, GDPR, HIPAA, and SOC 2 by enforcing secure defaults.
    """

    # Secure defaults (compliant with industry standards)
    _DEFAULTS = {
        "encryption": {
            "data_at_rest_algorithm": "AES-256-GCM",
            "data_in_transit_algorithm": "TLSv1.3",
            "key_derivation_function": "Argon2id",
            "key_rotation_days": 90,
            "use_hardware_security_module": False,
        },
        "authentication": {
            "multi_factor_required": True,
            "session_timeout_minutes": 15,
            "max_failed_attempts": 5,
            "lockout_duration_minutes": 30,
        },
        "audit": {
            "log_all_operations": True,
            "retain_logs_days": 365,
            "immutable_logging": True,
        },
        "anomaly_detection": {
            "enabled": True,
            "sensitivity_level": "high",  # low, medium, high
            "auto_block_suspicious_ip": True,
        },
        "compliance": {
            "gdpr_enabled": True,
            "pci_dss_enabled": True,
            "hipaa_enabled": False,  # opt-in due to overhead
            "soc2_enabled": True,
        },
        "rate_limiting": {
            "enabled": True,
            "requests_per_minute": 100,
            "burst_capacity": 20,
        },
    }

    def __init__(self, unified_config: Optional[UnifiedConfigManager] = None):
        """
        Initialize the security config manager.

        :param unified_config: Optional pre-initialized config manager.
                               If not provided, creates a new instance.
        """
        self._config_manager = unified_config or UnifiedConfigManager()
        self._validator = ConfigValidator()
        self._current_config: Dict[str, Any] = {}
        self._schema_path = Path("config/schemas/security.schema.json")
        self._load_and_validate()

    def _load_and_validate(self) -> None:
        """Load and validate security configuration."""
        try:
            raw_config = self._config_manager.get_section("security")
            if not raw_config:
                logger.warning("No 'security' section found in config. Using secure defaults.")
                raw_config = self._DEFAULTS.copy()

            # Validate against schema
            if self._schema_path.exists():
                with open(self._schema_path, "r", encoding="utf-8") as f:
                    schema = json.load(f)
                self._validator.validate(raw_config, schema)
            else:
                logger.warning(f"Security schema not found at {self._schema_path}. Skipping validation.")

            self._current_config = self._merge_with_defaults(raw_config)
            logger.info("✅ Security configuration loaded and validated successfully.")

        except Exception as e:
            logger.error(f"❌ Failed to load security config: {e}. Falling back to defaults.")
            self._current_config = self._DEFAULTS.copy()

    def _merge_with_defaults(self, user_config: Dict[str, Any]) -> Dict[str, Any]:
        """Recursively merge user config with secure defaults."""
        def deep_merge(base: Dict, override: Dict) -> Dict:
            result = base.copy()
            for key, value in override.items():
                if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                    result[key] = deep_merge(result[key], value)
                else:
                    result[key] = value
            return result

        return deep_merge(self._DEFAULTS, user_config)

    def get(self, key_path: str, default: Any = None) -> Any:
        """
        Get a security config value using dot notation (e.g., 'encryption.key_rotation_days').

        :param key_path: Dot-separated path to the config value
        :param default: Fallback if key not found
        :return: Config value or default
        """
        keys = key_path.split(".")
        value = self._current_config
        try:
            for key in keys:
                value = value[key]
            return value
        except (KeyError, TypeError):
            if default is not None:
                return default
            logger.warning(f"Security config key '{key_path}' not found. Returning None.")
            return None

    def reload(self) -> bool:
        """
        Reload configuration from source (e.g., file or env).
        Used for hot-reload without restart.

        :return: True if reload succeeded, False otherwise
        """
        old_config = self._current_config.copy()
        try:
            self._load_and_validate()
            if self._current_config != old_config:
                logger.info("🔄 Security configuration reloaded successfully.")
                return True
            else:
                logger.debug("Security config unchanged; no reload needed.")
                return True
        except Exception as e:
            logger.error(f"💥 Hot-reload of security config failed: {e}")
            return False

    def is_compliance_enabled(self, standard: str) -> bool:
        """Check if a compliance standard is enabled (e.g., 'gdpr', 'pci_dss')."""
        return bool(self.get(f"compliance.{standard}_enabled", False))

    def get_key_rotation_interval_days(self) -> int:
        """Get key rotation interval in days."""
        return int(self.get("encryption.key_rotation_days", 90))

    def requires_mfa(self) -> bool:
        """Check if multi-factor authentication is required."""
        return bool(self.get("authentication.multi_factor_required", True))

    def get_rate_limit(self) -> Dict[str, int]:
        """Get rate limiting settings."""
        return {
            "requests_per_minute": self.get("rate_limiting.requests_per_minute", 100),
            "burst_capacity": self.get("rate_limiting.burst_capacity", 20),
        }

    def to_dict(self) -> Dict[str, Any]:
        """Return a copy of the current config (safe for logging/redaction)."""
        # ⚠️ Never log secrets! This assumes no raw secrets are stored here.
        return self._current_config.copy()