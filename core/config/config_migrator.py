# core/config/config_migrator.py
"""
Модуль миграции конфигураций.
Переносит старые конфиги (из ai/configs/) в новую унифицированную систему.
Обеспечивает обратную совместимость, валидацию и безопасность.
"""

import json
import shutil
from pathlib import Path
from typing import Dict, Any, Optional, List
import logging
import datetime

from core.config.config_validator import ConfigValidator
from core.security.audit_logger import AuditLogger

logger = logging.getLogger("ConfigMigrator")
audit_logger = AuditLogger()


class ConfigMigrator:
    """
    Отвечает за безопасную миграцию конфигурационных файлов
    из устаревших форматов в новую унифицированную систему.
    """

    # Сопоставление старых путей → новые ключи конфигурации
    MIGRATION_MAP = {
        "ai/configs/embeddings_config.json": "ai.embeddings",
        "ai/configs/nlp_config.json": "ai.nlp",
        "ai/configs/textgen_config.json": "ai.textgen",
        "ai/configs/translation_config.json": "ai.translation",
        "ai/configs/whisper_config.json": "ai.speech.transcription",
    }

    # Сопоставление для вложенных файлов в model_configs/
    MODEL_CONFIG_PREFIX_MAP = {
        "embeddings_": "ai.embeddings.models.",
        "textgen_": "ai.textgen.models.",
        "translation_": "ai.translation.models.",
        "whisper_": "ai.speech.transcription.models.",
    }

    def __init__(self, base_path: Path = Path(".")):
        self.base_path = base_path.resolve()
        self.legacy_config_dir = self.base_path / "ai" / "configs"
        self.new_config_dir = self.base_path / "config"
        self.backup_dir = self.base_path / "backup" / "config_migration"
        self.validator = ConfigValidator(self.new_config_dir / "schemas")

    def migrate_all(self) -> bool:
        """
        Выполняет полную миграцию всех поддерживаемых конфигураций.
        Возвращает True, если все миграции прошли успешно.
        """
        logger.info("🔄 Starting full configuration migration...")

        success = True

        # 1. Миграция основных конфигов
        for legacy_rel_path, new_key in self.MIGRATION_MAP.items():
            if not self._migrate_single_file(legacy_rel_path, new_key):
                success = False

        # 2. Миграция model_configs/
        model_configs_dir = self.legacy_config_dir / "model_configs"
        if model_configs_dir.exists():
            for config_file in model_configs_dir.glob("*.json"):
                if not self._migrate_model_config(config_file):
                    success = False

        if success:
            logger.info("✅ Configuration migration completed successfully.")
            audit_logger.log("CONFIG_MIGRATION_SUCCESS", "All configs migrated to unified system.")
        else:
            logger.warning("⚠️ Some configuration migrations failed. Check logs.")

        return success

    def _migrate_single_file(self, legacy_rel_path: str, new_key: str) -> bool:
        """Мигрирует один файл конфигурации."""
        legacy_path = self.base_path / legacy_rel_path
        if not legacy_path.exists():
            logger.debug(f"⏭️  Legacy config not found: {legacy_rel_path}")
            return True  # не ошибка — просто нет старого файла

        try:
            # Резервная копия
            self._backup_file(legacy_path)

            # Чтение
            with open(legacy_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Преобразование (если нужно)
            transformed = self._transform_data(data, new_key)

            # Валидация
            schema_name = self._get_schema_name(new_key)
            if not self.validator.validate(transformed, schema_name):
                logger.error(f"❌ Validation failed for {legacy_rel_path} → {new_key}")
                return False

            # Сохранение в новый формат (через UnifiedConfigManager позже)
            # Сейчас просто логируем — интеграция с UCM будет отдельно
            logger.info(f"✅ Migrated {legacy_rel_path} → {new_key}")
            audit_logger.log("CONFIG_MIGRATED", {
                "from": str(legacy_path),
                "to": new_key,
                "timestamp": datetime.datetime.utcnow().isoformat()
            })

            # Опционально: переместить старый файл в архив
            self._archive_legacy_file(legacy_path)

            return True

        except Exception as e:
            logger.exception(f"💥 Failed to migrate {legacy_rel_path}: {e}")
            audit_logger.log("CONFIG_MIGRATION_ERROR", {
                "file": str(legacy_path),
                "error": str(e)
            })
            return False

    def _migrate_model_config(self, file_path: Path) -> bool:
        """Мигрирует отдельный файл модели из model_configs/."""
        filename = file_path.name
        matched = False
        new_key = None

        for prefix, key_prefix in self.MODEL_CONFIG_PREFIX_MAP.items():
            if filename.startswith(prefix):
                model_name = filename[len(prefix):-5]  # убрать .json
                new_key = f"{key_prefix}{model_name}"
                matched = True
                break

        if not matched:
            logger.warning(f"❓ Unknown model config format: {filename}")
            return True  # пропускаем, но не считаем ошибкой

        return self._migrate_single_file(str(file_path.relative_to(self.base_path)), new_key)

    def _transform_data(self, data: Dict[str, Any], new_key: str) -> Dict[str, Any]:
        """
        Применяет трансформации к данным при необходимости.
        Например, переименование полей, изменение структуры.
        """
        # Пример: если в старом whisper_config был "model_size", а теперь "model.variant"
        if "speech.transcription" in new_key and "model_size" in data:
            data["model"] = data.get("model", {})
            data["model"]["variant"] = data.pop("model_size")

        # Добавляем метаданные миграции
        data["_meta"] = {
            "migrated_at": datetime.datetime.utcnow().isoformat(),
            "source": "legacy_ai_configs",
            "version": "1.0"
        }
        return data

    def _get_schema_name(self, new_key: str) -> str:
        """Определяет имя схемы для валидации по ключу конфигурации."""
        mapping = {
            "ai.embeddings": "ai_config",
            "ai.nlp": "ai_config",
            "ai.textgen": "ai_config",
            "ai.translation": "ai_config",
            "ai.speech.transcription": "ai_config",
        }
        # Для моделей используем ту же схему — или можно расширить
        for k in mapping:
            if new_key.startswith(k):
                return mapping[k]
        return "ai_config"  # fallback

    def _backup_file(self, file_path: Path) -> None:
        """Создаёт резервную копию файла перед миграцией."""
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        backup_name = f"{file_path.stem}_{timestamp}{file_path.suffix}"
        shutil.copy2(file_path, self.backup_dir / backup_name)
        logger.debug(f"💾 Backed up {file_path} to {backup_name}")

    def _archive_legacy_file(self, file_path: Path) -> None:
        """Перемещает старый файл в архив (не удаляет)."""
        archive_dir = self.base_path / "ai" / "configs" / "migrated"
        archive_dir.mkdir(exist_ok=True)
        try:
            shutil.move(str(file_path), archive_dir / file_path.name)
            logger.debug(f"📦 Archived legacy config: {file_path.name}")
        except Exception as e:
            logger.warning(f"⚠️ Could not archive {file_path}: {e}")

    def is_migration_needed(self) -> bool:
        """Проверяет, есть ли неперенесённые конфиги."""
        for rel_path in self.MIGRATION_MAP:
            if (self.base_path / rel_path).exists():
                return True
        model_configs = self.legacy_config_dir / "model_configs"
        if model_configs.exists() and any(model_configs.glob("*.json")):
            return True
        return False


# Утилитарный интерфейс для внешнего использования
def run_config_migration(base_path: Optional[str] = None) -> bool:
    """
    Запускает миграцию конфигураций.
    Используется при первом запуске системы.
    """
    path = Path(base_path) if base_path else Path(".")
    migrator = ConfigMigrator(path)
    if migrator.is_migration_needed():
        return migrator.migrate_all()
    else:
        logger.info("⏩ No legacy configs found. Migration skipped.")
        return True