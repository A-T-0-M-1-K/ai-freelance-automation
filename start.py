#!/usr/bin/env python3
"""
AI Freelance Automation — Стартовый скрипт
Запускает систему в автономном режиме с полной инициализацией ядра.
Обеспечивает graceful shutdown, логирование и восстановление после сбоев.
"""

import os
import sys
import asyncio
import signal
import logging
from pathlib import Path

# Убедимся, что корень проекта в PYTHONPATH
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.config.unified_config_manager import UnifiedConfigManager
from core.security.advanced_crypto_system import AdvancedCryptoSystem
from core.application_core import ApplicationCore
from scripts.setup.first_time_setup import ensure_first_time_setup


def setup_logging(config: UnifiedConfigManager):
    """Инициализирует централизованное логирование."""
    log_config = config.get("logging", {})
    log_level = getattr(logging, log_config.get("level", "INFO").upper())
    log_dir = Path(log_config.get("directory", "logs/app")).expanduser()
    log_dir.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=log_level,
        format='%(asctime)s [%(levelname)-8s] %(name)s:%(funcName)s:%(lineno)d — %(message)s',
        handlers=[
            logging.FileHandler(log_dir / "application.log"),
            logging.StreamHandler(sys.stdout)
        ]
    )


def handle_shutdown(app: ApplicationCore):
    """Регистрирует обработчики сигналов для корректного завершения."""
    def signal_handler(signum, frame):
        logging.getLogger("StartScript").info(f"Получен сигнал {signum}. Завершение работы...")
        asyncio.create_task(app.shutdown())

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)


async def main():
    """Основная точка входа в автономную систему."""
    logger = logging.getLogger("StartScript")
    logger.info("🚀 Запуск AI Freelance Automation System...")

    try:
        # 1. Первичная настройка (если нужно)
        await ensure_first_time_setup()

        # 2. Загрузка конфигурации
        config = UnifiedConfigManager()
        config.load_all()  # Загружает все JSON-конфиги из config/ + .env

        # 3. Настройка логирования
        setup_logging(config)

        # 4. Инициализация криптосистемы
        crypto = AdvancedCryptoSystem(config.get("security", {}))

        # 5. Создание и запуск ядра приложения
        app = ApplicationCore(config=config, crypto=crypto)
        handle_shutdown(app)

        await app.start()

        # Ожидание завершения (обычно через сигнал)
        while app.is_running:
            await asyncio.sleep(1)

    except KeyboardInterrupt:
        logger.info("Остановка по запросу пользователя (Ctrl+C).")
    except Exception as e:
        logger.critical(f"❌ Критическая ошибка при запуске: {e}", exc_info=True)
        sys.exit(1)
    finally:
        logger.info("✅ Система завершила работу.")


if __name__ == "__main__":
    # Требуем Python >= 3.10
    if sys.version_info < (3, 10):
        raise RuntimeError("Требуется Python 3.10 или новее.")

    asyncio.run(main())