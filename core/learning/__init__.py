# AI_FREELANCE_AUTOMATION/core/learning/__init__.py
"""
Модуль непрерывного обучения (Continuous Learning)
Автономно улучшает качество работы системы на основе:
- обратной связи от клиентов
- анализа выполненных заказов
- метрик качества AI-моделей
- ошибок и их исправлений

Этот файл обеспечивает корректный импорт всех компонентов модуля
и гарантирует совместимость с общей архитектурой приложения.
"""

from .continuous_learning_system import ContinuousLearningSystem
from .feedback_analyzer import FeedbackAnalyzer
from .knowledge_base import KnowledgeBase
from .pattern_extractor import PatternExtractor

__all__ = [
    "ContinuousLearningSystem",
    "FeedbackAnalyzer",
    "KnowledgeBase",
    "PatternExtractor",
]

# Гарантируем, что модуль безопасен для импорта в любом порядке
# и не вызывает побочных эффектов при загрузке