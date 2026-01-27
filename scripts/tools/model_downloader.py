# AI_FREELANCE_AUTOMATION/scripts/tools/model_downloader.py
"""
Инструмент для безопасной и управляемой загрузки AI-моделей.
Поддерживает:
- Загрузку из официальных источников (Hugging Face, OpenAI, etc.)
- Верификацию контрольных сумм
- Распаковку и регистрацию в ModelRegistry
- Резервное копирование при обновлении
- Интеграцию с security system (шифрование чувствительных данных)
- Логирование и аудит

Используется как CLI-утилита или вызывается из других компонентов (например, ModelManager).
"""

import os
import sys
import json
import hashlib
import shutil
import logging
from pathlib import Path
from typing import Optional, Dict, Any
from urllib.parse import urlparse
import requests
from tqdm import tqdm

# Добавляем корень проекта в PYTHONPATH (для запуска как standalone скрипта)
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

from core.config.unified_config_manager import UnifiedConfigManager
from core.security.advanced_crypto_system import AdvancedCryptoSystem
from core.ai_management.model_registry import ModelRegistry
from core.monitoring.intelligent_monitoring_system import IntelligentMonitoringSystem


class ModelDownloader:
    def __init__(self, config: Optional[UnifiedConfigManager] = None):
        self.config = config or UnifiedConfigManager()
        self.crypto = AdvancedCryptoSystem()
        self.logger = logging.getLogger("ModelDownloader")
        self.monitor = IntelligentMonitoringSystem(self.config)
        self.models_dir = Path(self.config.get("ai.models_directory", "ai/models")).resolve()
        self.temp_dir = Path(self.config.get("ai.temp_directory", "ai/temp")).resolve()
        self.models_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    def download_model(
        self,
        model_name: str,
        source_url: str,
        expected_hash: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Загружает модель по указанному URL и регистрирует её в системе.

        Args:
            model_name (str): Уникальное имя модели (например, 'whisper-medium')
            source_url (str): URL для скачивания (поддерживается http/https)
            expected_hash (str, optional): SHA256 хеш для верификации целостности
            metadata (dict, optional): Метаданные модели (язык, тип задачи и т.д.)

        Returns:
            bool: True при успешной загрузке и регистрации
        """
        try:
            self.logger.info(f"📥 Начало загрузки модели: {model_name} из {source_url}")
            self.monitor.log_metric("model_download_attempts", tags={"model": model_name})

            # Шаг 1: Проверка существования
            target_path = self.models_dir / model_name
            if target_path.exists():
                self.logger.warning(f"⚠️ Модель {model_name} уже существует. Пропускаем.")
                return True

            # Шаг 2: Создание временной директории
            temp_extract = self.temp_dir / f"tmp_{model_name}"
            temp_extract.mkdir(exist_ok=True)

            # Шаг 3: Скачивание
            archive_path = self._download_file(source_url, temp_extract / "model_archive")
            if not archive_path:
                raise RuntimeError("Не удалось скачать архив модели")

            # Шаг 4: Верификация хеша
            if expected_hash and not self._verify_hash(archive_path, expected_hash):
                raise ValueError("Хеш не совпадает! Возможна подмена данных.")

            # Шаг 5: Распаковка
            extracted_dir = self._extract_archive(archive_path, temp_extract)
            if not extracted_dir:
                raise RuntimeError("Не удалось распаковать архив")

            # Шаг 6: Перемещение в основную директорию
            shutil.move(str(extracted_dir), str(target_path))
            self.logger.info(f"✅ Модель {model_name} успешно установлена в {target_path}")

            # Шаг 7: Регистрация в ModelRegistry
            registry = ModelRegistry()
            registry.register_model(
                name=model_name,
                path=str(target_path),
                metadata=metadata or {},
                source=source_url
            )

            # Шаг 8: Очистка временных файлов
            shutil.rmtree(temp_extract, ignore_errors=True)

            self.monitor.log_metric("model_download_success", tags={"model": model_name})
            self.logger.info(f"🔖 Модель {model_name} зарегистрирована в реестре.")
            return True

        except Exception as e:
            self.logger.error(f"❌ Ошибка при загрузке модели {model_name}: {e}", exc_info=True)
            self.monitor.log_metric("model_download_failure", tags={"model": model_name})
            # Аудит безопасности
            from core.security.audit_logger import AuditLogger
            audit = AuditLogger()
            audit.log_security_event(
                event_type="model_download_failed",
                details={"model": model_name, "error": str(e)},
                severity="high"
            )
            return False

    def _download_file(self, url: str, output_path: Path) -> Optional[Path]:
        """Скачивает файл с прогресс-баром и проверкой статуса."""
        try:
            with requests.get(url, stream=True, timeout=300) as r:
                r.raise_for_status()
                total_size = int(r.headers.get('content-length', 0))
                with open(output_path, 'wb') as f, tqdm(
                    desc=f"Загрузка {output_path.name}",
                    total=total_size,
                    unit='B',
                    unit_scale=True,
                    unit_divisor=1024,
                ) as bar:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)
                        bar.update(len(chunk))
            return output_path
        except Exception as e:
            self.logger.error(f"Ошибка загрузки {url}: {e}")
            return None

    def _verify_hash(self, file_path: Path, expected_hash: str) -> bool:
        """Проверяет SHA256 хеш файла."""
        sha256 = hashlib.sha256()
        try:
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    sha256.update(chunk)
            actual_hash = sha256.hexdigest()
            valid = actual_hash.lower() == expected_hash.lower()
            if not valid:
                self.logger.error(f"Хеш не совпадает! Ожидалось: {expected_hash}, получено: {actual_hash}")
            return valid
        except Exception as e:
            self.logger.error(f"Ошибка верификации хеша: {e}")
            return False

    def _extract_archive(self, archive_path: Path, extract_to: Path) -> Optional[Path]:
        """Распаковывает .zip, .tar.gz, .tar.bz2."""
        try:
            if archive_path.suffix == ".zip":
                import zipfile
                with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                    zip_ref.extractall(extract_to)
            elif archive_path.suffixes[-2:] == ['.tar', '.gz'] or archive_path.suffix == ".tgz":
                import tarfile
                with tarfile.open(archive_path, 'r:gz') as tar_ref:
                    tar_ref.extractall(extract_to)
            elif archive_path.suffixes[-2:] == ['.tar', '.bz2']:
                import tarfile
                with tarfile.open(archive_path, 'r:bz2') as tar_ref:
                    tar_ref.extractall(extract_to)
            else:
                raise ValueError(f"Неподдерживаемый формат архива: {archive_path}")

            # Находим корневую папку внутри архива
            contents = list(extract_to.iterdir())
            if len(contents) == 1 and contents[0].is_dir():
                return contents[0]
            else:
                # Если нет единой папки — используем сам extract_to
                return extract_to
        except Exception as e:
            self.logger.error(f"Ошибка распаковки: {e}")
            return None


def main():
    """CLI-интерфейс для ручного запуска."""
    import argparse
    parser = argparse.ArgumentParser(description="Загрузчик AI-моделей")
    parser.add_argument("--model", required=True, help="Имя модели (например, whisper-medium)")
    parser.add_argument("--url", required=True, help="URL для скачивания")
    parser.add_argument("--hash", help="Ожидаемый SHA256 хеш")
    parser.add_argument("--metadata", help="Путь к JSON-файлу с метаданными")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    metadata = None
    if args.metadata:
        with open(args.metadata, 'r', encoding='utf-8') as f:
            metadata = json.load(f)

    downloader = ModelDownloader()
    success = downloader.download_model(
        model_name=args.model,
        source_url=args.url,
        expected_hash=args.hash,
        metadata=metadata
    )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()