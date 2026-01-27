# AI_FREELANCE_AUTOMATION/core/performance/__init__.py
"""
Модуль производительности системы.
Содержит компоненты для интеллектуального кэширования, оптимизации памяти,
предсказания нагрузки и адаптивного управления ресурсами.

Этот модуль гарантирует:
- Минимальное потребление памяти при высокой загрузке
- Предиктивную подгрузку данных на основе поведения пользователя и заказов
- Автоматическую очистку устаревших или ненужных кэш-данных
- Интеграцию с системой мониторинга для динамической настройки стратегий

Автономность: работает без вмешательства пользователя.
Безопасность: не хранит чувствительные данные в открытом виде.
Совместимость: следует архитектуре DI через service locator и lazy loading.
"""

from .intelligent_cache_system import IntelligentCacheSystem
from .cache_performance_monitor import CachePerformanceMonitor
from .strategy_selector import StrategySelector
from .load_predictor import LoadPredictor
from .memory_optimizer import MemoryOptimizer

__all__ = [
    "IntelligentCacheSystem",
    "CachePerformanceMonitor",
    "StrategySelector",
    "LoadPredictor",
    "MemoryOptimizer",
]