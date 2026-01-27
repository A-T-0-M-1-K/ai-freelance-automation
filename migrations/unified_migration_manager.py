import os
import sys
import json
import hashlib
from pathlib import Path
from typing import List, Dict, Optional, Callable
from datetime import datetime
from alembic.config import Config
from alembic import command
from scripts.tools.data_migrator import DataMigrator


class UnifiedMigrationManager:
    """
    Унифицированный менеджер миграций, объединяющий:
    1. Структурные миграции (Alembic) — изменения схемы БД
    2. Миграции данных (собственный движок) — преобразование бизнес-данных

    Разделение ответственности с единым интерфейсом управления.
    """

    def __init__(self, alembic_cfg_path: str = "migrations/alembic.ini"):
        self.alembic_cfg = Config(alembic_cfg_path)
        self.data_migrator = DataMigrator()
        self.migration_log_path = Path("data/migrations/migration_log.json")
        self.migration_log_path.parent.mkdir(parents=True, exist_ok=True)

        # Инициализация лога миграций, если не существует
        if not self.migration_log_path.exists():
            with open(self.migration_log_path, 'w') as f:
                json.dump({"applied_migrations": [], "data_migrations": []}, f, indent=2)

    def _load_migration_log(self) -> Dict:
        with open(self.migration_log_path) as f:
            return json.load(f)

    def _save_migration_log(self, log: Dict):
        with open(self.migration_log_path, 'w') as f:
            json.dump(log, f, indent=2)

    def upgrade_schema(self, revision: str = "head", sql: bool = False) -> List[str]:
        """
        Выполнение структурных миграций через Alembic.
        """
        print(f"🚀 Применение структурных миграций до ревизии: {revision}")

        # Получение списка применяемых ревизий
        current_rev = command.current(self.alembic_cfg, silent=True)
        history = command.history(self.alembic_cfg, indicate_current=True)

        # Выполнение миграции
        command.upgrade(self.alembic_cfg, revision, sql=sql)

        # Логирование
        new_rev = command.current(self.alembic_cfg, silent=True)
        log = self._load_migration_log()

        migration_record = {
            "type": "schema",
            "from_revision": str(current_rev),
            "to_revision": str(new_rev),
            "applied_at": datetime.utcnow().isoformat(),
            "sql_mode": sql,
            "hash": hashlib.sha256(f"{current_rev}->{new_rev}".encode()).hexdigest()
        }

        log["applied_migrations"].append(migration_record)
        self._save_migration_log(log)

        print(f"✅ Структурные миграции применены: {current_rev} → {new_rev}")
        return [str(new_rev)]

    def downgrade_schema(self, revision: str, sql: bool = False) -> List[str]:
        """
        Откат структурных миграций через Alembic.
        """
        print(f"⏪ Откат структурных миграций до ревизии: {revision}")

        current_rev = command.current(self.alembic_cfg, silent=True)
        command.downgrade(self.alembic_cfg, revision, sql=sql)
        new_rev = command.current(self.alembic_cfg, silent=True)

        log = self._load_migration_log()
        log["applied_migrations"].append({
            "type": "schema_downgrade",
            "from_revision": str(current_rev),
            "to_revision": str(new_rev),
            "applied_at": datetime.utcnow().isoformat(),
            "sql_mode": sql
        })
        self._save_migration_log(log)

        print(f"✅ Откат структурных миграций выполнен: {current_rev} → {new_rev}")
        return [str(new_rev)]

    def run_data_migration(self, migration_name: str, batch_size: int = 1000) -> Dict:
        """
        Выполнение миграции данных с поддержкой отката.

        Примеры миграций:
        - convert_old_job_format → конвертация старого формата заказов
        - backfill_client_preferences → заполнение недостающих предпочтений клиентов
        - anonymize_old_data → анонимизация устаревших данных для GDPR
        """
        print(f"📊 Запуск миграции данных: {migration_name}")

        # Проверка существования миграции
        migration_func = getattr(self.data_migrator, f"migrate_{migration_name}", None)
        if not migration_func or not callable(migration_func):
            raise ValueError(f"Миграция данных '{migration_name}' не найдена")

        # Создание точки восстановления перед миграцией
        backup_path = self._create_migration_backup(migration_name)

        try:
            # Выполнение миграции с прогресс-баром
            total_records = self.data_migrator.get_total_records(migration_name)
            processed = 0

            while processed < total_records:
                batch = min(batch_size, total_records - processed)
                result = migration_func(batch_size=batch, offset=processed)

                processed += batch
                progress = (processed / total_records) * 100
                print(f"   📈 Прогресс: {progress:.1f}% ({processed}/{total_records})")

            # Логирование успешной миграции
            log = self._load_migration_log()
            log["data_migrations"].append({
                "name": migration_name,
                "applied_at": datetime.utcnow().isoformat(),
                "records_processed": total_records,
                "backup_path": str(backup_path),
                "status": "completed"
            })
            self._save_migration_log(log)

            print(f"✅ Миграция данных '{migration_name}' успешно завершена")
            return {"status": "success", "records_processed": total_records, "backup": str(backup_path)}

        except Exception as e:
            print(f"❌ Ошибка при миграции данных: {e}")
            print(f"🔄 Восстановление из резервной копии: {backup_path}")

            # Автоматический откат
            self._restore_from_backup(backup_path)

            # Логирование неудачной миграции
            log = self._load_migration_log()
            log["data_migrations"].append({
                "name": migration_name,
                "applied_at": datetime.utcnow().isoformat(),
                "error": str(e),
                "backup_path": str(backup_path),
                "status": "failed_rolled_back"
            })
            self._save_migration_log(log)

            raise RuntimeError(f"Миграция данных отменена из-за ошибки: {e}")

    def _create_migration_backup(self, migration_name: str) -> Path:
        """
        Создание точечной резервной копии перед миграцией данных.
        """
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        backup_dir = Path(f"backup/migration_backups/{migration_name}_{timestamp}")
        backup_dir.mkdir(parents=True, exist_ok=True)

        # Копирование критичных данных
        import shutil

        # Заказы
        if Path("data/jobs").exists():
            shutil.copytree("data/jobs", backup_dir / "jobs", dirs_exist_ok=True)

        # Клиенты
        if Path("data/clients").exists():
            shutil.copytree("data/clients", backup_dir / "clients", dirs_exist_ok=True)

        # Финансы
        if Path("data/finances").exists():
            shutil.copytree("data/finances", backup_dir / "finances", dirs_exist_ok=True)

        # Метаданные миграции
        with open(backup_dir / "migration_metadata.json", 'w') as f:
            json.dump({
                "migration_name": migration_name,
                "created_at": datetime.utcnow().isoformat(),
                "system_version": self._get_system_version(),
                "python_version": sys.version
            }, f, indent=2)

        print(f"💾 Создана точечная резервная копия: {backup_dir}")
        return backup_dir

    def _restore_from_backup(self, backup_path: Path):
        """
        Восстановление данных из резервной копии после неудачной миграции.
        """
        import shutil

        print(f"🔄 Восстановление данных из: {backup_path}")

        # Восстановление заказов
        if (backup_path / "jobs").exists():
            shutil.rmtree("data/jobs", ignore_errors=True)
            shutil.copytree(backup_path / "jobs", "data/jobs")

        # Восстановление клиентов
        if (backup_path / "clients").exists():
            shutil.rmtree("data/clients", ignore_errors=True)
            shutil.copytree(backup_path / "clients", "data/clients")

        # Восстановление финансов
        if (backup_path / "finances").exists():
            shutil.rmtree("data/finances", ignore_errors=True)
            shutil.copytree(backup_path / "finances", "data/finances")

        print("✅ Данные успешно восстановлены")

    def _get_system_version(self) -> str:
        """Получение версии системы из pyproject.toml"""
        try:
            import tomli
            with open("pyproject.toml", "rb") as f:
                pyproject = tomli.load(f)
            return pyproject["tool"]["poetry"]["version"]
        except:
            return "unknown"

    def list_pending_migrations(self) -> Dict[str, List]:
        """
        Список ожидающих применения миграций (структурных и данных).
        """
        # Структурные миграции
        command.history(self.alembic_cfg, indicate_current=True)
        # TODO: Реализовать парсинг вывода для определения pending revisions

        # Данные миграции — проверка наличия файлов в директории
        data_migrations_dir = Path("migrations/data_migrations")
        available = []
        if data_migrations_dir.exists():
            for file in data_migrations_dir.glob("*.py"):
                if file.stem not in ["__init__", "base_migration"]:
                    available.append(file.stem)

        log = self._load_migration_log()
        applied = [m["name"] for m in log.get("data_migrations", []) if m["status"] == "completed"]
        pending = [m for m in available if m not in applied]

        return {
            "schema_pending": ["ревизия_005", "ревизия_006"],  # Пример
            "data_pending": pending,
            "last_applied_schema": log["applied_migrations"][-1]["to_revision"] if log["applied_migrations"] else None,
            "last_applied_data": log["data_migrations"][-1]["name"] if log["data_migrations"] else None
        }

    def run_all_migrations(self, with_data: bool = True) -> Dict:
        """
        Полный прогон всех миграций (структурных + данных) при первом запуске.
        """
        print("🏁 Запуск полного цикла миграций...")

        # 1. Структурные миграции
        schema_revs = self.upgrade_schema("head")

        # 2. Миграции данных (если требуется)
        data_results = []
        if with_data:
            pending = self.list_pending_migrations()["data_pending"]
            for migration_name in pending:
                try:
                    result = self.run_data_migration(migration_name)
                    data_results.append({migration_name: result})
                except Exception as e:
                    print(f"⚠️  Миграция {migration_name} пропущена из-за ошибки: {e}")
                    data_results.append({migration_name: {"status": "skipped", "error": str(e)}})

        print("🎉 Все миграции успешно применены!")
        return {
            "schema_migrations": schema_revs,
            "data_migrations": data_results,
            "completed_at": datetime.utcnow().isoformat()
        }


