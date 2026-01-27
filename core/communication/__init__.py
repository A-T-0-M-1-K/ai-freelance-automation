"""
Модуль core.communication — централизованная точка импорта для подсистемы интеллектуальной коммуникации.

Отвечает за:
- Эмоционально-интеллектуальное общение с клиентами
- Анализ тональности и настроения
- Управление диалоговым контекстом
- Поддержку 50+ языков
- Автоматическую адаптацию стиля общения

Этот файл гарантирует корректную инициализацию модуля и предотвращает циклические импорты.
"""

from typing import TYPE_CHECKING

# Ленивая загрузка для избежания циклических зависимостей
if TYPE_CHECKING:
    from .empathetic_communicator import EmpatheticCommunicator
    from .sentiment_analyzer import SentimentAnalyzer
    from .tone_adjuster import ToneAdjuster
    from .context_manager import ContextManager
    from .multilingual_support import MultilingualSupport

# Публичный API модуля
__all__ = [
    "EmpatheticCommunicator",
    "SentimentAnalyzer",
    "ToneAdjuster",
    "ContextManager",
    "MultilingualSupport",
]

# Версия подсистемы коммуникации
__version__ = "1.0.0"

# Метаданные модуля
__author__ = "AI Freelance Automation Team"
__description__ = "Intelligent, empathetic, and multilingual client communication system"

# Инициализация модуля (выполняется один раз при первом импорте)
def _initialize_module():
    """Выполняет базовую инициализацию подсистемы коммуникации."""
    import logging
    logger = logging.getLogger("core.communication")
    logger.debug("✅ Communication subsystem initialized.")

# Запуск инициализации
_initialize_module()