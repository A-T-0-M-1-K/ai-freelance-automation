import os
import json
import shutil
import tarfile
import hashlib
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from enum import Enum
import boto3  # Для интеграции с S3/Yandex Object Storage
from core.security.encryption_engine import EncryptionEngine


class BackupType(Enum):
    FULL = "full"
    INCREMENTAL = "incremental"
    DIFFERENTIAL = "differential"


class BackupRetentionPolicy:
    """
    Политика хранения резервных копий с автоматической ротацией.
    """

    def __init__(self, config_path: str = "backup/backup_config.json"):
        self.config_path = Path(config_path)
        self.config = self._load_config()

    def _load_config(self) -> Dict:
        default_config = {
            "retention": {
                "daily": {"count": 7, "keep_for_days": 7},
                "weekly": {"count": 4, "keep_for_days": 28},
                "monthly": {"count": 12, "keep_for_days": 365},
                "yearly": {"count": 5, "keep_for_days": 1825}
            },
            "compression": {
                "enabled": True,
                "algorithm": "gzip",  # gzip, bzip2, xz
                "level": 6  # 1-9 для gzip
            },
            "encryption": {
                "enabled": True,
                "algorithm": "AES-256-GCM"
            },
            "cloud_sync": {
                "enabled": False,
                "provider": "yandex",  # yandex, aws, google
                "bucket": "ai-freelance-backups",
                "region": "ru-central1",
                "sync_after_backup": True
            },
            "verification": {
                "enabled": True,
                "verify_checksum": True,
                "test_restore": False  # Тестовое восстановление (ресурсоёмко)
            }
        }

        if self.config_path.exists():
            with open(self.config_path) as f:
                user_config = json.load(f)
                # Мержим с дефолтной конфигурацией
                self._deep_merge(default_config, user_config)

        return default_config

    def _deep_merge(self, base: Dict, update: Dict):
        """Рекурсивное слияние словарей"""
        for key, value in update.items():
            if isinstance(value, dict) and key in base and isinstance(base[key], dict):
                self._deep_merge(base[key], value)
            else:
                base[key] = value

    def get_backup_schedule(self) -> Dict[str, List[str]]:
        """
        Получение расписания бэкапов на основе политик.
        """
        schedule_path = Path("backup/backup_schedule.json")
        default_schedule = {
            "daily": ["02:00"],
            "weekly": ["sunday 03:00"],
            "monthly": ["1st 04:00"],
            "yearly": ["january-1st 05:00"]
        }

        if schedule_path.exists():
            with open(schedule_path) as f:
                return json.load(f)

        return default_schedule

    def should_create_backup(self, backup_type: str, last_backup_time: Optional[datetime]) -> bool:
        """
        Определение необходимости создания бэкапа заданного типа.
        """
        now = datetime.utcnow()
        policy = self.config["retention"][backup_type]

        if last_backup_time is None:
            return True

        # Проверка по времени
        if backup_type == "daily":
            return (now - last_backup_time).days >= 1
        elif backup_type == "weekly":
            return (now - last_backup_time).days >= 7
        elif backup_type == "monthly":
            return (now.year > last_backup_time.year or
                    (now.year == last_backup_time.year and now.month > last_backup_time.month))
        elif backup_type == "yearly":
            return now.year > last_backup_time.year

        return False

    def cleanup_old_backups(self, backup_type: str):
        """
        Автоматическая очистка старых бэкапов согласно политике хранения.
        """
        backup_dir = Path(f"backup/automatic/{backup_type}")
        if not backup_dir.exists():
            return

        # Получение списка бэкапов
        backups = sorted(
            [p for p in backup_dir.iterdir() if p.is_dir() or p.suffix in ('.tar', '.tar.gz', '.tar.bz2', '.tar.xz')],
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )

        policy = self.config["retention"][backup_type]
        max_count = policy["count"]

        # Удаление лишних бэкапов
        to_delete = backups[max_count:]
        deleted = 0

        for backup in to_delete:
            try:
                if backup.is_dir():
                    shutil.rmtree(backup)
                else:
                    backup.unlink()
                deleted += 1
                print(f"🗑️  Удалён старый {backup_type} бэкап: {backup.name}")
            except Exception as e:
                print(f"⚠️  Ошибка удаления {backup}: {e}")

        if deleted > 0:
            print(f"✅ Очищено {deleted} старых {backup_type} бэкапов")