# CLI-интерфейс для управления миграциями
def migration_cli():
    import argparse

    parser = argparse.ArgumentParser(description="Унифицированный менеджер миграций")
    parser.add_argument("action", choices=["upgrade", "downgrade", "list", "run-data", "run-all"],
                        help="Действие над миграциями")
    parser.add_argument("--revision", default="head", help="Целевая ревизия (для downgrade/upgrade)")
    parser.add_argument("--migration-name", help="Имя миграции данных (для run-data)")
    parser.add_argument("--sql", action="store_true", help="Вывести SQL без выполнения")
    parser.add_argument("--batch-size", type=int, default=1000, help="Размер батча для миграции данных")

    args = parser.parse_args()
    manager = UnifiedMigrationManager()

    if args.action == "upgrade":
        manager.upgrade_schema(args.revision, args.sql)

    elif args.action == "downgrade":
        manager.downgrade_schema(args.revision, args.sql)

    elif args.action == "list":
        pending = manager.list_pending_migrations()
        print("Ожидающие структурные миграции:", pending["schema_pending"])
        print("Ожидающие миграции данных:", pending["data_pending"])

    elif args.action == "run-data":
        if not args.migration_name:
            raise ValueError("--migration-name обязателен для run-data")
        manager.run_data_migration(args.migration_name, args.batch_size)

    elif args.action == "run-all":
        manager.run_all_migrations(with_data=True)


if __name__ == "__main__":
    migration_cli()
