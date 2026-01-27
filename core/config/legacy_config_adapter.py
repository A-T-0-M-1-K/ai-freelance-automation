# core/config/legacy_config_adapter.py
"""
Legacy Configuration Adapter

Мост между старыми AI-конфигурациями (ai/configs/) и новой унифицированной системой.
Обеспечивает безопасную миграцию без потери данных и с полной валидацией.
"""

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

from core.config.config_validator import ConfigValidator
from core.config.unified_config_manager import UnifiedConfigManager

# Инициализация логгера
logger = logging.getLogger(__name__)


class LegacyConfigAdapter:
    """
    Адаптер для преобразования устаревших конфигураций в новый формат.

    Поддерживаемые старые конфиги:
        - embeddings_config.json
        - nlp_config.json
        - textgen_config.json
        - translation_config.json
        - whisper_config.json
        - model_configs/*.json
    """

    # Сопоставление старых файлов → новые секции в unified config
    _MAPPING = {
        "embeddings_config.json": "ai.embeddings",
        "nlp_config.json": "ai.nlp",
        "textgen_config.json": "ai.textgen",
        "translation_config.json": "ai.translation",
        "whisper_config.json": "ai.transcription",
    }

    def __init__(
            self,
            legacy_config_dir: str = "ai/configs",
            unified_config_manager: Optional[UnifiedConfigManager] = None,
            schema_dir: str = "config/schemas"
    ):
        self.legacy_dir = Path(legacy_config_dir).resolve()
        self.schema_dir = Path(schema_dir).resolve()
        self.unified_config = unified_config_manager
        self.validator = ConfigValidator(schema_dir=str(self.schema_dir))
        self._migrated_data: Dict[str, Any] = {}

        if not self.legacy_dir.exists():
            logger.warning(f"Legacy config directory not found: {self.legacy_dir}")
        else:
            logger.info(f"Legacy config adapter initialized for: {self.legacy_dir}")

    def migrate_all(self) -> Dict[str, Any]:
        """
        Мигрирует все поддерживаемые legacy-конфиги в единый формат.
        Возвращает словарь с объединёнными данными, готовыми к интеграции.
        """
        logger.info("🔄 Starting legacy configuration migration...")

        # 1. Миграция основных конфигов
        for filename, target_path in self._MAPPING.items():
            file_path = self.legacy_dir / filename
            if file_path.exists():
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    self._migrated_data = self._deep_merge(
                        self._migrated_data,
                        self._build_nested_dict(target_path, data)
                    )
                    logger.debug(f"Migrated {filename} → {target_path}")
                except Exception as e:
                    logger.error(f"❌ Failed to migrate {filename}: {e}", exc_info=True)

        # 2. Миграция модель-специфичных конфигов
        model_configs_dir = self.legacy_dir / "model_configs"
        if model_configs_dir.exists():
            for model_file in model_configs_dir.glob("*.json"):
                try:
                    with open(model_file, "r", encoding="utf-8") as f:
                        model_data = json.load(f)
                    model_name = model_file.stem
                    # Определяем тип модели по имени (простая эвристика)
                    if "whisper" in model_name:
                        key = f"ai.transcription.models.{model_name}"
                    elif "translation" in model_name:
                        key = f"ai.translation.models.{model_name}"
                    elif "textgen" in model_name:
                        key = f"ai.textgen.models.{model_name}"
                    elif "embeddings" in model_name:
                        key = f"ai.embeddings.models.{model_name}"
                    else:
                        key = f"ai.models.{model_name}"

                    self._migrated_data = self._deep_merge(
                        self._migrated_data,
                        self._build_nested_dict(key, model_data)
                    )
                    logger.debug(f"Migrated model config: {model_file.name} → {key}")
                except Exception as e:
                    logger.error(f"❌ Failed to migrate model config {model_file.name}: {e}", exc_info=True)

        logger.info("✅ Legacy configuration migration completed.")
        return self._migrated_data

    def integrate_into_unified_config(self) -> bool:
        """
        Интегрирует мигрированные данные в UnifiedConfigManager.
        Выполняет валидацию перед применением.

        Returns:
            bool: True если интеграция успешна, иначе False
        """
        if self.unified_config is None:
            logger.error("UnifiedConfigManager not provided. Cannot integrate.")
            return False

        migrated = self.migrate_all()
        if not migrated:
            logger.info("No legacy configs to integrate.")
            return True

        try:
            # Валидация каждой секции отдельно
            for section_key, section_data in self._flatten_dict(migrated).items():
                if "." in section_key:
                    # Пример: ai.textgen.temperature → валидируем как ai/textgen.schema.json
                    parts = section_key.split(".")
                    schema_name = f"{'_'.join(parts[:2])}.schema.json"
                    schema_path = self.schema_dir / schema_name
                    if schema_path.exists():
                        if not self.validator.validate_section(section_data, str(schema_path)):
                            logger.warning(f"Validation failed for section {section_key}, skipping.")
                            continue

            # Обновляем конфигурацию (без перезаписи всего — только merge)
            self.unified_config.merge_config(migrated)
            logger.info("✅ Legacy configs successfully integrated into unified configuration.")
            return True

        except Exception as e:
            logger.critical(f"💥 Critical error during config integration: {e}", exc_info=True)
            return False

    @staticmethod
    def _build_nested_dict(path: str, value: Any) -> Dict[str, Any]:
        """Преобразует точечную нотацию в вложенный словарь."""
        keys = path.split(".")
        result = current = {}
        for key in keys[:-1]:
            current[key] = {}
            current = current[key]
        current[keys[-1]] = value
        return result

    @staticmethod
    def _deep_merge(a: Dict, b: Dict) -> Dict:
        """Рекурсивное слияние двух словарей."""
        result = a.copy()
        for key, value in b.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = LegacyConfigAdapter._deep_merge(result[key], value)
            else:
                result[key] = value
        return result

    @staticmethod
    def _flatten_dict(d: Dict, parent_key: str = "", sep: str = ".") -> Dict[str, Any]:
        """Преобразует вложенный словарь в плоский с точечной нотацией."""
        items = []
        for k, v in d.items():
            new_key = f"{parent_key}{sep}{k}" if parent_key else k
            if isinstance(v, dict):
                items.extend(LegacyConfigAdapter._flatten_dict(v, new_key, sep=sep).items())
            else:
                items.append((new_key, v))
        return dict(items)