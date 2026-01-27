"""
Унифицированная система бэкапов с политикой хранения вместо ручного разделения на daily/weekly/monthly
"""
import asyncio
import json
import logging
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict
import zipfile
import os

logger = logging.getLogger(__name__)


@dataclass
class BackupPolicy:
    """Политика хранения бэкапов"""
    keep_daily: int = 7      # Количество ежедневных бэкапов
    keep_weekly: int = 4     # Количество еженедельных бэкапов
    keep_monthly: int = 12   # Количество ежемесячных бэкапов
    max_size_gb: float = 50.0  # Максимальный размер хранилища бэкапов
    compression_level: int = 6  # Уровень сжатия (1-9)


@dataclass
class BackupMetadata:
    """Метаданные бэкапа"""
    backup_id: str
    timestamp: str
    backup_type: str  # full, incremental, config_only
    size_bytes: int
    duration_seconds: float
    success: bool
    error: Optional[str] = None
    included_paths: List[str] = None
    excluded_paths: List[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class UnifiedBackupManager:
    """
    Единый менеджер бэкапов с автоматической ротацией и политикой хранения
    Заменяет ручную структуру backup/automatic/daily|weekly|monthly
    """

    def __init__(self, base_backup_dir: str = "backup", policy: Optional[BackupPolicy] = None):
        self.base_dir = Path(base_backup_dir)
        self.policy = policy or BackupPolicy()
        self.metadata_file = self.base_dir / "backup_metadata.json"
        self.backups_dir = self.base_dir / "archives"

        # Создание директорий
        self.backups_dir.mkdir(parents=True, exist_ok=True)

        # Загрузка существующих метаданных
        self.backup_history: List[BackupMetadata] = self._load_metadata()

        logger.info(f"Инициализирован менеджер бэкапов. Политика: {self.policy}")

    def _load_metadata(self) -> List[BackupMetadata]:
        """Загрузка истории бэкапов из метаданных"""
        if not self.metadata_file.exists():
            return []

        try:
            with open(self.metadata_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return [BackupMetadata(**item) for item in data]
        except Exception as e:
            logger.error(f"Ошибка загрузки метаданных бэкапов: {str(e)}")
            return []

    def _save_metadata(self):
        """Сохранение метаданных бэкапов"""
        try:
            with open(self.metadata_file, 'w', encoding='utf-8') as f:
                json.dump([bm.to_dict() for bm in self.backup_history], f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Ошибка сохранения метаданных бэкапов: {str(e)}")

    async def create_backup(self, backup_type: str = "full",
                          custom_paths: Optional[List[str]] = None) -> BackupMetadata:
        """
        Создание бэкапа с автоматической классификацией по типу (daily/weekly/monthly)
        """
        backup_id = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{backup_type[:3]}"
        start_time = datetime.now()

        logger.info(f"Начало создания бэкапа {backup_id} ({backup_type})")

        try:
            # Определение путей для бэкапа
            paths_to_backup = custom_paths or self._get_default_backup_paths()
            excluded_paths = self._get_excluded_paths()

            # Создание архива
            archive_path = await self._create_archive(
                backup_id=backup_id,
                paths=paths_to_backup,
                excluded=excluded_paths,
                backup_type=backup_type
            )

            duration = (datetime.now() - start_time).total_seconds()
            size_bytes = archive_path.stat().st_size if archive_path.exists() else 0

            # Создание метаданных
            metadata = BackupMetadata(
                backup_id=backup_id,
                timestamp=start_time.isoformat(),
                backup_type=backup_type,
                size_bytes=size_bytes,
                duration_seconds=duration,
                success=True,
                included_paths=paths_to_backup,
                excluded_paths=excluded_paths
            )

            # Добавление в историю и сохранение
            self.backup_history.append(metadata)
            self._save_metadata()

            # Очистка старых бэкапов согласно политике
            await self._rotate_backups()

            logger.info(f"Бэкап {backup_id} успешно создан. Размер: {size_bytes / 1024**2:.2f}MB, время: {duration:.2f}с")
            return metadata

        except Exception as e:
            duration = (datetime.now() - start_time).total_seconds()
            error_msg = str(e)

            metadata = BackupMetadata(
                backup_id=backup_id,
                timestamp=start_time.isoformat(),
                backup_type=backup_type,
                size_bytes=0,
                duration_seconds=duration,
                success=False,
                error=error_msg
            )

            self.backup_history.append(metadata)
            self._save_metadata()

            logger.error(f"Ошибка создания бэкапа {backup_id}: {error_msg}")
            raise

    def _get_default_backup_paths(self) -> List[str]:
        """Получение путей по умолчанию для бэкапа"""
        return [
            "data/jobs",
            "data/clients",
            "data/conversations",
            "data/finances",
            "data/projects",
            "config",
            "ai/configs"
        ]

    def _get_excluded_paths(self) -> List[str]:
        """Получение путей для исключения из бэкапа"""
        return [
            "ai/models",           # Слишком большие, восстанавливаются через загрузку
            "ai/temp",            # Временные файлы
            "data/cache",         # Кэш восстанавливается
            "backup",             # Сама директория бэкапов
            "__pycache__",
            "*.log",
            "*.tmp"
        ]

    async def _create_archive(self, backup_id: str, paths: List[str],
                            excluded: List[str], backup_type: str) -> Path:
        """Создание архива бэкапа"""
        archive_path = self.backups_dir / f"{backup_id}.zip"

        def _should_exclude(path: Path) -> bool:
            """Проверка, должен ли путь быть исключен"""
            path_str = str(path)
            for pattern in excluded:
                if pattern.startswith("*."):
                    if path_str.endswith(pattern[1:]):
                        return True
                elif pattern in path_str:
                    return True
            return False

        # Асинхронное создание архива в потоке
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._create_archive_sync, archive_path, paths, _should_exclude)

        return archive_path

    def _create_archive_sync(self, archive_path: Path, paths: List[str], exclude_func):
        """Синхронное создание архива (выполняется в потоке)"""
        with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            zipf.comment = f"AI Freelance Backup - {datetime.now().isoformat()}".encode('utf-8')

            for base_path in paths:
                base = Path(base_path)
                if not base.exists():
                    logger.warning(f"Путь для бэкапа не существует: {base_path}")
                    continue

                if base.is_file():
                    if not exclude_func(base):
                        zipf.write(base, arcname=base.name)
                else:
                    for root, dirs, files in os.walk(base):
                        # Фильтрация директорий
                        dirs[:] = [d for d in dirs if not exclude_func(Path(root) / d)]

                        for file in files:
                            file_path = Path(root) / file
                            if not exclude_func(file_path):
                                # Сохранение относительного пути от корня проекта
                                arcname = str(file_path.relative_to(Path.cwd()))
                                try:
                                    zipf.write(file_path, arcname=arcname)
                                except Exception as e:
                                    logger.warning(f"Ошибка добавления файла {file_path} в архив: {str(e)}")

    async def _rotate_backups(self):
        """Ротация бэкапов согласно политике хранения"""
        # Группировка бэкапов по типу
        successful_backups = [b for b in self.backup_history if b.success]
        successful_backups.sort(key=lambda b: b.timestamp, reverse=True)

        # Классификация бэкапов по периодичности
        now = datetime.now()
        daily_backups = []
        weekly_backups = []
        monthly_backups = []

        for backup in successful_backups:
            backup_time = datetime.fromisoformat(backup.timestamp)
            days_old = (now - backup_time).days

            if days_old <= 7:
                daily_backups.append(backup)
            elif days_old <= 30:
                weekly_backups.append(backup)
            else:
                monthly_backups.append(backup)

        # Определение бэкапов для удаления
        to_keep = set()

        # Ежедневные (последние N)
        to_keep.update(b.backup_id for b in daily_backups[:self.policy.keep_daily])

        # Еженедельные (каждый 7-й день из последних 30)
        weekly_candidates = sorted(weekly_backups, key=lambda b: b.timestamp, reverse=True)
        for i, backup in enumerate(weekly_candidates):
            if i % 7 == 0 and len(to_keep) < self.policy.keep_daily + self.policy.keep_weekly:
                to_keep.add(backup.backup_id)

        # Ежемесячные (первый бэкап каждого месяца)
        monthly_by_month = {}
        for backup in sorted(monthly_backups, key=lambda b: b.timestamp):
            month_key = backup.timestamp[:7]  # YYYY-MM
            if month_key not in monthly_by_month:
                monthly_by_month[month_key] = backup

        monthly_list = list(monthly_by_month.values())[-self.policy.keep_monthly:]
        to_keep.update(b.backup_id for b in monthly_list)

        # Удаление лишних бэкапов
        deleted = 0
        total_size_freed = 0

        for backup in successful_backups:
            if backup.backup_id not in to_keep:
                archive_path = self.backups_dir / f"{backup.backup_id}.zip"
                if archive_path.exists():
                    size = archive_path.stat().st_size
                    try:
                        archive_path.unlink()
                        total_size_freed += size
                        deleted += 1
                        logger.info(f"Удален старый бэкап: {backup.backup_id} ({size / 1024**2:.2f}MB)")
                    except Exception as e:
                        logger.warning(f"Ошибка удаления бэкапа {backup.backup_id}: {str(e)}")

        # Обновление истории (удаление метаданных удаленных бэкапов)
        self.backup_history = [b for b in self.backup_history if b.backup_id in to_keep or not b.success]
        self._save_metadata()

        logger.info(f"Ротация завершена: удалено {deleted} бэкапов, освобождено {total_size_freed / 1024**3:.2f}GB")

    async def restore_backup(self, backup_id: str, target_dir: Optional[str] = None) -> bool:
        """Восстановление из бэкапа"""
        archive_path = self.backups_dir / f"{backup_id}.zip"

        if not archive_path.exists():
            logger.error(f"Бэкап {backup_id} не найден")
            return False

        target = Path(target_dir) if target_dir else Path.cwd()

        try:
            logger.info(f"Начало восстановления из бэкапа {backup_id}")

            # Распаковка в потоке
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._restore_archive_sync, archive_path, target)

            logger.info(f"Восстановление из бэкапа {backup_id} успешно завершено")
            return True

        except Exception as e:
            logger.error(f"Ошибка восстановления из бэкапа {backup_id}: {str(e)}")
            return False

    def _restore_archive_sync(self, archive_path: Path, target_dir: Path):
        """Синхронное восстановление архива"""
        with zipfile.ZipFile(archive_path, 'r') as zipf:
            # Проверка на наличие опасных путей (защита от path traversal)
            for member in zipf.namelist():
                member_path = (target_dir / member).resolve()
                if not str(member_path).startswith(str(target_dir.resolve())):
                    raise Exception(f"Обнаружен опасный путь в архиве: {member}")

            zipf.extractall(target_dir)

    def get_backup_stats(self) -> Dict[str, Any]:
        """Получение статистики по бэкапам"""
        successful = [b for b in self.backup_history if b.success]
        failed = [b for b in self.backup_history if not b.success]

        total_size = sum(b.size_bytes for b in successful)

        # Группировка по типам
        types = {}
        for backup in successful:
            types[backup.backup_type] = types.get(backup.backup_type, 0) + 1

        return {
            "total_backups": len(self.backup_history),
            "successful_backups": len(successful),
            "failed_backups": len(failed),
            "total_size_bytes": total_size,
            "total_size_gb": total_size / 1024**3,
            "backup_types": types,
            "oldest_backup": successful[-1].timestamp if successful else None,
            "newest_backup": successful[0].timestamp if successful else None,
            "policy": asdict(self.policy)
        }

    async def cleanup_old_metadata(self, max_age_days: int = 90):
        """Очистка старых метаданных (без удаления самих бэкапов)"""
        cutoff = datetime.now() - timedelta(days=max_age_days)

        before_count = len(self.backup_history)
        self.backup_history = [
            b for b in self.backup_history
            if datetime.fromisoformat(b.timestamp) > cutoff or b.success
        ]
        after_count = len(self.backup_history)

        self._save_metadata()
        logger.info(f"Очистка метаданных: удалено {before_count - after_count} записей старше {max_age_days} дней")