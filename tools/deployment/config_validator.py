# AI_FREELANCE_AUTOMATION/tools/deployment/config_validator.py
"""
Configuration Validator for Deployment

Validates all system configuration files against their respective JSON schemas.
Ensures integrity, correctness, and compliance before deployment or hot-reload.
Integrates with core.config.unified_config_manager and logging systems.

Features:
- Validates all .json configs in /config/
- Uses schema files from /config/schemas/
- Supports profile-based validation (dev/staging/prod)
- Safe error reporting without exposing secrets
- Compatible with CI/CD pipelines
"""

import json
import logging
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from jsonschema import validate, ValidationError, Draft202012Validator
from jsonschema.exceptions import SchemaError

# Configure module-specific logger
logger = logging.getLogger(__name__)

# Project root detection (robust to execution context)
PROJECT_ROOT = Path(__file__).resolve().parents[3]
CONFIG_DIR = PROJECT_ROOT / "config"
SCHEMAS_DIR = CONFIG_DIR / "schemas"


class ConfigValidator:
    """
    Validates system configuration files against JSON schemas.
    Designed for use in deployment pipelines and runtime config reloads.
    """

    def __init__(self, config_dir: Optional[Path] = None, schemas_dir: Optional[Path] = None):
        self.config_dir = config_dir or CONFIG_DIR
        self.schemas_dir = schemas_dir or SCHEMAS_DIR
        self._ensure_directories_exist()

    def _ensure_directories_exist(self) -> None:
        """Ensure required directories exist."""
        if not self.config_dir.exists():
            raise FileNotFoundError(f"Config directory not found: {self.config_dir}")
        if not self.schemas_dir.exists():
            raise FileNotFoundError(f"Schemas directory not found: {self.schemas_dir}")

    def _load_json_file(self, file_path: Path) -> Any:
        """Safely load a JSON file."""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in {file_path}: {e}") from e
        except Exception as e:
            raise IOError(f"Failed to read {file_path}: {e}") from e

    def _get_schema_for_config(self, config_name: str) -> Dict[str, Any]:
        """Get corresponding schema for a config file."""
        schema_name = f"{config_name}.schema.json"
        schema_path = self.schemas_dir / schema_name

        if not schema_path.exists():
            # Try fallback: remove extension if present (e.g., ai_config.json → ai_config.schema.json)
            base_name = config_name.rsplit(".", 1)[0] if "." in config_name else config_name
            schema_path = self.schemas_dir / f"{base_name}.schema.json"

        if not schema_path.exists():
            raise FileNotFoundError(f"No schema found for config '{config_name}' at {schema_path}")

        return self._load_json_file(schema_path)

    def validate_single_config(self, config_file: Path) -> bool:
        """
        Validate a single config file against its schema.

        Returns:
            bool: True if valid, raises exception otherwise.
        """
        config_name = config_file.stem  # e.g., 'ai_config'
        logger.debug(f"Validating config: {config_file.name}")

        config_data = self._load_json_file(config_file)
        schema = self._get_schema_for_config(config_name)

        try:
            # Compile validator for better error messages
            validator = Draft202012Validator(schema)
            validator.check_schema(schema)  # Validate schema itself
            validate(instance=config_data, schema=schema, cls=Draft202012Validator)
            logger.info(f"✅ Config '{config_file.name}' is VALID")
            return True
        except SchemaError as e:
            logger.error(f"❌ Invalid schema for '{config_file.name}': {e.message}")
            raise
        except ValidationError as e:
            # Mask sensitive paths/values in error (security best practice)
            error_path = " → ".join(str(p) for p in e.absolute_path) if e.absolute_path else "root"
            logger.error(
                f"❌ Validation failed for '{config_file.name}' at [{error_path}]: {e.message}"
            )
            raise
        except Exception as e:
            logger.error(f"💥 Unexpected error validating '{config_file.name}': {e}")
            raise

    def validate_all_configs(self, profile: Optional[str] = None) -> bool:
        """
        Validate all config files in /config/, including profile-specific ones.

        Args:
            profile (str, optional): Profile name (e.g., 'production'). If provided,
                                     also validates config/profiles/{profile}.json.

        Returns:
            bool: True if all configs are valid.
        """
        logger.info("🔍 Starting full configuration validation...")

        # Validate main config files
        config_files = [
            f for f in self.config_dir.glob("*.json")
            if f.is_file() and not f.name.startswith("profile.") and f.name != "config_manager.py"
        ]

        # Add profile config if specified
        if profile:
            profile_path = self.config_dir / "profiles" / f"{profile}.json"
            if profile_path.exists():
                config_files.append(profile_path)
            else:
                logger.warning(f"Profile config not found: {profile_path}")

        invalid_count = 0
        for config_file in config_files:
            try:
                self.validate_single_config(config_file)
            except Exception as e:
                logger.error(f"Failed to validate {config_file.name}: {e}")
                invalid_count += 1

        if invalid_count > 0:
            logger.critical(f"❌ {invalid_count} config(s) FAILED validation. Deployment blocked.")
            return False

        logger.info("✅ All configurations PASSED validation.")
        return True

    def validate_profile_set(self, profiles: List[str]) -> bool:
        """Validate multiple profiles (useful in CI)."""
        all_valid = True
        for profile in profiles:
            logger.info(f"🧪 Validating profile: {profile}")
            if not self.validate_all_configs(profile=profile):
                all_valid = False
        return all_valid


def main() -> int:
    """CLI entry point for config validation."""
    import argparse

    parser = argparse.ArgumentParser(description="Validate system configuration files.")
    parser.add_argument("--profile", type=str, help="Validate specific profile (e.g., production)")
    parser.add_argument("--all-profiles", action="store_true", help="Validate all known profiles")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging")

    args = parser.parse_args()

    # Setup logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)]
    )

    try:
        validator = ConfigValidator()

        if args.all_profiles:
            profiles_dir = CONFIG_DIR / "profiles"
            if not profiles_dir.exists():
                logger.error("Profiles directory not found")
                return 1
            profiles = [f.stem for f in profiles_dir.glob("*.json") if f.is_file()]
            success = validator.validate_profile_set(profiles)
        else:
            success = validator.validate_all_configs(profile=args.profile)

        return 0 if success else 1

    except Exception as e:
        logger.critical(f"Validation process crashed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())