class UnifiedBackupManager:
    """
    Единый менеджер резервного копирования для всех типов бэкапов.
    Обеспечивает:
    - Единый интерфейс для полных/инкрементальных бэкапов
    - Шифрование данных
    - Сжатие
    - Верификацию целостности
    - Синхронизацию с облаком
    """

    def __init__(self, config_path: str = "backup/backup_config.json"):
        self.policy = BackupRetentionPolicy(config_path)
        self.encryption_engine = EncryptionEngine() if self.policy.config["encryption"]["enabled"] else None
        self.backup_root = Path("backup/automatic")
        self.manual_root = Path("backup/manual")
        self.metadata_root = Path("data/backup_metadata")
        self.metadata_root.mkdir(parents=True, exist_ok=True)

    def create_backup(self, backup_type: BackupType, name: Optional[str] = None) -> Dict:
        """
        Создание резервной копии заданного типа.

        :param backup_type: Тип бэкапа (полный/инкрементальный)
        :param name: Кастомное имя (для ручных бэкапов)
        :return: Метаданные бэкапа
        """
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        backup_name = name or f"{backup_type.value}_{timestamp}"

        # Определение директории назначения
        if name:  # Ручной бэкап
            backup_dir = self.manual_root / backup_name
        else:  # Автоматический бэкап
            backup_dir = self.backup_root / backup_type.value / backup_name

        backup_dir.mkdir(parents=True, exist_ok=True)

        print(f"💾 Создание {backup_type.value} бэкапа: {backup_name}")

        # Метаданные бэкапа
        metadata = {
            "backup_id": hashlib.sha256(f"{backup_name}_{timestamp}".encode()).hexdigest()[:16],
            "name": backup_name,
            "type": backup_type.value,
            "created_at": datetime.utcnow().isoformat(),
            "version": "2.0",
            "encrypted": bool(self.encryption_engine),
            "compression": self.policy.config["compression"]["enabled"],
            "sources": [],
            "checksums": {},
            "size_bytes": 0
        }

        total_size = 0

        # 1. Бэкап базы данных
        db_backup_path = self._backup_database(backup_dir)
        if db_backup_path:
            metadata["sources"].append("database")
            metadata["checksums"]["database"] = self._calculate_checksum(db_backup_path)
            total_size += db_backup_path.stat().st_size

        # 2. Бэкап данных приложения
        data_backup_path = self._backup_application_data(backup_dir)
        if data_backup_path:
            metadata["sources"].append("application_data")
            metadata["checksums"]["application_data"] = self._calculate_checksum(data_backup_path)
            total_size += data_backup_path.stat().st_size

        # 3. Бэкап конфигураций
        config_backup_path = self._backup_configurations(backup_dir)
        if config_backup_path:
            metadata["sources"].append("configurations")
            metadata["checksums"]["configurations"] = self._calculate_checksum(config_backup_path)
            total_size += config_backup_path.stat().st_size

        # 4. Бэкап моделей ИИ (опционально — из-за большого размера)
        if backup_type == BackupType.FULL:
            models_backup_path = self._backup_ai_models(backup_dir)
            if models_backup_path:
                metadata["sources"].append("ai_models")
                metadata["checksums"]["ai_models"] = self._calculate_checksum(models_backup_path)
                total_size += models_backup_path.stat().st_size

        metadata["size_bytes"] = total_size
        metadata["size_human"] = self._human_size(total_size)

        # Шифрование бэкапа (если включено)
        if self.encryption_engine:
            print(" 🔒 Шифрование бэкапа...")
            encrypted_path = self._encrypt_backup_directory(backup_dir)
            metadata["encrypted_path"] = str(encrypted_path)

        # Создание архива
        if self.policy.config["compression"]["enabled"]:
            print(" 📦 Сжатие бэкапа...")
            archive_path = self._create_compressed_archive(backup_dir, backup_name)
            metadata["archive_path"] = str(archive_path)
            metadata["checksums"]["archive"] = self._calculate_checksum(archive_path)

        # Верификация целостности
        if self.policy.config["verification"]["enabled"]:
            print(" ✅ Верификация целостности...")
            self._verify_backup_integrity(metadata, backup_dir)

        # Сохранение метаданных
        metadata_path = backup_dir / "backup_metadata.json"
        with open(metadata_path, 'w') as f:
            json.dump(metadata, f, indent=2)

        # Синхронизация с облаком
        if self.policy.config["cloud_sync"]["enabled"]:
            print(" ☁️  Синхронизация с облаком...")
            self._sync_to_cloud(backup_dir, metadata)

        # Очистка старых бэкапов
        if not name:  # Только для автоматических бэкапов
            self.policy.cleanup_old_backups(backup_type.value)

        print(f"✅ Бэкап успешно создан: {backup_dir}")
        print(f"📊 Размер: {metadata['size_human']}")

        return metadata

    def _backup_database(self, backup_dir: Path) -> Optional[Path]:
        """Резервное копирование базы данных"""
        try:
            # Использование pg_dump или аналога для вашей БД
            import subprocess

            db_dump_path = backup_dir / "database_dump.sql"

            # Получение параметров подключения из конфигурации
            db_config = json.loads(Path("config/database.json").read_text())
            conn_str = f"postgresql://{db_config['user']}:{db_config['password']}@{db_config['host']}:{db_config['port']}/{db_config['name']}"

            subprocess.run([
                "pg_dump",
                "--format=custom",
                f"--file={db_dump_path}",
                conn_str
            ], check=True, capture_output=True)

            print("   💾 База данных сохранена")
            return db_dump_path

        except Exception as e:
            print(f"   ⚠️  Ошибка бэкапа БД: {e}")
            return None

    def _backup_application_data(self, backup_dir: Path) -> Path:
        """Резервное копирование данных приложения (клиенты, заказы, финансы)"""
        data_sources = [
            ("clients", "data/clients"),
            ("jobs", "data/jobs"),
            ("finances", "data/finances"),
            ("projects", "data/projects"),
            ("conversations", "data/conversations"),
            ("stats", "data/stats"),
            ("settings", "data/settings")
        ]

        data_backup_dir = backup_dir / "application_data"
        data_backup_dir.mkdir(exist_ok=True)

        for name, source in data_sources:
            source_path = Path(source)
            if source_path.exists():
                dest_path = data_backup_dir / name
                if source_path.is_dir():
                    shutil.copytree(source_path, dest_path, dirs_exist_ok=True)
                else:
                    shutil.copy2(source_path, dest_path)

        print("   💾 Данные приложения сохранены")
        return data_backup_dir

    def _backup_configurations(self, backup_dir: Path) -> Path:
        """Резервное копирование конфигураций"""
        config_sources = [
            "config",
            "ai/configs",
            ".env",  # Если используется
            "backup/backup_config.json",
            "backup/backup_schedule.json"
        ]

        config_backup_dir = backup_dir / "configurations"
        config_backup_dir.mkdir(exist_ok=True)

        for source in config_sources:
            source_path = Path(source)
            if source_path.exists():
                if source_path.is_dir():
                    shutil.copytree(source_path, config_backup_dir / source_path.name, dirs_exist_ok=True)
                else:
                    shutil.copy2(source_path, config_backup_dir)

        print("   ⚙️  Конфигурации сохранены")
        return config_backup_dir

    def _backup_ai_models(self, backup_dir: Path) -> Optional[Path]:
        """Резервное копирование моделей ИИ (только для полных бэкапов)"""
        models_path = Path("ai/models")
        if not models_path.exists():
            return None

        models_backup_dir = backup_dir / "ai_models"
        models_backup_dir.mkdir(exist_ok=True)

        # Копирование только метаданных и конфигов (сами модели могут быть очень большими)
        # Для полных моделей лучше использовать внешнее хранилище или символические ссылки
        for model_dir in models_path.iterdir():
            if model_dir.is_dir():
                # Копирование конфигурации модели
                for file in model_dir.glob("*config.json"):
                    shutil.copy2(file, models_backup_dir / f"{model_dir.name}_{file.name}")
                # Копирование токенизатора
                for file in model_dir.glob("*tokenizer*"):
                    if file.is_file():
                        shutil.copy2(file, models_backup_dir / f"{model_dir.name}_{file.name}")

        print("   🤖 Метаданные моделей ИИ сохранены")
        return models_backup_dir

    def _encrypt_backup_directory(self, backup_dir: Path) -> Path:
        """Шифрование директории бэкапа"""
        if not self.encryption_engine:
            return backup_dir

        encrypted_dir = backup_dir.with_suffix(".encrypted")

        for file_path in backup_dir.rglob("*"):
            if file_path.is_file():
                relative_path = file_path.relative_to(backup_dir)
                encrypted_path = encrypted_dir / relative_path
                encrypted_path.parent.mkdir(parents=True, exist_ok=True)

                with open(file_path, 'rb') as f:
                    data = f.read()

                encrypted_data = self.encryption_engine.encrypt(data)

                with open(encrypted_path, 'wb') as f:
                    f.write(encrypted_data)

        # Удаление нешифрованной версии после успешного шифрования
        shutil.rmtree(backup_dir)

        return encrypted_dir

    def _create_compressed_archive(self, source_dir: Path, archive_name: str) -> Path:
        """Создание сжатого архива из директории бэкапа"""
        compression = self.policy.config["compression"]
        archive_path = source_dir.with_suffix(f".tar.{compression['algorithm'][-2:]}")

        mode = 'w:gz' if compression['algorithm'] == 'gzip' else \
            'w:bz2' if compression['algorithm'] == 'bzip2' else \
                'w:xz'

        with tarfile.open(archive_path, mode, compresslevel=compression.get('level', 6)) as tar:
            tar.add(source_dir, arcname=archive_name)

        # Удаление исходной директории после архивации
        if source_dir.exists() and source_dir.is_dir():
            shutil.rmtree(source_dir)

        return archive_path

    def _calculate_checksum(self, path: Path) -> str:
        """Расчёт контрольной суммы файла"""
        hash_sha256 = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_sha256.update(chunk)
        return hash_sha256.hexdigest()

    def _verify_backup_integrity(self, metadata: Dict, backup_dir: Path):
        """Верификация целостности бэкапа"""
        for source, expected_checksum in metadata["checksums"].items():
            if source == "archive":
                path = Path(metadata["archive_path"])
            else:
                path = backup_dir / f"{source}_dump.sql" if source == "database" else backup_dir / source

            if path.exists():
                actual_checksum = self._calculate_checksum(path)
                if actual_checksum != expected_checksum:
                    raise ValueError(
                        f"Нарушена целостность бэкапа для {source}: {actual_checksum} != {expected_checksum}")

        print("   ✅ Целостность бэкапа подтверждена")

    def _sync_to_cloud(self, backup_dir: Path, metadata: Dict):
        """Синхронизация бэкапа с облачным хранилищем"""
        cloud_config = self.policy.config["cloud_sync"]

        if cloud_config["provider"] == "yandex":
            session = boto3.session.Session()
            s3 = session.client(
                service_name='s3',
                endpoint_url='https://storage.yandexcloud.net',
                aws_access_key_id=os.environ.get('YC_ACCESS_KEY_ID'),
                aws_secret_access_key=os.environ.get('YC_SECRET_ACCESS_KEY'),
                region_name=cloud_config["region"]
            )

            # Загрузка архива
            archive_path = Path(metadata["archive_path"])
            s3_key = f"backups/{metadata['type']}/{archive_path.name}"

            s3.upload_file(
                Filename=str(archive_path),
                Bucket=cloud_config["bucket"],
                Key=s3_key,
                ExtraArgs={
                    'Metadata': {
                        'backup-id': metadata['backup_id'],
                        'created-at': metadata['created_at'],
                        'size-bytes': str(metadata['size_bytes'])
                    }
                }
            )

            print(f"   ☁️  Бэкап загружен в Yandex Object Storage: {s3_key}")

        # Добавить поддержку других провайдеров по необходимости

    def _human_size(self, size_bytes: int) -> str:
        """Конвертация байтов в человекочитаемый формат"""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.2f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.2f} PB"

    def restore_backup(self, backup_id: str, target_dir: Optional[str] = None):
        """
        Восстановление системы из бэкапа.
        """
        print(f"🔄 Восстановление из бэкапа: {backup_id}")
        # Реализация восстановления (симметричная процессу бэкапа)
        # 1. Поиск бэкапа по ID
        # 2. Распаковка архива
        # 3. Расшифровка (если зашифрован)
        # 4. Восстановление БД
        # 5. Восстановление файлов
        # 6. Верификация
        raise NotImplementedError("Реализация восстановления будет добавлена в следующей итерации")

    def list_backups(self, backup_type: Optional[str] = None) -> List[Dict]:
        """
        Список доступных бэкапов.
        """
        backups = []

        for bt in ["daily", "weekly", "monthly", "yearly", "manual"]:
            if backup_type and bt != backup_type:
                continue

            dir_path = self.backup_root / bt if bt != "manual" else self.manual_root
            if not dir_path.exists():
                continue

            for backup_item in dir_path.iterdir():
                metadata_path = backup_item / "backup_metadata.json" if backup_item.is_dir() else None
                if not metadata_path or not metadata_path.exists():
                    # Поиск метаданных в архиве или рядом с ним
                    metadata_path = backup_item.parent / f"{backup_item.stem}_metadata.json"

                if metadata_path and metadata_path.exists():
                    with open(metadata_path) as f:
                        metadata = json.load(f)
                        metadata["location"] = str(backup_item)
                        backups.append(metadata)

        return sorted(backups, key=lambda x: x["created_at"], reverse=True)


