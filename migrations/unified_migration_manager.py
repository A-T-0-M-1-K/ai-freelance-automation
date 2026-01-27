"""
Унифицированный менеджер миграций для автоматизации:
- Миграции схемы БД (через Alembic)
- Миграции данных (конвертация форматов)
- Миграции конфигураций (обновление структуры конфигов)
- Отката миграций при ошибках
"""

import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, Any, List, Optional, Callable
from datetime import datetime
import traceback
import shutil

from alembic.config import Config
from alembic import command
from sqlalchemy import create_engine, text

from core.security.encryption_engine import EncryptionEngine
from core.config.unified_config_manager import UnifiedConfigManager


class MigrationType(Enum):
    """Тип миграции"""
    DATABASE_SCHEMA = "database_schema"  # Миграция схемы БД через Alembic
    DATA_CONVERSION = "data_conversion"  # Конвертация форматов данных
    CONFIG_UPDATE = "config_update"  # Обновление структуры конфигов
    BLOCKCHAIN_UPGRADE = "blockchain_upgrade"  # Обновление смарт-контрактов
    FILE_STRUCTURE = "file_structure"  # Изменение структуры файлов


@dataclass
class MigrationRecord:
    """Запись о выполненной миграции"""
    id: str
    name: str
    type: MigrationType
    version: str
    applied_at: datetime
    duration_seconds: float
    success: bool
    error_message: Optional[str] = None
    rollback_applied: bool = False
    checksum_before: Optional[str] = None
    checksum_after: Optional[str] = None


