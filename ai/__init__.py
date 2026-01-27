# AI_FREELANCE_AUTOMATION/ai/__init__.py
"""
AI Module Initialization

This package serves as the legacy AI configuration and model storage layer.
All active AI logic has been migrated to `core/ai_management/`.
This module remains for backward compatibility and file organization only.

DO NOT implement new AI logic here.
Use `core.ai_management.intelligent_model_manager.IntelligentModelManager` instead.
"""

import logging
import os
from pathlib import Path

# Настройка логгера для модуля ai/
logger = logging.getLogger(__name__)

# Определяем базовый путь к папке ai/
AI_ROOT = Path(__file__).parent.resolve()

# Убедимся, что необходимые подкаталоги существуют (на случай первого запуска)
_REQUIRED_DIRS = ["logs", "temp", "models", "configs"]
for _dir in _REQUIRED_DIRS:
    dir_path = AI_ROOT / _dir
    if not dir_path.exists():
        dir_path.mkdir(parents=True, exist_ok=True)
        logger.debug(f"Created required AI directory: {dir_path}")

# Предотвращаем прямое использование этого модуля как точки входа
if __name__ == "__main__":
    logger.warning("The 'ai' package is not intended to be executed directly.")

# Экспорт только метаданных — НИКАКИХ активных компонентов не импортируется
__version__ = "1.0.0"
__author__ = "AI Freelance Automation Team"
__package_type__ = "legacy-ai-storage"

# Явно указываем, что модуль не предоставляет публичных классов или функций
__all__ = []

# Логирование инициализации (только при первом импорте)
logger.info("✅ Legacy AI module initialized (storage-only mode). "
            "Active AI logic resides in core/ai_management/.")

# Защита от непреднамеренного выполнения тяжелых операций
def __getattr__(name):
    """Prevent accidental access to undefined attributes."""
    raise AttributeError(
        f"Module 'ai' has no attribute '{name}'. "
        "This is a legacy storage package. Use 'core.ai_management' for AI operations."
    )