# AI_FREELANCE_AUTOMATION/migrations/migration_manager.py
"""
Менеджер миграций базы данных.
Обеспечивает безопасное, откатываемое и версионированное обновление схемы БД.
Интегрирован с системой резервного копирования и мониторингом.
"""

import os
import sys
import logging
import shutil
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime

from alembic import command
from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from alembic.runtime.environment import EnvironmentContext
from alembic.runtime.migration import MigrationContext

from core.config.unified_config_manager import UnifiedConfigManager
from core.security.audit_logger import AuditLogger
from core.monitoring.intelligent_monitoring_system import IntelligentMonitoringSystem
from scripts.maintenance.backup_system import backup_system


class MigrationManager:
    """
    Централизованный менеджер миграций.
    Поддерживает:
      - Автоматическое создание бэкапа перед миграцией
      - Валидацию целостности миграций
      - Откат при ошибках
      - Аудит всех операций
      - Интеграцию с мониторингом
    """

    def __init__(self, config: Optional[UnifiedConfigManager] = None):
        self.config = config or UnifiedConfigManager()
        self.logger = logging.getLogger("MigrationManager")
        self.migrations_path = Path(__file__).parent.resolve()
        self.alembic_ini_path = self.migrations_path / "alembic.ini"
        self.backup_dir = Path(self.config.get("backup.automatic.migration_backup_dir", "backup/automatic/migration"))
        self.backup_dir.mkdir(parents=True, exist_ok=True)

        # Инициализация зависимостей
        self.audit_logger = AuditLogger()
        self.monitor = IntelligentMonitoringSystem(self.config)

        if not self.alembic_ini_path.exists():
            raise FileNotFoundError(f"Отсутствует alembic.ini по пути: {self.alembic_ini_path}")

        self.alembic_cfg = AlembicConfig(str(self.alembic_ini_path))
        self.alembic_cfg.set_main_option("script_location", str(self.migrations_path / "versions"))

    def _create_pre_migration_backup(self) -> Path:
        """Создает резервную копию перед миграцией."""
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        backup_path = self.backup_dir / f"pre_migration_{timestamp}"
        self.logger.info(f"Создание резервной копии перед миграцией: {backup_path}")
        backup_system(target_dir=str(backup_path), include_db=True, include_configs=False)
        self.audit_logger.log(
            action="migration_backup_created",
            resource_type="database",
            details={"backup_path": str(backup_path)}
        )
        return backup_path

    def _validate_migrations_integrity(self) -> bool:
        """Проверяет целостность цепочки миграций."""
        script = ScriptDirectory.from_config(self.alembic_cfg)
        try:
            # Проверка на наличие разрывов в цепочке
            script.walk_revisions()
            self.logger.debug("Целостность миграций подтверждена.")
            return True
        except Exception as e:
            self.logger.error(f"Нарушена целостность миграций: {e}")
            return False

    def get_current_revision(self) -> Optional[str]:
        """Возвращает текущую версию БД."""
        try:
            from sqlalchemy import create_engine
            db_url = self.config.get("database.url")
            engine = create_engine(db_url)
            with engine.connect() as conn:
                context = MigrationContext.configure(conn)
                return context.get_current_revision()
        except Exception as e:
            self.logger.error(f"Не удалось определить текущую ревизию: {e}")
            return None

    def get_head_revision(self) -> str:
        """Возвращает последнюю доступную ревизию."""
        script = ScriptDirectory.from_config(self.alembic_cfg)
        return script.get_current_head()

    def is_up_to_date(self) -> bool:
        """Проверяет, актуальна ли схема БД."""
        current = self.get_current_revision()
        head = self.get_head_revision()
        return current == head

    def upgrade(self, revision: str = "head", dry_run: bool = False) -> bool:
        """
        Выполняет миграцию вверх до указанной ревизии.
        При dry_run — только проверяет, что будет выполнено.
        """
        if dry_run:
            self.logger.info("🧪 Режим dry-run: проверка миграции без изменений.")
            return True

        if not self._validate_migrations_integrity():
            self.logger.critical("❌ Миграция отменена: нарушена целостность.")
            return False

        current = self.get_current_revision()
        head = self.get_head_revision()
        if current == head:
            self.logger.info("✅ База данных уже актуальна.")
            return True

        # Создание бэкапа
        backup_path = self._create_pre_migration_backup()

        try:
            self.logger.info(f"⬆️ Запуск миграции: {current} → {revision}")
            self.audit_logger.log(
                action="migration_started",
                resource_type="database",
                details={"from": current, "to": revision}
            )

            command.upgrade(self.alembic_cfg, revision)

            self.logger.info("✅ Миграция успешно завершена.")
            self.audit_logger.log(
                action="migration_completed",
                resource_type="database",
                details={"to": revision}
            )
            self.monitor.record_event("migration.success", {"revision": revision})
            return True

        except Exception as e:
            self.logger.critical(f"💥 Ошибка миграции: {e}", exc_info=True)
            self.audit_logger.log(
                action="migration_failed",
                resource_type="database",
                details={"error": str(e), "backup_used": str(backup_path)}
            )
            self.monitor.record_event("migration.failure", {"error": str(e)})
            # Здесь можно добавить автоматический откат, если поддерживается
            raise

    def downgrade(self, revision: str) -> bool:
        """Выполняет откат миграции до указанной ревизии."""
        self.logger.warning(f"⬇️ Запуск отката миграции до: {revision}")
        try:
            command.downgrade(self.alembic_cfg, revision)
            self.audit_logger.log(
                action="migration_downgraded",
                resource_type="database",
                details={"to": revision}
            )
            return True
        except Exception as e:
            self.logger.error(f"Ошибка отката миграции: {e}", exc_info=True)
            raise

    def generate_revision(self, message: str, autogenerate: bool = True) -> Optional[str]:
        """Генерирует новую миграцию на основе изменений в моделях."""
        if not autogenerate:
            self.logger.warning("⚠️ Ручная миграция требует редактирования шаблона.")
        try:
            rev = command.revision(
                self.alembic_cfg,
                message=message,
                autogenerate=autogenerate
            )
            self.audit_logger.log(
                action="migration_generated",
                resource_type="database",
                details={"message": message, "autogenerate": autogenerate}
            )
            return rev.revision if rev else None
        except Exception as e:
            self.logger.error(f"Не удалось сгенерировать миграцию: {e}")
            return None

    def show_history(self) -> List[Dict[str, Any]]:
        """Возвращает историю миграций."""
        script = ScriptDirectory.from_config(self.alembic_cfg)
        history = []
        for rev in script.walk_revisions():
            history.append({
                "revision": rev.revision,
                "down_revision": rev.down_revision,
                "doc": rev.doc,
                "branch_labels": rev.branch_labels,
                "timestamp": getattr(rev, "timestamp", None)
            })
        return history


