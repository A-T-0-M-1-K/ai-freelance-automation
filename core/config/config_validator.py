# core/config/config_validator.py
"""
Configuration Validator for AI Freelance Automation System.
Validates configuration files against JSON schemas to ensure integrity,
security, and compatibility across all subsystems.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, Union
from jsonschema import validate, ValidationError, Draft202012Validator
from jsonschema.validators import validator_for

# Internal imports (relative to maintain clean architecture)
from .unified_config_manager import ConfigError

# Logger setup
logger = logging.getLogger(__name__)


class ConfigValidator:
    """
    Validates configuration dictionaries or files against predefined JSON schemas.
    Supports schema auto-discovery, custom error handling, and safe validation.
    """

    def __init__(self, schemas_dir: Union[str, Path] = "config/schemas"):
        """
        Initialize the validator with a directory containing JSON schema files.

        Args:
            schemas_dir (Union[str, Path]): Path to directory with *.schema.json files.
        """
        self.schemas_dir = Path(schemas_dir).resolve()
        if not self.schemas_dir.exists():
            raise FileNotFoundError(f"Schema directory not found: {self.schemas_dir}")
        self._compiled_schemas: Dict[str, Draft202012Validator] = {}
        self._load_all_schemas()
        logger.debug(f"ConfigValidator initialized with schemas from {self.schemas_dir}")

    def _load_all_schemas(self) -> None:
        """Pre-load and compile all JSON schemas for performance."""
        for schema_path in self.schemas_dir.glob("*.schema.json"):
            schema_name = schema_path.stem.replace(".schema", "")
            try:
                with open(schema_path, "r", encoding="utf-8") as f:
                    raw_schema = json.load(f)
                validator_class = validator_for(raw_schema)
                validator = validator_class(raw_schema)
                validator.check_schema(raw_schema)  # Validate schema itself
                self._compiled_schemas[schema_name] = validator
                logger.debug(f"Loaded schema: {schema_name}")
            except (json.JSONDecodeError, ValueError) as e:
                logger.error(f"Invalid JSON in schema file {schema_path}: {e}")
                raise ConfigError(f"Corrupted schema file: {schema_path}") from e
            except Exception as e:
                logger.error(f"Failed to load schema {schema_path}: {e}")
                raise ConfigError(f"Schema loading failed: {schema_path}") from e

    def validate_config(
        self,
        config_data: Dict[str, Any],
        schema_name: str,
        source: str = "unknown"
    ) -> bool:
        """
        Validate a configuration dictionary against a named schema.

        Args:
            config_data (Dict[str, Any]): Configuration data to validate.
            schema_name (str): Name of the schema (e.g., 'ai_config' → uses ai_config.schema.json).
            source (str): Human-readable source (e.g., file path or profile name) for logging.

        Returns:
            bool: True if valid.

        Raises:
            ConfigError: If validation fails or schema is missing.
        """
        if schema_name not in self._compiled_schemas:
            available = ", ".join(self._compiled_schemas.keys())
            raise ConfigError(
                f"Schema '{schema_name}' not found. Available: {available}"
            )

        validator = self._compiled_schemas[schema_name]
        try:
            validator.validate(config_data)
            logger.info(f"✅ Configuration '{source}' passed validation against '{schema_name}' schema.")
            return True
        except ValidationError as ve:
            message = (
                f"❌ Validation failed for '{source}' using schema '{schema_name}': "
                f"{ve.message} at {' -> '.join(map(str, ve.absolute_path))}"
            )
            logger.error(message)
            raise ConfigError(message) from ve
        except Exception as e:
            logger.error(f"Unexpected error during validation of '{source}': {e}")
            raise ConfigError(f"Validation process failed: {e}") from e

    def validate_file(self, config_path: Union[str, Path], schema_name: str) -> bool:
        """
        Load and validate a configuration file directly.

        Args:
            config_path (Union[str, Path]): Path to JSON config file.
            schema_name (str): Schema name to validate against.

        Returns:
            bool: True if valid.
        """
        config_path = Path(config_path)
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config_data = json.load(f)
        except json.JSONDecodeError as e:
            raise ConfigError(f"Invalid JSON in config file {config_path}: {e}") from e

        return self.validate_config(config_data, schema_name, source=str(config_path))

    def get_available_schemas(self) -> list[str]:
        """Return list of available schema names."""
        return list(self._compiled_schemas.keys())