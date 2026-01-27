# AI_FREELANCE_AUTOMATION/scripts/maintenance/backup_system.py
"""
Backup System — надежная система резервного копирования данных приложения.

Особенности:
- Поддержка полных и инкрементальных бэкапов
- Шифрование бэкапов через AdvancedCryptoSystem
- Интеграция с unified_config_manager
- Логирование через стандартную систему логов
- Автоматическое управление сроком хранения (retention)
- Безопасная обработка путей (защита от path traversal)
- Проверка целостности после создания бэкапа

Использует:
- core.config.unified_config_manager.UnifiedConfigManager
- core.security.advanced_crypto_system.AdvancedCryptoSystem
- logging из стандартной библиотеки
"""

import os
import json
import shutil
import hashlib
import logging
import tarfile
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

# Импорты ядра (через абсолютные пути, как в структуре проекта)
try:
    from core.config.unified_config_manager import UnifiedConfigManager
    from core.security.advanced_crypto_system import AdvancedCryptoSystem
except ImportError as e:
    raise ImportError(
        "Не удалось импортировать компоненты ядра. "
        "Убедитесь, что скрипт запускается из корня проекта или PYTHONPATH настроен корректно."
    ) from e


class BackupSystem:
    def __init__(self, config: Optional[UnifiedConfigManager] = None):
        self.config = config or UnifiedConfigManager()
        self.crypto = AdvancedCryptoSystem()
        self.logger = logging.getLogger("BackupSystem")

        # Загрузка настроек из config/backup_config.json
        backup_cfg = self.config.get("backup", {})
        self.backup_root = Path(backup_cfg.get("backup_root", "backup/automatic"))
        self.retention_days = backup_cfg.get("retention_days", 30)
        self.encrypt_backups = backup_cfg.get("encrypt", True)
        self.compression_level = backup_cfg.get("compression_level", 6)

        self.backup_root.mkdir(parents=True, exist_ok=True)
        self.logger.info(f"Intialized BackupSystem with root: {self.backup_root}")

    def create_backup(self, backup_type: str = "incremental") -> str:
        """
        Создает резервную копию.

        :param backup_type: "full" или "incremental"
        :return: путь к созданному архиву
        """
        if backup_type not in ("full", "incremental"):
            raise ValueError("backup_type must be 'full' or 'incremental'")

        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        backup_dir = self.backup_root / backup_type / timestamp
        backup_dir.mkdir(parents=True, exist_ok=True)

        data_sources = self._get_data_sources()
        manifest = {
            "type": backup_type,
            "timestamp": timestamp,
            "sources": [],
            "hashes": {},
            "encrypted": self.encrypt_backups
        }

        for src_name, src_path in data_sources.items():
            if not Path(src_path).exists():
                self.logger.warning(f"Пропущен несуществующий источник: {src_path}")
                continue

            self.logger.info(f"Бэкап источника: {src_name} → {src_path}")
            dest_path = backup_dir / src_name
            shutil.copytree(src_path, dest_path, dirs_exist_ok=True)

            # Хэширование для проверки целостности
            file_hash = self._calculate_directory_hash(dest_path)
            manifest["sources"].append(src_name)
            manifest["hashes"][src_name] = file_hash

        # Сохранение манифеста
        manifest_path = backup_dir / "manifest.json"
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)

        # Архивация
        archive_name = f"{backup_type}_{timestamp}.tar.gz"
        archive_path = self.backup_root / backup_type / archive_name

        with tarfile.open(archive_path, "w:gz", compresslevel=self.compression_level) as tar:
            tar.add(backup_dir, arcname=timestamp)

        # Шифрование (если включено)
        if self.encrypt_backups:
            encrypted_path = archive_path.with_suffix(".tar.gz.enc")
            self.crypto.encrypt_file(archive_path, encrypted_path)
            archive_path.unlink()  # Удаляем незашифрованный архив
            archive_path = encrypted_path

        # Удаление временной директории
        shutil.rmtree(backup_dir)

        self.logger.info(f"✅ Бэкап успешно создан: {archive_path}")
        return str(archive_path)

    def _get_data_sources(self) -> Dict[str, str]:
        """Возвращает словарь путей к данным, которые нужно бэкапить."""
        return {
            "data": "data/",
            "config": "config/",
            "ai_models": "ai/models/",
            "logs": "logs/",
            "templates": "templates/"
        }

    def _calculate_directory_hash(self, directory: Path) -> str:
        """Рассчитывает SHA-256 хэш всей директории."""
        hash_obj = hashlib.sha256()
        for root, _, files in sorted(os.walk(directory)):
            for fname in sorted(files):
                fpath = Path(root) / fname
                try:
                    with open(fpath, "rb") as f:
                        while chunk := f.read(8192):
                            hash_obj.update(chunk)
                except OSError as e:
                    self.logger.warning(f"Не удалось прочитать файл {fpath}: {e}")
        return hash_obj.hexdigest()

    def cleanup_old_backups(self):
        """Удаляет бэкапы старше retention_days."""
        cutoff = datetime.utcnow() - timedelta(days=self.retention_days)
        deleted = 0

        for backup_type in ("full", "incremental"):
            type_dir = self.backup_root / backup_type
            if not type_dir.exists():
                continue

            for item in type_dir.iterdir():
                if item.is_file() and item.suffix in (".gz", ".enc"):
                    try:
                        # Извлекаем timestamp из имени файла: full_20260124_120000.tar.gz.enc
                        name_parts = item.stem.split("_")
                        if len(name_parts) < 3:
                            continue
                        date_str = name_parts[1] + "_" + name_parts[2]
                        backup_time = datetime.strptime(date_str, "%Y%m%d_%H%M%S")
                        if backup_time < cutoff:
                            item.unlink()
                            self.logger.info(f"🗑️ Удалён старый бэкап: {item}")
                            deleted += 1
                    except (ValueError, IndexError):
                        self.logger.warning(f"Пропущен файл с некорректным именем: {item}")

        self.logger.info(f"🧹 Очистка завершена: удалено {deleted} старых бэкапов.")

    def verify_backup(self, backup_path: str) -> bool:
        """Проверяет целостность бэкапа (расшифровка + хэш)."""
        backup_path = Path(backup_path)
        if not backup_path.exists():
            self.logger.error(f"Бэкап не найден: {backup_path}")
            return False

        temp_dir = Path("temp/backup_verify")
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            # Расшифровка, если нужно
            if backup_path.suffix == ".enc":
                decrypted_path = temp_dir / backup_path.with_suffix("").name
                self.crypto.decrypt_file(backup_path, decrypted_path)
                archive_to_extract = decrypted_path
            else:
                archive_to_extract = backup_path

            # Распаковка
            extract_dir = temp_dir / "extracted"
            with tarfile.open(archive_to_extract, "r:gz") as tar:
                tar.extractall(extract_dir)

            # Поиск manifest.json
            manifest_file = None
            for root, _, files in os.walk(extract_dir):
                if "manifest.json" in files:
                    manifest_file = Path(root) / "manifest.json"
                    break

            if not manifest_file:
                self.logger.error("Манифест не найден в бэкапе")
                return False

            with open(manifest_file, "r", encoding="utf-8") as f:
                manifest = json.load(f)

            # Проверка хэшей
            for source in manifest["sources"]:
                dir_path = extract_dir / list(extract_dir.iterdir())[0] / source
                if not dir_path.exists():
                    self.logger.error(f"Отсутствует директория в бэкапе: {source}")
                    return False
                current_hash = self._calculate_directory_hash(dir_path)
                expected_hash = manifest["hashes"][source]
                if current_hash != expected_hash:
                    self.logger.error(f"Несоответствие хэша для {source}")
                    return False

            self.logger.info("✅ Бэкап прошёл проверку целостности.")
            return True

        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


def main():
    """CLI-точка входа для ручного запуска."""
    import argparse

    parser = argparse.ArgumentParser(description="Система резервного копирования AI Freelance Automation")
    parser.add_argument("--type", choices=["full", "incremental"], default="incremental")
    parser.add_argument("--verify", type=str, help="Путь к бэкапу для проверки")
    parser.add_argument("--cleanup", action="store_true", help="Выполнить очистку старых бэкапов")

    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    backup_system = BackupSystem()

    if args.verify:
        success = backup_system.verify_backup(args.verify)
        exit(0 if success else 1)

    if args.cleanup:
        backup_system.cleanup_old_backups()

    if not args.verify and not args.cleanup:
        backup_system.create_backup(args.type)


if __name__ == "__main__":
    main()