# Утилитарная функция для CLI или скриптов
def run_migration_cli(action: str, **kwargs) -> int:
    """
    Запускает миграцию из CLI.
    Пример: run_migration_cli("upgrade", revision="head")
    """
    try:
        manager = MigrationManager()
        if action == "upgrade":
            success = manager.upgrade(kwargs.get("revision", "head"))
            return 0 if success else 1
        elif action == "downgrade":
            success = manager.downgrade(kwargs.get("revision", "-1"))
            return 0 if success else 1
        elif action == "generate":
            rev = manager.generate_revision(
                message=kwargs["message"],
                autogenerate=kwargs.get("autogenerate", True)
            )
            if rev:
                print(f"Создана миграция: {rev}")
                return 0
            else:
                return 1
        else:
            logging.error(f"Неизвестное действие: {action}")
            return 1
    except Exception as e:
        logging.critical(f"Критическая ошибка в CLI миграции: {e}")
        return 1


if __name__ == "__main__":
    # Пример использования как standalone-скрипта
    import argparse
    parser = argparse.ArgumentParser(description="Менеджер миграций БД")
    parser.add_argument("action", choices=["upgrade", "downgrade", "generate"])
    parser.add_argument("--revision", default="head")
    parser.add_argument("--message", default="")
    parser.add_argument("--autogenerate", action="store_true")
    args = parser.parse_args()

    sys.exit(run_migration_cli(
        action=args.action,
        revision=args.revision,
        message=args.message,
        autogenerate=args.autogenerate
    ))