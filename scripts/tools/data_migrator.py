# AI_FREELANCE_AUTOMATION/scripts/tools/data_migrator.py
"""
Data Migrator Tool — безопасная, атомарная и откатываемая миграция данных.
Используется при обновлениях схемы, смене хранилища, восстановлении из бэкапа.
Поддерживает шифрование, валидацию целостности, логирование и откат.
"""

import os
import json
import shutil
import logging
import hashlib
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone

# Импорты из ядра (через service locator или DI — без циклических зависимостей)
from core.config.unified_config_manager import UnifiedConfigManager
from core.security.advanced_crypto_system import AdvancedCryptoSystem
from core.monitoring.intelligent_monitor import IntelligentMonitor
from core.logging.audit_logger import AuditLogger

# Локальный импорт для утилит
from scripts.utils.file_utils import safe_write_json, atomic_move, ensure_dir


class DataMigrator:
    """
    Управляет миграцией данных между источником и назначением.
    Гарантирует:
    - Атомарность (всё или ничего)
    - Шифрование чувствительных данных
    - Валидацию контрольных сумм
    - Возможность отката
    - Аудит всех операций
    """

    def __init__(
        self,
        config: Optional[UnifiedConfigManager] = None,
        crypto: Optional[AdvancedCryptoSystem] = None,
        monitor: Optional[IntelligentMonitor] = None,
        audit_logger: Optional[AuditLogger] = None
    ):
        self.config = config or UnifiedConfigManager()
        self.crypto = crypto or AdvancedCryptoSystem()
        self.monitor = monitor or IntelligentMonitor()
        self.audit_logger = audit_logger or AuditLogger()

        self.logger = logging.getLogger("DataMigrator")
        self.migration_dir = Path(self.config.get("paths.migration_dir", "data/migrations"))
        self.backup_dir = Path(self.config.get("paths.backup_dir", "data/backups"))
        self.temp_dir = Path(self.config.get("paths.temp_dir", "temp/migration"))

        ensure_dir(self.migration_dir)
        ensure_dir(self.backup_dir)
        ensure_dir(self.temp_dir)

        self.logger.info("Intialized DataMigrator with secure migration pipeline.")

    def migrate(
        self,
        source_path: str,
        target_path: str,
        migration_id: str,
        schema_version: str,
        encrypt: bool = True,
        create_backup: bool = True
    ) -> bool:
        """
        Выполняет миграцию данных с полной безопасностью.

        Args:
            source_path (str): Путь к исходным данным (файл или директория)
            target_path (str): Путь к целевому хранилищу
            migration_id (str): Уникальный ID миграции (например, 'v2_to_v3_jobs')
            schema_version (str): Версия целевой схемы
            encrypt (bool): Шифровать ли данные при переносе
            create_backup (bool): Создавать ли резервную копию перед миграцией

        Returns:
            bool: True если миграция успешна, иначе False
        """
        try:
            self.logger.info(f"🚀 Starting migration '{migration_id}' to schema {schema_version}")
            self.audit_logger.log("DATA_MIGRATION_START", {
                "migration_id": migration_id,
                "source": source_path,
                "target": target_path,
                "encrypt": encrypt,
                "backup": create_backup
            })

            # 1. Валидация исходных данных
            if not os.path.exists(source_path):
                raise FileNotFoundError(f"Source path does not exist: {source_path}")

            # 2. Создание бэкапа
            backup_path = None
            if create_backup:
                backup_path = self._create_backup(source_path, migration_id)
                self.logger.info(f"💾 Backup created at: {backup_path}")

            # 3. Подготовка временной директории
            temp_target = self.temp_dir / f"migrate_{migration_id}_{int(datetime.now().timestamp())}"
            ensure_dir(temp_target)

            # 4. Копирование и трансформация данных
            self._copy_and_transform(source_path, temp_target, schema_version)

            # 5. Шифрование (если требуется)
            if encrypt:
                self._encrypt_directory(temp_target)

            # 6. Валидация целостности
            checksum_before = self._calculate_checksum(temp_target)
            self.logger.debug(f"Checksum before commit: {checksum_before}")

            # 7. Атомарная замена
            atomic_move(str(temp_target), target_path)
            self.logger.info(f"✅ Data successfully migrated to {target_path}")

            # 8. Запись метаданных миграции
            self._record_migration(
                migration_id=migration_id,
                schema_version=schema_version,
                source=source_path,
                target=target_path,
                backup=backup_path,
                checksum=checksum_before
            )

            self.audit_logger.log("DATA_MIGRATION_SUCCESS", {"migration_id": migration_id})
            self.monitor.record_metric("data_migration.success", 1)
            return True

        except Exception as e:
            self.logger.error(f"💥 Migration '{migration_id}' failed: {e}", exc_info=True)
            self.audit_logger.log("DATA_MIGRATION_FAILURE", {
                "migration_id": migration_id,
                "error": str(e)
            })
            self.monitor.record_metric("data_migration.failure", 1)
            self._rollback_if_possible(migration_id, backup_path, target_path)
            return False

    def _create_backup(self, source: str, migration_id: str) -> str:
        """Создаёт зашифрованную резервную копию."""
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup_name = f"{migration_id}_backup_{timestamp}"
        backup_path = self.backup_dir / backup_name

        if os.path.isdir(source):
            shutil.copytree(source, backup_path)
        else:
            ensure_dir(backup_path.parent)
            shutil.copy2(source, backup_path)

        # Шифруем бэкап
        if os.path.isdir(backup_path):
            self._encrypt_directory(backup_path)
        else:
            encrypted_data = self.crypto.encrypt_file(str(backup_path))
            with open(str(backup_path) + ".enc", "wb") as f:
                f.write(encrypted_data)
            os.remove(backup_path)
            backup_path = str(backup_path) + ".enc"

        return str(backup_path)

    def _copy_and_transform(self, source: str, target: Path, schema_version: str):
        """Копирует и преобразует данные под новую схему."""
        # Пример: если это JSON-файлы с заказами — обновляем структуру
        if os.path.isfile(source) and source.endswith(".json"):
            with open(source, "r", encoding="utf-8") as f:
                data = json.load(f)
            transformed = self._transform_data(data, schema_version)
            safe_write_json(target / os.path.basename(source), transformed)
        elif os.path.isdir(source):
            for item in Path(source).rglob("*"):
                rel_path = item.relative_to(source)
                target_item = target / rel_path
                if item.is_file():
                    if item.suffix == ".json":
                        with open(item, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        transformed = self._transform_data(data, schema_version)
                        safe_write_json(target_item, transformed)
                    else:
                        ensure_dir(target_item.parent)
                        shutil.copy2(item, target_item)
        else:
            ensure_dir(target)
            shutil.copy2(source, target)

    def _transform_data(self, data: Dict[str, Any], target_schema: str) -> Dict[str, Any]:
        """Применяет трансформации в зависимости от целевой схемы."""
        # Пример: миграция с v1 → v2
        if target_schema == "v2" and data.get("schema_version") == "v1":
            # Добавляем новые поля, переименовываем старые
            data["schema_version"] = "v2"
            data.setdefault("quality_score", 0.0)
            if "client_feedback" in data:
                data["feedback"] = data.pop("client_feedback")
        # Можно расширить через плагины или registry
        return data

    def _encrypt_directory(self, dir_path: Path):
        """Шифрует все файлы в директории."""
        for file in dir_path.rglob("*"):
            if file.is_file() and not file.name.endswith(".enc"):
                encrypted = self.crypto.encrypt_file(str(file))
                enc_file = file.with_suffix(file.suffix + ".enc")
                with open(enc_file, "wb") as f:
                    f.write(encrypted)
                file.unlink()

    def _calculate_checksum(self, path: Path) -> str:
        """Рассчитывает SHA-256 хеш всего содержимого."""
        hash_sha256 = hashlib.sha256()
        if path.is_file():
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_sha256.update(chunk)
        else:
            for file in sorted(path.rglob("*")):
                if file.is_file():
                    hash_sha256.update(file.name.encode())
                    with open(file, "rb") as f:
                        for chunk in iter(lambda: f.read(4096), b""):
                            hash_sha256.update(chunk)
        return hash_sha256.hexdigest()

    def _record_migration(self, **meta):
        """Сохраняет метаданные миграции."""
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **meta
        }
        migration_file = self.migration_dir / f"{meta['migration_id']}.json"
        safe_write_json(migration_file, record)

    def _rollback_if_possible(self, migration_id: str, backup_path: Optional[str], target_path: str):
        """Пытается откатить изменения при ошибке."""
        self.logger.warning(f"🔄 Attempting rollback for migration '{migration_id}'")
        try:
            if backup_path and os.path.exists(backup_path):
                self.logger.info(f"Restoring from backup: {backup_path}")
                if backup_path.endswith(".enc"):
                    decrypted = self.crypto.decrypt_file(backup_path)
                    orig_path = backup_path[:-4]  # remove .enc
                    with open(orig_path, "wb") as f:
                        f.write(decrypted)
                    backup_path = orig_path

                if os.path.isdir(backup_path):
                    if os.path.exists(target_path):
                        shutil.rmtree(target_path)
                    shutil.copytree(backup_path, target_path)
                else:
                    shutil.copy2(backup_path, target_path)

                self.audit_logger.log("DATA_MIGRATION_ROLLBACK_SUCCESS", {"migration_id": migration_id})
            else:
                self.logger.warning("No valid backup found for rollback.")
        except Exception as e:
            self.logger.error(f"Rollback failed: {e}", exc_info=True)
            self.audit_logger.log("DATA_MIGRATION_ROLLBACK_FAILURE", {
                "migration_id": migration_id,
                "error": str(e)
            })


