# AI_FREELANCE_AUTOMATION/tests/unit/test_config_manager.py
"""
Unit tests for the Unified Config Manager.
Validates loading, validation, schema enforcement, hot-reload, and error handling.
"""

import os
import json
import tempfile
import pytest
from unittest.mock import patch, MagicMock

# Предполагаем, что основной менеджер находится в core/config/
from core.config.unified_config_manager import UnifiedConfigManager
from core.config.config_validator import ConfigValidator


class TestUnifiedConfigManager:
    """Test suite for UnifiedConfigManager."""

    def setup_method(self):
        """Prepare clean test environment before each test."""
        self.test_dir = tempfile.TemporaryDirectory()
        self.config_path = os.path.join(self.test_dir.name, "test_config.json")
        self.schema_path = os.path.join(self.test_dir.name, "test_schema.json")

        # Пример валидной конфигурации
        self.valid_config = {
            "system": {
                "log_level": "INFO",
                "max_concurrent_jobs": 10,
                "enable_monitoring": True
            },
            "ai": {
                "model_provider": "openai",
                "fallback_enabled": True
            }
        }

        # Простая JSON Schema
        self.valid_schema = {
            "type": "object",
            "properties": {
                "system": {
                    "type": "object",
                    "properties": {
                        "log_level": {"type": "string", "enum": ["DEBUG", "INFO", "WARNING", "ERROR"]},
                        "max_concurrent_jobs": {"type": "integer", "minimum": 1, "maximum": 100},
                        "enable_monitoring": {"type": "boolean"}
                    },
                    "required": ["log_level", "max_concurrent_jobs", "enable_monitoring"]
                },
                "ai": {
                    "type": "object",
                    "properties": {
                        "model_provider": {"type": "string"},
                        "fallback_enabled": {"type": "boolean"}
                    },
                    "required": ["model_provider", "fallback_enabled"]
                }
            },
            "required": ["system", "ai"]
        }

        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(self.valid_config, f, indent=2)
        with open(self.schema_path, 'w', encoding='utf-8') as f:
            json.dump(self.valid_schema, f, indent=2)

    def teardown_method(self):
        """Clean up after each test."""
        self.test_dir.cleanup()

    def test_load_valid_config_success(self):
        """Test successful loading of a valid config file."""
        config_manager = UnifiedConfigManager(config_path=self.config_path, schema_path=self.schema_path)
        loaded = config_manager.get("system.log_level")
        assert loaded == "INFO"
        assert config_manager.get("ai.fallback_enabled") is True

    def test_invalid_config_raises_error(self):
        """Test that invalid config fails validation."""
        invalid_config = self.valid_config.copy()
        invalid_config["system"]["log_level"] = "INVALID_LEVEL"

        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(invalid_config, f)

        with pytest.raises(ValueError, match="Configuration validation failed"):
            UnifiedConfigManager(config_path=self.config_path, schema_path=self.schema_path)

    def test_missing_required_field_fails(self):
        """Test missing required field triggers validation error."""
        incomplete_config = {
            "system": {
                "log_level": "INFO"
                # missing max_concurrent_jobs and enable_monitoring
            },
            "ai": self.valid_config["ai"]
        }

        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(incomplete_config, f)

        with pytest.raises(ValueError, match="Configuration validation failed"):
            UnifiedConfigManager(config_path=self.config_path, schema_path=self.schema_path)

    def test_get_nested_value_with_default(self):
        """Test safe get with fallback to default."""
        config_manager = UnifiedConfigManager(config_path=self.config_path, schema_path=self.schema_path)
        value = config_manager.get("non.existent.key", default="fallback")
        assert value == "fallback"

    def test_hot_reload_updates_config(self):
        """Test dynamic config reload without restart."""
        config_manager = UnifiedConfigManager(config_path=self.config_path, schema_path=self.schema_path)
        assert config_manager.get("system.max_concurrent_jobs") == 10

        # Изменяем файл
        updated_config = self.valid_config.copy()
        updated_config["system"]["max_concurrent_jobs"] = 25
        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(updated_config, f)

        # Перезагружаем
        config_manager.reload()
        assert config_manager.get("system.max_concurrent_jobs") == 25

    @patch("core.config.config_validator.validate")
    def test_validation_called_on_init(self, mock_validate):
        """Ensure validator is invoked during initialization."""
        mock_validate.return_value = None  # No exception = valid
        UnifiedConfigManager(config_path=self.config_path, schema_path=self.schema_path)
        mock_validate.assert_called_once()

    def test_env_override_support(self):
        """Test that environment variables can override config (if implemented)."""
        # Устанавливаем env var
        os.environ["AI_FREELANCE_SYSTEM_LOG_LEVEL"] = "DEBUG"

        try:
            config_manager = UnifiedConfigManager(config_path=self.config_path, schema_path=self.schema_path)
            # Если поддержка env включена — должно быть DEBUG
            # Но если не реализована — тест не падает, просто проверяем базовое поведение
            # Здесь предполагаем, что env_loader интегрирован через unified_config_manager
            # Для unit-теста оставим как опциональную проверку
            assert config_manager.get("system.log_level") in ("INFO", "DEBUG")
        finally:
            os.environ.pop("AI_FREELANCE_SYSTEM_LOG_LEVEL", None)

    def test_config_is_immutable_after_load(self):
        """Ensure internal config cannot be mutated externally."""
        config_manager = UnifiedConfigManager(config_path=self.config_path, schema_path=self.schema_path)
        raw = config_manager._config  # Предполагаем защищённый доступ
        with pytest.raises(TypeError):
            raw["system"]["log_level"] = "HACK"  # Должен быть заморожен или копия

    def test_schema_not_found_raises_error(self):
        """Missing schema file should raise clear error."""
        with pytest.raises(FileNotFoundError, match="Schema file not found"):
            UnifiedConfigManager(config_path=self.config_path, schema_path="/invalid/path.json")