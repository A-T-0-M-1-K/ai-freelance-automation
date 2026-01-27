#!/usr/bin/env python3
"""
Configuration Generator Tool

Generates validated configuration files for the AI Freelance Automation system
based on built-in templates and user-provided overrides.

Features:
- Supports all config types (ai, automation, security, platforms, etc.)
- Validates output against JSON schemas
- Generates environment-specific profiles
- Safe defaults with secure placeholders
- CLI and programmatic interfaces

Usage:
    python scripts/tools/config_generator.py --profile production --output ./config/
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional, List

# Add project root to path for imports
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

from core.config.config_validator import ConfigValidator
from core.config.unified_config_manager import UnifiedConfigManager


# Configure module logger
logger = logging.getLogger("ConfigGenerator")


class ConfigGenerator:
    """Generates and validates configuration files for the system."""

    # Mapping of config types to their default template paths
    CONFIG_TEMPLATES = {
        "ai_config": "config/ai_config.json",
        "automation": "config/automation.json",
        "backup_config": "config/backup_config.json",
        "database": "config/database.json",
        "deploy": "config/deploy.json",
        "logging": "config/logging.json",
        "notifications": "config/notifications.json",
        "performance": "config/performance.json",
        "platforms": "config/platforms.json",
        "recovery_plan": "config/recovery_plan.json",
        "security": "config/security.json",
        "settings": "config/settings.json",
        "ui_config": "config/ui_config.json",
    }

    PROFILE_DEFAULTS = {
        "default": {
            "log_level": "INFO",
            "max_concurrent_jobs": 5,
            "enable_monitoring": True,
            "use_gpu": False,
        },
        "development": {
            "log_level": "DEBUG",
            "max_concurrent_jobs": 2,
            "enable_monitoring": True,
            "use_gpu": False,
            "debug_mode": True,
        },
        "staging": {
            "log_level": "INFO",
            "max_concurrent_jobs": 10,
            "enable_monitoring": True,
            "use_gpu": True,
            "debug_mode": False,
        },
        "production": {
            "log_level": "WARNING",
            "max_concurrent_jobs": 50,
            "enable_monitoring": True,
            "use_gpu": True,
            "debug_mode": False,
            "enable_audit_logging": True,
        }
    }

    def __init__(self, profile: str = "default", output_dir: Path = None):
        self.profile = profile
        self.output_dir = output_dir or PROJECT_ROOT / "config"
        self.validator = ConfigValidator()
        self._ensure_output_dir()

    def _ensure_output_dir(self):
        """Ensure output directory exists."""
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _load_template(self, config_type: str) -> Dict[str, Any]:
        """Load base template for a config type."""
        template_path = PROJECT_ROOT / self.CONFIG_TEMPLATES[config_type]
        if not template_path.exists():
            # Fallback: generate minimal valid config
            logger.warning(f"Template not found: {template_path}. Using minimal defaults.")
            return self._minimal_config(config_type)
        try:
            with open(template_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load template {template_path}: {e}")
            return self._minimal_config(config_type)

    def _minimal_config(self, config_type: str) -> Dict[str, Any]:
        """Return minimal valid config if template missing."""
        base = {"version": "1.0", "generated_by": "ConfigGenerator", "profile": self.profile}
        if config_type == "security":
            base.update({
                "encryption": {"algorithm": "AES-256-GCM"},
                "key_rotation_days": 90,
                "store_keys_in_hsm": False
            })
        elif config_type == "platforms":
            base.update({"enabled_platforms": ["upwork", "freelance_ru"]})
        elif config_type == "ai_config":
            base.update({"model_provider": "openai", "default_model": "gpt-4"})
        return base

    def _apply_profile_overrides(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Apply profile-specific overrides."""
        profile_data = self.PROFILE_DEFAULTS.get(self.profile, {})
        config.update(profile_data)
        return config

    def _secure_sensitive_fields(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Replace sensitive values with placeholders."""
        sensitive_keys = ["api_key", "secret", "password", "token", "private_key"]
        def redact(obj):
            if isinstance(obj, dict):
                return {k: ("***REDACTED***" if any(sk in k.lower() for sk in sensitive_keys) else redact(v))
                        for k, v in obj.items()}
            elif isinstance(obj, list):
                return [redact(item) for item in obj]
            else:
                return obj
        return redact(config)

    def generate_config(self, config_type: str, user_overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Generate a single config file."""
        logger.info(f"Generating config: {config_type} (profile: {self.profile})")
        config = self._load_template(config_type)
        config = self._apply_profile_overrides(config)
        if user_overrides:
            config.update(user_overrides)
        config = self._secure_sensitive_fields(config)
        # Validate
        schema_path = PROJECT_ROOT / f"config/schemas/{config_type}.schema.json"
        if schema_path.exists():
            if not self.validator.validate(config, str(schema_path)):
                raise ValueError(f"Generated config for {config_type} failed validation")
        else:
            logger.warning(f"No schema found for {config_type} at {schema_path}")
        return config

    def save_config(self, config_type: str, config: Dict[str, Any]):
        """Save config to file."""
        filepath = self.output_dir / f"{config_type}.json"
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
        logger.info(f"Saved config: {filepath}")

    def generate_all(self, user_overrides: Optional[Dict[str, Any]] = None):
        """Generate all configuration files."""
        for config_type in self.CONFIG_TEMPLATES.keys():
            try:
                config = self.generate_config(config_type, user_overrides)
                self.save_config(config_type, config)
            except Exception as e:
                logger.error(f"Failed to generate {config_type}: {e}")
                raise

    @classmethod
    def from_cli(cls):
        """Create instance from CLI args."""
        parser = argparse.ArgumentParser(description="AI Freelance Automation Config Generator")
        parser.add_argument("--profile", default="default",
                            choices=["default", "development", "staging", "production"],
                            help="Configuration profile")
        parser.add_argument("--output", type=str, default=str(PROJECT_ROOT / "config"),
                            help="Output directory for config files")
        parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
        args = parser.parse_args()

        logging.basicConfig(level=getattr(logging, args.log_level.upper()))
        return cls(profile=args.profile, output_dir=Path(args.output))


def main():
    """CLI entry point."""
    try:
        generator = ConfigGenerator.from_cli()
        generator.generate_all()
        logger.info("✅ All configuration files generated successfully.")
    except KeyboardInterrupt:
        logger.info("Interrupted by user.")
        sys.exit(1)
    except Exception as e:
        logger.critical(f"Config generation failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()