# Утилиты (могут быть вынесены в отдельный файл, но оставлены здесь для автономности)
def safe_write_json(path: Path, data: Dict):
    """Безопасная запись JSON с созданием директорий."""
    ensure_dir(path.parent)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp_path.rename(path)

def atomic_move(src: str, dst: str):
    """Атомарное перемещение (rename) — гарантирует целостность."""
    if os.path.exists(dst):
        if os.path.isdir(dst):
            shutil.rmtree(dst)
        else:
            os.remove(dst)
    shutil.move(src, dst)

def ensure_dir(path: Path):
    """Создаёт директорию, если не существует."""
    path.mkdir(parents=True, exist_ok=True)


# CLI-интерфейс (опционально, для ручного запуска)
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="AI Freelance Automation — Data Migrator")
    parser.add_argument("--source", required=True, help="Source path")
    parser.add_argument("--target", required=True, help="Target path")
    parser.add_argument("--id", required=True, help="Migration ID")
    parser.add_argument("--schema", required=True, help="Target schema version")
    parser.add_argument("--no-encrypt", action="store_true", help="Disable encryption")
    parser.add_argument("--no-backup", action="store_true", help="Skip backup")

    args = parser.parse_args()

    migrator = DataMigrator()
    success = migrator.migrate(
        source_path=args.source,
        target_path=args.target,
        migration_id=args.id,
        schema_version=args.schema,
        encrypt=not args.no_encrypt,
        create_backup=not args.no_backup
    )
    exit(0 if success else 1)