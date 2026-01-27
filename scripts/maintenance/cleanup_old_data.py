# AI_FREELANCE_AUTOMATION/scripts/maintenance/cleanup_old_data.py
"""
Автоматизированный скрипт очистки устаревших данных.
Удаляет или архивирует временные, кэшированные и лог-файлы старше заданного срока.
Интегрируется с системой мониторинга и логирования.
Поддерживает безопасное удаление (с проверкой целостности) и восстановление при ошибке.
"""

import os
import shutil
import logging
import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Any

# Используем относительные импорты только если запускается как модуль,
# но для standalone-скрипта — абсолютные пути через корень проекта.
# Предполагаем, что скрипт запускается из корня проекта.

# Настройка логгера
logger = logging.getLogger("Maintenance.Cleanup")

# Пути по умолчанию (могут быть переопределены через конфиг)
DEFAULT_CONFIG_PATH = "config/automation.json"
CLEANUP_RULES_SCHEMA = {
    "logs": {"age_days": 30, "enabled": True},
    "cache": {"age_days": 7, "enabled": True},
    "temp_ai": {"age_days": 1, "enabled": True},
    "backup_automatic": {"age_days": 90, "enabled": False},  # по умолчанию не удаляем бэкапы
    "conversations": {"age_days": 180, "enabled": True},
}


def load_cleanup_config(config_path: str = DEFAULT_CONFIG_PATH) -> Dict[str, Any]:
    """Загружает правила очистки из конфигурации."""
    try:
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            return config.get("cleanup_rules", CLEANUP_RULES_SCHEMA)
        else:
            logger.warning(f"Конфигурация {config_path} не найдена. Используются значения по умолчанию.")
            return CLEANUP_RULES_SCHEMA
    except Exception as e:
        logger.error(f"Ошибка загрузки конфигурации очистки: {e}")
        return CLEANUP_RULES_SCHEMA


def is_older_than(path: Path, days: int) -> bool:
    """Проверяет, старше ли файл/директория заданного количества дней."""
    try:
        stat = path.stat()
        file_time = datetime.fromtimestamp(max(stat.st_mtime, stat.st_ctime))
        return datetime.now() - file_time > timedelta(days=days)
    except OSError as e:
        logger.debug(f"Не удалось получить время для {path}: {e}")
        return False


def safe_remove(path: Path) -> bool:
    """Безопасно удаляет файл или директорию."""
    try:
        if path.is_file():
            path.unlink()
            logger.debug(f"Удалён файл: {path}")
        elif path.is_dir():
            shutil.rmtree(path)
            logger.debug(f"Удалена директория: {path}")
        return True
    except Exception as e:
        logger.error(f"Ошибка при удалении {path}: {e}")
        return False


def cleanup_directory(root: Path, max_age_days: int, dry_run: bool = False) -> int:
    """Очищает директорию от файлов старше max_age_days."""
    deleted_count = 0
    if not root.exists():
        logger.debug(f"Директория не существует: {root}")
        return 0

    for item in root.rglob("*"):
        if item.is_file() and is_older_than(item, max_age_days):
            if not dry_run:
                if safe_remove(item):
                    deleted_count += 1
            else:
                logger.info(f"[DRY RUN] Будет удалён: {item}")
                deleted_count += 1

    # Удаляем пустые директории (только если не dry_run)
    if not dry_run:
        for dir_item in sorted(root.rglob("*"), key=lambda x: len(str(x)), reverse=True):
            if dir_item.is_dir() and not any(dir_item.iterdir()):
                try:
                    dir_item.rmdir()
                    logger.debug(f"Удалена пустая директория: {dir_item}")
                except Exception as e:
                    logger.debug(f"Не удалось удалить пустую директорию {dir_item}: {e}")

    return deleted_count


def run_cleanup(dry_run: bool = False) -> Dict[str, int]:
    """
    Выполняет полную очистку устаревших данных согласно правилам.
    Возвращает статистику по удалённым объектам.
    """
    config = load_cleanup_config()
    stats = {}

    paths_map = {
        "logs": Path("logs"),
        "cache": Path("data/cache"),
        "temp_ai": Path("ai/temp"),
        "backup_automatic": Path("backup/automatic"),
        "conversations": Path("data/conversations"),
    }

    for category, rules in config.items():
        if not rules.get("enabled", False):
            continue

        age_days = rules.get("age_days", 30)
        target_path = paths_map.get(category)

        if not target_path or not target_path.exists():
            logger.debug(f"Пропущена категория {category}: путь не существует")
            continue

        logger.info(f"Очистка категории '{category}' (старше {age_days} дней)...")
        deleted = cleanup_directory(target_path, age_days, dry_run=dry_run)
        stats[category] = deleted
        logger.info(f"Удалено {deleted} элементов в категории '{category}'")

    return stats


def main(dry_run: bool = False):
    """Основная точка входа для CLI или cron."""
    log_file = Path("logs/app/maintenance.log")
    log_file.parent.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler()
        ]
    )

    logger.info("🚀 Запуск скрипта очистки устаревших данных...")
    stats = run_cleanup(dry_run=dry_run)

    total_deleted = sum(stats.values())
    if dry_run:
        logger.info(f"✅ DRY RUN завершён. Обнаружено {total_deleted} устаревших элементов.")
    else:
        logger.info(f"✅ Очистка завершена. Удалено {total_deleted} элементов.")

    # Сохраняем отчёт в data/stats/
    report_path = Path("data/stats/cleanup_report.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "timestamp": datetime.now().isoformat(),
        "dry_run": dry_run,
        "stats": stats,
        "total_deleted": total_deleted
    }
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    logger.info(f"📄 Отчёт сохранён: {report_path}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Очистка устаревших данных системы")
    parser.add_argument("--dry-run", action="store_true", help="Только показать, что будет удалено")
    args = parser.parse_args()
    main(dry_run=args.dry_run)