# CLI-интерфейс
def backup_cli():
    import argparse

    parser = argparse.ArgumentParser(description="Унифицированный менеджер резервного копирования")
    parser.add_argument("action", choices=["create", "list", "restore", "cleanup"], help="Действие")
    parser.add_argument("--type", choices=["full", "incremental"], default="full", help="Тип бэкапа")
    parser.add_argument("--name", help="Имя для ручного бэкапа")
    parser.add_argument("--backup-id", help="ID бэкапа для восстановления")
    parser.add_argument("--target-dir", help="Директория для восстановления")

    args = parser.parse_args()
    manager = UnifiedBackupManager()

    if args.action == "create":
        backup_type = BackupType.FULL if args.type == "full" else BackupType.INCREMENTAL
        manager.create_backup(backup_type, args.name)

    elif args.action == "list":
        backups = manager.list_backups()
        for b in backups:
            print(f"{b['created_at'][:10]} | {b['type']:10} | {b['size_human']:10} | {b['name']}")

    elif args.action == "restore":
        if not args.backup_id:
            raise ValueError("--backup-id обязателен для восстановления")
        manager.restore_backup(args.backup_id, args.target_dir)

    elif args.action == "cleanup":
        for bt in ["daily", "weekly", "monthly"]:
            manager.policy.cleanup_old_backups(bt)


if __name__ == "__main__":
    backup_cli()