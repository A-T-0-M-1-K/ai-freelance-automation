# AI_FREELANCE_AUTOMATION/scripts/deployment/update_system.py
"""
Система безопасного обновления AI Freelance Automation.
Выполняет:
- Проверку наличия обновлений
- Резервное копирование перед обновлением
- Применение обновлений (код, конфиги, модели)
- Валидацию после обновления
- Автоматический откат при сбое
- Обновление зависимостей и миграций БД

Интегрируется с:
- backup_system
- config_manager
- health_monitor
- logging
- dependency_manager
"""

import asyncio
import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional, Dict, Any

# Импорты из ядра — через service locator для избежания циклических зависимостей
from core.dependency.service_locator import ServiceLocator
from core.config.unified_config_manager import UnifiedConfigManager
from core.security.audit_logger import AuditLogger
from core.monitoring.intelligent_monitoring_system import IntelligentMonitoringSystem


class UpdateSystem:
    def __init__(self):
        self.logger = logging.getLogger("UpdateSystem")
        self.config: UnifiedConfigManager = ServiceLocator.get("config")
        self.audit_logger: AuditLogger = ServiceLocator.get("audit_logger")
        self.monitor: IntelligentMonitoringSystem = ServiceLocator.get("monitoring")
        self.backup_dir = Path(self.config.get("backup.automatic.path", "backup/automatic"))
        self.update_source = self.config.get("deployment.update.source", "https://api.ai-freelance.dev/releases/latest")
        self.current_version_file = Path("VERSION")
        self.temp_dir = Path(tempfile.mkdtemp(prefix="update_"))

    async def check_for_updates(self) -> Optional[Dict[str, Any]]:
        """Проверяет наличие новых версий через API или файл."""
        self.logger.info("🔍 Проверка наличия обновлений...")
        try:
            # Пример: загрузка manifest.json с метаданными
            import httpx
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(f"{self.update_source}/manifest.json")
                resp.raise_for_status()
                remote_manifest = resp.json()

            local_version = self._get_local_version()
            remote_version = remote_manifest.get("version")

            if self._is_newer_version(local_version, remote_version):
                self.logger.info(f"🆕 Доступна новая версия: {remote_version} (текущая: {local_version})")
                return remote_manifest
            else:
                self.logger.info("✅ Система актуальна.")
                return None
        except Exception as e:
            self.logger.error(f"❌ Ошибка при проверке обновлений: {e}")
            return None

    def _get_local_version(self) -> str:
        if self.current_version_file.exists():
            return self.current_version_file.read_text().strip()
        return "0.0.0"

    def _is_newer_version(self, current: str, new: str) -> bool:
        from packaging.version import parse
        return parse(new) > parse(current)

    async def perform_update(self) -> bool:
        """Основной метод обновления системы."""
        self.logger.info("🔄 Запуск процесса обновления...")
        manifest = await self.check_for_updates()
        if not manifest:
            self.logger.info("Обновление не требуется.")
            return True

        try:
            # 1. Создать резервную копию
            await self._create_backup(manifest["version"])

            # 2. Скачать архив обновления
            archive_path = await self._download_update(manifest)

            # 3. Распаковать в временную директорию
            extracted_path = await self._extract_update(archive_path)

            # 4. Проверить контрольные суммы
            if not self._verify_integrity(extracted_path, manifest.get("checksums", {})):
                raise RuntimeError("❌ Нарушена целостность обновления!")

            # 5. Выполнить миграции (до замены файлов)
            await self._run_migrations(extracted_path / "migrations")

            # 6. Обновить зависимости
            await self._update_dependencies(extracted_path)

            # 7. Заменить файлы
            await self._replace_files(extracted_path)

            # 8. Обновить VERSION
            self.current_version_file.write_text(manifest["version"])

            # 9. Перезагрузить конфигурацию
            self.config.reload()

            # 10. Валидация работоспособности
            if not await self._validate_system():
                raise RuntimeError("❌ Система не прошла валидацию после обновления!")

            self.logger.info(f"✅ Обновление до версии {manifest['version']} успешно завершено!")
            self.audit_logger.log("system_update", {"version": manifest["version"], "status": "success"})
            return True

        except Exception as e:
            self.logger.critical(f"💥 Критическая ошибка при обновлении: {e}")
            self.audit_logger.log("system_update", {"error": str(e), "status": "failed"})
            await self._rollback(manifest["version"])
            return False
        finally:
            self._cleanup_temp()

    async def _create_backup(self, version: str):
        self.logger.info("💾 Создание резервной копии перед обновлением...")
        backup_script = Path("scripts/maintenance/backup_system.py")
        if backup_script.exists():
            result = subprocess.run([sys.executable, str(backup_script), "--type", "pre-update", "--tag", f"v{version}"])
            if result.returncode != 0:
                raise RuntimeError("Не удалось создать резервную копию!")
        else:
            # Fallback: копировать важные директории
            shutil.copytree("data", self.backup_dir / f"pre-update_v{version}" / "data", dirs_exist_ok=True)
            shutil.copytree("config", self.backup_dir / f"pre-update_v{version}" / "config", dirs_exist_ok=True)

    async def _download_update(self, manifest: Dict[str, Any]) -> Path:
        import httpx
        url = manifest["archive_url"]
        archive_name = url.split("/")[-1]
        archive_path = self.temp_dir / archive_name

        self.logger.info(f"📥 Скачивание обновления: {url}")
        async with httpx.AsyncClient(timeout=120.0) as client:
            with open(archive_path, "wb") as f:
                async for chunk in client.stream("GET", url):
                    f.write(chunk)
        return archive_path

    async def _extract_update(self, archive_path: Path) -> Path:
        import tarfile
        extract_to = self.temp_dir / "extracted"
        extract_to.mkdir(exist_ok=True)

        if archive_path.suffix == ".tar.gz":
            with tarfile.open(archive_path, "r:gz") as tar:
                tar.extractall(path=extract_to)
        elif archive_path.suffix == ".zip":
            import zipfile
            with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                zip_ref.extractall(extract_to)
        else:
            raise ValueError("Неподдерживаемый формат архива")

        # Ожидается, что внутри один корневой каталог
        items = list(extract_to.iterdir())
        if len(items) == 1 and items[0].is_dir():
            return items[0]
        return extract_to

    def _verify_integrity(self, extracted_path: Path, checksums: Dict[str, str]) -> bool:
        self.logger.info("🛡️ Проверка целостности файлов...")
        for rel_path, expected_hash in checksums.items():
            full_path = extracted_path / rel_path
            if not full_path.exists():
                self.logger.warning(f"Файл отсутствует: {rel_path}")
                return False
            actual_hash = hashlib.sha256(full_path.read_bytes()).hexdigest()
            if actual_hash != expected_hash:
                self.logger.warning(f"Хэш не совпадает: {rel_path}")
                return False
        return True

    async def _run_migrations(self, migrations_path: Path):
        if not migrations_path.exists():
            return
        self.logger.info("🔧 Запуск миграций базы данных...")
        migration_manager = Path("migrations/migration_manager.py")
        if migration_manager.exists():
            result = subprocess.run([sys.executable, str(migration_manager), "--auto"])
            if result.returncode != 0:
                raise RuntimeError("Миграции завершились с ошибкой!")

    async def _update_dependencies(self, update_root: Path):
        req_file = update_root / "requirements-base.txt"
        if not req_file.exists():
            return
        self.logger.info("📦 Обновление зависимостей...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", str(req_file)])

    async def _replace_files(self, update_root: Path):
        self.logger.info("🔄 Замена файлов системы...")
        exclude = {"data", "backup", ".env", "logs", "ai/models"}  # Не трогаем пользовательские данные
        for item in update_root.iterdir():
            if item.name in exclude:
                continue
            dest = Path(item.name)
            if dest.exists():
                if dest.is_dir():
                    shutil.rmtree(dest)
                else:
                    dest.unlink()
            if item.is_dir():
                shutil.copytree(item, dest)
            else:
                shutil.copy2(item, dest)

    async def _validate_system(self) -> bool:
        self.logger.info("🧪 Валидация работоспособности системы...")
        try:
            # Запустить минимальный health-check
            from core.health_monitor import HealthMonitor
            health = HealthMonitor(ServiceLocator.get_all_services())
            report = await health.generate_health_report()
            return report.get("overall_status") == "healthy"
        except Exception as e:
            self.logger.error(f"Валидация провалена: {e}")
            return False

    async def _rollback(self, version: str):
        self.logger.warning("⏪ Выполнение отката к предыдущей версии...")
        backup_path = self.backup_dir / f"pre-update_v{version}"
        if not backup_path.exists():
            self.logger.error("Резервная копия для отката не найдена!")
            return

        # Восстановить config и data
        if (backup_path / "config").exists():
            shutil.rmtree("config")
            shutil.copytree(backup_path / "config", "config")
        if (backup_path / "data").exists():
            shutil.rmtree("data")
            shutil.copytree(backup_path / "data", "data")

        self.logger.info("✅ Откат завершён. Требуется перезапуск.")

    def _cleanup_temp(self):
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)


# CLI-точка входа
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    async def main():
        updater = UpdateSystem()
        success = await updater.perform_update()
        sys.exit(0 if success else 1)

    asyncio.run(main())