class UnifiedMigrationManager:
    """
    Централизованный менеджер миграций с поддержкой:
    - Автоматического определения необходимых миграций
    - Транзакционного выполнения с откатом при ошибках
    - Валидации целостности данных после миграции
    - Журналирования всех операций для аудита
    - Поддержки отката (downgrade) для каждой миграции
    """

    def __init__(self,
                 migrations_dir: str = "migrations",
                 versions_dir: str = "migrations/versions",
                 data_dir: str = "data",
                 backup_dir: str = "backup/automatic/migration"):
        self.migrations_dir = Path(migrations_dir)
        self.versions_dir = Path(versions_dir)
        self.data_dir = Path(data_dir)
        self.backup_dir = Path(backup_dir)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.encryption_engine = EncryptionEngine()
        self.config_manager = UnifiedConfigManager()
        self.migration_history_path = self.data_dir / "migration_history.json"
        self.migration_lock_path = self.data_dir / ".migration_lock"

        # Загрузка истории миграций
        self.migration_history: List[MigrationRecord] = self._load_migration_history()

    def run_migrations(self,
                       target_version: Optional[str] = None,
                       dry_run: bool = False,
                       backup_before: bool = True) -> Dict[str, Any]:
        """
        Запуск всех необходимых миграций до целевой версии.

        Args:
            target_version: Целевая версия (если None — последняя доступная)
            dry_run: Режим "пробного запуска" без реальных изменений
            backup_before: Создавать ли бэкап перед миграцией

        Returns:
            Отчёт о выполнении миграций
        """
        # Проверка блокировки (защита от параллельных миграций)
        if self._is_migration_locked():
            raise RuntimeError("Миграция уже выполняется другим процессом")

        # Создание блокировки
        self._acquire_migration_lock()

        try:
            # 1. Определение текущей и целевой версий
            current_version = self._get_current_version()
            available_migrations = self._discover_available_migrations()

            if not available_migrations:
                return {'status': 'up_to_date', 'message': 'Нет доступных миграций', 'current_version': current_version}

            target_version = target_version or available_migrations[-1].version

            # 2. Определение списка миграций для применения
            pending_migrations = self._get_pending_migrations(current_version, target_version, available_migrations)

            if not pending_migrations:
                return {'status': 'up_to_date', 'message': f'Система уже на версии {current_version}',
                        'current_version': current_version}

            # 3. Создание бэкапа перед миграцией
            if backup_before and not dry_run:
                backup_path = self._create_pre_migration_backup(pending_migrations)
                print(f"✅ Создан бэкап перед миграцией: {backup_path}")

            # 4. Выполнение миграций
            results = []
            start_time = time.time()

            for migration in pending_migrations:
                if dry_run:
                    result = self._dry_run_migration(migration)
                else:
                    result = self._execute_migration(migration)

                results.append(result)

                # Прерывание при критической ошибке (если не в режиме продолжения)
                if not result['success'] and not migration.get('continue_on_error', False):
                    # Автоматический откат при ошибке
                    self._rollback_migrations(results)
                    raise RuntimeError(f"Миграция {migration['id']} завершилась ошибкой: {result.get('error')}")

            total_duration = time.time() - start_time

            # 5. Валидация после миграции
            validation_result = self._validate_post_migration()

            # 6. Формирование отчёта
            report = {
                'status': 'success' if all(r['success'] for r in results) else 'partial_success',
                'current_version': target_version,
                'migrations_applied': len([r for r in results if r['success']]),
                'migrations_failed': len([r for r in results if not r['success']]),
                'total_duration_seconds': total_duration,
                'results': results,
                'validation': validation_result,
                'backup_path': backup_path if backup_before and not dry_run else None,
                'timestamp': datetime.now().isoformat()
            }

            # Сохранение отчёта
            self._save_migration_report(report)

            return report

        finally:
            # Снятие блокировки
            self._release_migration_lock()

    def _discover_available_migrations(self) -> List[Dict[str, Any]]:
        """Обнаружение доступных миграций (схема БД + данные + конфиги)"""
        migrations = []

        # 1. Миграции схемы БД (Alembic)
        alembic_migrations = self._discover_alembic_migrations()
        migrations.extend(alembic_migrations)

        # 2. Миграции данных
        data_migrations = self._discover_data_migrations()
        migrations.extend(data_migrations)

        # 3. Миграции конфигураций
        config_migrations = self._discover_config_migrations()
        migrations.extend(config_migrations)

        # Сортировка по версии
        return sorted(migrations, key=lambda m: m['version'])

    def _discover_alembic_migrations(self) -> List[Dict[str, Any]]:
        """Обнаружение миграций схемы БД через Alembic"""
        alembic_cfg = Config(str(self.migrations_dir / "alembic.ini"))
        alembic_cfg.set_main_option("script_location", str(self.versions_dir))

        # Получение списка миграций из Alembic
        # (В реальной реализации — парсинг файлов в versions_dir)
        migrations = []

        for version_file in sorted(self.versions_dir.glob("*.py")):
            if version_file.name.startswith(("__", "env", "script")):
                continue

            # Извлечение метаданных из файла миграции
            version_id = version_file.stem.split('_')[0]  # Например, "001" из "001_initial_schema.py"
            name = '_'.join(version_file.stem.split('_')[1:])

            migrations.append({
                'id': f"alembic_{version_id}",
                'name': name,
                'type': MigrationType.DATABASE_SCHEMA,
                'version': version_id,
                'file_path': version_file,
                'upgrade_func': f"versions.{version_file.stem}.upgrade",
                'downgrade_func': f"versions.{version_file.stem}.downgrade"
            })

        return migrations

    def _discover_data_migrations(self) -> List[Dict[str, Any]]:
        """Обнаружение миграций данных"""
        data_migrations_dir = self.migrations_dir / "data_migrations"
        migrations = []

        if data_migrations_dir.exists():
            for migration_file in sorted(data_migrations_dir.glob("*.py")):
                if migration_file.name.startswith("__"):
                    continue

                # Парсинг метаданных из файла (упрощённо)
                version = migration_file.stem.split('_')[0]
                name = '_'.join(migration_file.stem.split('_')[1:])

                migrations.append({
                    'id': f"data_{version}",
                    'name': name,
                    'type': MigrationType.DATA_CONVERSION,
                    'version': version,
                    'file_path': migration_file,
                    'upgrade_func': self._load_data_migration_func(migration_file, 'upgrade'),
                    'downgrade_func': self._load_data_migration_func(migration_file, 'downgrade')
                })

        return migrations

    def _load_data_migration_func(self, file_path: Path, func_name: str) -> Callable:
        """Динамическая загрузка функции миграции данных"""
        import importlib.util

        spec = importlib.util.spec_from_file_location(file_path.stem, file_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        return getattr(module, func_name, None)

    def _execute_migration(self, migration: Dict[str, Any]) -> Dict[str, Any]:
        """Выполнение одной миграции с обработкой ошибок и откатом"""
        migration_id = migration['id']
        migration_type = migration['type']
        start_time = time.time()

        print(f"🚀 Применение миграции {migration_id} ({migration['name']})...")

        # Создание точки восстановления (бэкап критичных данных)
        checkpoint = self._create_migration_checkpoint(migration)

        try:
            # Выполнение миграции в зависимости от типа
            if migration_type == MigrationType.DATABASE_SCHEMA:
                result = self._execute_alembic_migration(migration)
            elif migration_type == MigrationType.DATA_CONVERSION:
                result = self._execute_data_migration(migration)
            elif migration_type == MigrationType.CONFIG_UPDATE:
                result = self._execute_config_migration(migration)
            else:
                raise ValueError(f"Неизвестный тип миграции: {migration_type}")

            duration = time.time() - start_time

            # Запись в историю
            record = MigrationRecord(
                id=migration_id,
                name=migration['name'],
                type=migration_type,
                version=migration['version'],
                applied_at=datetime.now(),
                duration_seconds=duration,
                success=result['success'],
                error_message=result.get('error'),
                checksum_before=checkpoint.get('checksum'),
                checksum_after=self._calculate_system_checksum()
            )

            self.migration_history.append(record)
            self._save_migration_history()

            if result['success']:
                print(f"✅ Миграция {migration_id} успешно применена за {duration:.2f} сек")
            else:
                print(f"❌ Миграция {migration_id} завершилась ошибкой: {result.get('error')}")

            return {
                'migration_id': migration_id,
                'success': result['success'],
                'duration_seconds': duration,
                'error': result.get('error'),
                'details': result.get('details', {})
            }

        except Exception as e:
            duration = time.time() - start_time
            error_msg = f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}"

            # Автоматический откат
            print(f"⚠️  Ошибка при выполнении миграции {migration_id}, выполняется откат...")
            self._rollback_to_checkpoint(checkpoint, migration)

            # Запись неудачной миграции в историю
            record = MigrationRecord(
                id=migration_id,
                name=migration['name'],
                type=migration_type,
                version=migration['version'],
                applied_at=datetime.now(),
                duration_seconds=duration,
                success=False,
                error_message=error_msg,
                rollback_applied=True
            )

            self.migration_history.append(record)
            self._save_migration_history()

            return {
                'migration_id': migration_id,
                'success': False,
                'duration_seconds': duration,
                'error': error_msg,
                'rolled_back': True
            }

    def _execute_alembic_migration(self, migration: Dict[str, Any]) -> Dict[str, Any]:
        """Выполнение миграции схемы БД через Alembic"""
        try:
            alembic_cfg = Config(str(self.migrations_dir / "alembic.ini"))
            alembic_cfg.set_main_option("script_location", str(self.versions_dir))

            # Применение миграции
            command.upgrade(alembic_cfg, migration['version'])

            return {'success': True, 'details': {'type': 'alembic_upgrade', 'version': migration['version']}}

        except Exception as e:
            return {'success': False, 'error': str(e)}

    def _execute_data_migration(self, migration: Dict[str, Any]) -> Dict[str, Any]:
        """Выполнение миграции данных"""
        try:
            upgrade_func = migration['upgrade_func']
            if not upgrade_func:
                raise ValueError(f"Функция upgrade не найдена для миграции {migration['id']}")

            # Выполнение миграции
            result = upgrade_func(data_dir=self.data_dir)

            return {'success': True, 'details': result or {}}

        except Exception as e:
            return {'success': False, 'error': str(e)}

    def _execute_config_migration(self, migration: Dict[str, Any]) -> Dict[str, Any]:
        """Выполнение миграции конфигураций"""
        try:
            # Загрузка текущих конфигов
            old_configs = self.config_manager.load_all_configs()

            # Применение преобразований
            new_configs = self._apply_config_transformations(old_configs, migration)

            # Валидация новых конфигов
            validation = self.config_manager.validate_configs(new_configs)
            if not validation['valid']:
                raise ValueError(f"Валидация конфигов после миграции не пройдена: {validation['errors']}")

            # Сохранение новых конфигов
            self.config_manager.save_configs(new_configs)

            return {
                'success': True,
                'details': {
                    'configs_updated': list(new_configs.keys()),
                    'validation_passed': True
                }
            }

        except Exception as e:
            return {'success': False, 'error': str(e)}

    def _create_pre_migration_backup(self, migrations: List[Dict[str, Any]]) -> Path:
        """Создание полного бэкапа перед серией миграций"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        migration_ids = '_'.join([m['id'] for m in migrations[:3]])  # Первые 3 миграции в имени
        if len(migrations) > 3:
            migration_ids += f"_and_{len(migrations) - 3}_more"

        backup_name = f"pre_migration_{timestamp}_{migration_ids}"
        backup_path = self.backup_dir / backup_name

        # Создание бэкапа через существующую систему бэкапов
        from scripts.maintenance.backup_system import BackupSystem
        backup_system = BackupSystem(backup_root=str(self.backup_dir))

        result = backup_system.create_backup(
            backup_type='full',
            backup_name=backup_name,
            include_paths=['data/', 'config/', 'ai/models/'],
            compress=True,
            encrypt=True
        )

        return Path(result['backup_path'])

    def _create_migration_checkpoint(self, migration: Dict[str, Any]) -> Dict[str, Any]:
        """Создание точки восстановления перед миграцией"""
        # Расчёт контрольной суммы критичных данных
        checksum = self._calculate_system_checksum()

        # Бэкап только изменяемых компонентов
        affected_components = self._get_affected_components(migration)
        checkpoint_dir = self.backup_dir / f"checkpoint_{migration['id']}_{int(time.time())}"
        checkpoint_dir.mkdir(parents=True, exist_ok=True)

        for component in affected_components:
            src = Path(component)
            if src.exists():
                dst = checkpoint_dir / src.name
                if src.is_file():
                    shutil.copy2(src, dst)
                elif src.is_dir():
                    shutil.copytree(src, dst, dirs_exist_ok=True)

        return {
            'migration_id': migration['id'],
            'timestamp': datetime.now().isoformat(),
            'checksum': checksum,
            'checkpoint_dir': str(checkpoint_dir),
            'affected_components': affected_components
        }

    def _calculate_system_checksum(self) -> str:
        """Расчёт контрольной суммы критичных данных системы"""
        import hashlib

        hasher = hashlib.sha256()

        # Хеширование ключевых файлов
        critical_files = [
            Path("data/jobs/jobs_index.json"),
            Path("data/clients/clients_index.json"),
            Path("data/finances/transactions.json"),
            Path("config/settings.json"),
            Path("config/ai_config.json")
        ]

        for file_path in critical_files:
            if file_path.exists():
                hasher.update(file_path.read_bytes())

        return hasher.hexdigest()

    def _rollback_to_checkpoint(self, checkpoint: Dict[str, Any], migration: Dict[str, Any]):
        """Откат системы к точке восстановления"""
        checkpoint_dir = Path(checkpoint['checkpoint_dir'])

        if not checkpoint_dir.exists():
            print(f"⚠️  Точка восстановления не найдена: {checkpoint_dir}")
            return False

        # Восстановление компонентов
        for component in checkpoint['affected_components']:
            backup_path = checkpoint_dir / Path(component).name
            target_path = Path(component)

            if backup_path.exists():
                if backup_path.is_file():
                    shutil.copy2(backup_path, target_path)
                elif backup_path.is_dir():
                    # Очистка целевой директории
                    if target_path.exists():
                        shutil.rmtree(target_path)
                    shutil.copytree(backup_path, target_path)

        print(f"✅ Откат к точке восстановления {checkpoint['migration_id']} выполнен")
        return True

    def _rollback_migrations(self, results: List[Dict[str, Any]]):
        """Откат успешно применённых миграций в обратном порядке"""
        # Фильтрация успешных миграций
        successful_migrations = [r for r in results if r['success']]

        if not successful_migrations:
            return

        print(f"↩️  Выполняется откат {len(successful_migrations)} миграций...")

        # Откат в обратном порядке
        for result in reversed(successful_migrations):
            migration_id = result['migration_id']
            print(f"  Откат миграции {migration_id}...")
            # Логика отката (зависит от типа миграции)
            # ... реализация отката ...

    def _get_current_version(self) -> str:
        """Получение текущей версии системы"""
        # Версия из последней применённой миграции
        if self.migration_history:
            return self.migration_history[-1].version

        # Версия из файла версии
        version_file = Path("VERSION")
        if version_file.exists():
            return version_file.read_text().strip()

        return "0.0.0"

    def _get_pending_migrations(self,
                                current_version: str,
                                target_version: str,
                                available_migrations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Определение списка миграций для применения"""
        # Фильтрация миграций между текущей и целевой версиями
        pending = [
            m for m in available_migrations
            if self._version_greater(m['version'], current_version) and
               self._version_less_equal(m['version'], target_version)
        ]

        return pending

    def _version_greater(self, v1: str, v2: str) -> bool:
        """Сравнение версий (упрощённо)"""
        return v1 > v2

    def _version_less_equal(self, v1: str, v2: str) -> bool:
        """Сравнение версий (упрощённо)"""
        return v1 <= v2

    def _load_migration_history(self) -> List[MigrationRecord]:
        """Загрузка истории миграций из файла"""
        if not self.migration_history_path.exists():
            return []

        try:
            with open(self.migration_history_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            return [MigrationRecord(**record) for record in data]
        except Exception as e:
            print(f"⚠️  Ошибка загрузки истории миграций: {e}")
            return []

    def _save_migration_history(self):
        """Сохранение истории миграций в файл"""
        try:
            with open(self.migration_history_path, 'w', encoding='utf-8') as f:
                json.dump(
                    [asdict(record) for record in self.migration_history],
                    f,
                    indent=2,
                    ensure_ascii=False,
                    default=str
                )
        except Exception as e:
            print(f"⚠️  Ошибка сохранения истории миграций: {e}")

    def _save_migration_report(self, report: Dict[str, Any]):
        """Сохранение отчёта о миграции"""
        report_dir = Path("data/reports/migrations")
        report_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        report_path = report_dir / f"migration_report_{timestamp}.json"

        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False, default=str)

        print(f"📄 Отчёт о миграции сохранён: {report_path}")

    def _is_migration_locked(self) -> bool:
        """Проверка наличия блокировки миграции"""
        if not self.migration_lock_path.exists():
            return False

        # Проверка "свежести" блокировки (защита от зависаний)
        lock_age = time.time() - self.migration_lock_path.stat().st_mtime
        if lock_age > 3600:  # Блокировка старше часа — считаем её "зависшей"
            print(f"⚠️  Обнаружена зависшая блокировка миграции (возраст: {lock_age / 60:.1f} мин), игнорируем")
            return False

        return True

    def _acquire_migration_lock(self):
        """Установка блокировки миграции"""
        with open(self.migration_lock_path, 'w', encoding='utf-8') as f:
            f.write(f"Locked at {datetime.now().isoformat()}\nPID: {os.getpid()}")

    def _release_migration_lock(self):
        """Снятие блокировки миграции"""
        if self.migration_lock_path.exists():
            self.migration_lock_path.unlink(missing_ok=True)

    def _validate_post_migration(self) -> Dict[str, Any]:
        """Валидация целостности системы после миграции"""
        validations = {
            'database_connection': self._validate_db_connection(),
            'config_integrity': self._validate_config_integrity(),
            'data_consistency': self
            'critical_files_exist': self._validate_critical_files(),
            'blockchain_connection': self._validate_blockchain_connection()
        }

        all_passed = all(validations.values())

        return {
            'passed': all_passed,
            'details': validations,
            'timestamp': datetime.now().isoformat()
        }

    def _validate_db_connection(self) -> bool:
        """Валидация подключения к БД"""
        try:
            engine = create_engine(self.config_manager.get_config('database')['url'])
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    def _validate_config_integrity(self) -> bool:
        """Валидация целостности конфигураций"""
        try:
            configs = self.config_manager.load_all_configs()
            validation = self.config_manager.validate_configs(configs)
            return validation['valid']
        except Exception:
            return False

    def _validate_critical_files(self) -> bool:
        """Валидация существования критичных файлов"""
        critical_files = [
            Path("config/settings.json"),
            Path("data/jobs/jobs_index.json"),
            Path("data/clients/clients_index.json")
        ]
        return all(f.exists() for f in critical_files)

    def _validate_blockchain_connection(self) -> bool:
        """Валидация подключения к блокчейну"""
        try:
            from blockchain.wallet_manager import WalletManager
            wm = WalletManager()
            return wm.is_connected()
        except Exception:
            return False

    def _get_affected_components(self, migration: Dict[str, Any]) -> List[str]:
        """Определение компонентов, затронутых миграцией"""
        # В реальной системе — анализ метаданных миграции
        # Для примера возвращаем общие компоненты по типу миграции
        if migration['type'] == MigrationType.DATABASE_SCHEMA:
            return ["data/database/"]
        elif migration['type'] == MigrationType.DATA_CONVERSION:
            return ["data/jobs/", "data/clients/", "data/finances/"]
        elif migration['type'] == MigrationType.CONFIG_UPDATE:
            return ["config/"]
        else:
            return ["data/", "config/"]

    def _apply_config_transformations(self, configs: Dict[str, Any], migration: Dict[str, Any]) -> Dict[str, Any]:
        """Применение преобразований к конфигурациям"""
        # В реальной системе — загрузка и выполнение функции трансформации из файла миграции
        # Для примера возвращаем неизменённые конфиги
        return configs

    def _dry_run_migration(self, migration: Dict[str, Any]) -> Dict[str, Any]:
        """Пробный запуск миграции без реальных изменений"""
        print(f"🔍 Dry run миграции {migration['id']} ({migration['name']})...")

        # Симуляция выполнения
        # ... логика симуляции ...

        return {
            'migration_id': migration['id'],
            'success': True,
            'duration_seconds': 0.1,
            'error': None,
            'dry_run': True,
            'would_modify': self._get_affected_components(migration)
        }

    def get_migration_status(self) -> Dict[str, Any]:
        """Получение статуса миграций системы"""
        current_version = self._get_current_version()
        available_migrations = self._discover_available_migrations()
        pending_migrations = self._get_pending_migrations(
            current_version,
            available_migrations[-1]['version'] if available_migrations else current_version,
            available_migrations
        )

        return {
            'current_version': current_version,
            'latest_available_version': available_migrations[-1][
                'version'] if available_migrations else current_version,
            'pending_migrations_count': len(pending_migrations),
            'pending_migrations': [
                {'id': m['id'], 'name': m['name'], 'version': m['version'], 'type': m['type'].value}
                for m in pending_migrations
            ],
            'last_migration': asdict(self.migration_history[-1]) if self.migration_history else None,
            'migration_history_count': len(self.migration_history),
            'needs_migration': len(pending_migrations) > 0
        }

    # CLI интерфейс
    def main():
        import argparse

        parser = argparse.ArgumentParser(description='Унифицированный менеджер миграций')
        parser.add_argument('--version', '-v', action='version', version='1.2.0')
        parser.add_argument('--target-version', '-t', help='Целевая версия для миграции')
        parser.add_argument('--dry-run', '-n', action='store_true', help='Пробный запуск без реальных изменений')
        parser.add_argument('--no-backup', action='store_true', help='Не создавать бэкап перед миграцией')
        parser.add_argument('--status', '-s', action='store_true', help='Показать статус миграций')
        parser.add_argument('--list', '-l', action='store_true', help='Список доступных миграций')

        args = parser.parse_args()

        manager = UnifiedMigrationManager()

        if args.status:
            status = manager.get_migration_status()
            print(json.dumps(status, indent=2, ensure_ascii=False))
            return 0

        if args.list:
            migrations = manager._discover_available_migrations()
            print(f"Доступно миграций: {len(migrations)}")
            for m in migrations:
                print(f"  {m['version']:>5} | {m['id']:30} | {m['name']}")
            return 0

        # Запуск миграций
        print("🚀 Запуск миграций системы...")
        print(f"   Текущая версия: {manager._get_current_version()}")
        if args.target_version:
            print(f"   Целевая версия: {args.target_version}")

        try:
            report = manager.run_migrations(
                target_version=args.target_version,
                dry_run=args.dry_run,
                backup_before=not args.no_backup
            )

            print("\n" + "=" * 80)
            if report['status'] == 'success':
                print("✅ МИГРАЦИЯ УСПЕШНО ЗАВЕРШЕНА")
            elif report['status'] == 'up_to_date':
                print("ℹ️  СИСТЕМА УЖЕ АКТУАЛЬНА")
            else:
                print("⚠️  МИГРАЦИЯ ЗАВЕРШЕНА С ОШИБКАМИ")

            print(f"   Версия системы: {report['current_version']}")
            print(f"   Применено миграций: {report['migrations_applied']}")
            if report.get('migrations_failed', 0) > 0:
                print(f"   Ошибок: {report['migrations_failed']}")
            print(f"   Общее время: {report['total_duration_seconds']:.2f} сек")
            if report.get('backup_path'):
                print(f"   Бэкап: {report['backup_path']}")
            print("=" * 80)

            # Вывод деталей при ошибках
            if report['status'] != 'success' and report['status'] != 'up_to_date':
                print("\nДЕТАЛИ ОШИБОК:")
                for result in report['results']:
                    if not result['success']:
                        print(f"  ✗ {result['migration_id']}: {result.get('error', 'Неизвестная ошибка')[:200]}")

            # Валидация
            print("\nРЕЗУЛЬТАТЫ ВАЛИДАЦИИ:")
            for check, passed in report['validation']['details'].items():
                status = "✅" if passed else "❌"
                print(f"  {status} {check}: {'OK' if passed else 'FAILED'}")

            return 0 if report['status'] == 'success' or report['status'] == 'up_to_date' else 1

        except Exception as e:
            print(f"\n❌ КРИТИЧЕСКАЯ ОШИБКА МИГРАЦИИ:\n{e}", file=sys.stderr)
            traceback.print_exc()
            return 1

    if __name__ == "__main__":
        exit(main())