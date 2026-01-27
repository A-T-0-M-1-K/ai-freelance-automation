# AI_FREELANCE_AUTOMATION/core/monitoring/__init__.py
"""
Модуль мониторинга — точка импорта для подсистемы интеллектуального наблюдения.

Обеспечивает:
- Единый интерфейс для импорта компонентов мониторинга
- Защиту от циклических импортов
- Ленивую загрузку тяжелых модулей при необходимости
- Соответствие архитектуре ядра (core/)

Этот файл НЕ содержит логики — только безопасные импорты и метаданные.
"""

# Указываем явно, что экспортируем
__all__ = [
    "IntelligentMonitoringSystem",
    "AnomalyDetection",
    "ThresholdManager",
    "TrendAnalyzer",
    "ResourceOptimizer",
    "AlertManager",
    "MetricsCollector",
]

# Ленивые импорты через функции или отложенные импорты не используются здесь,
# так как __init__.py должен быть легковесным и не вызывать побочных эффектов.
# Все тяжелые операции происходят внутри самих модулей при их прямом использовании.

from .intelligent_monitoring_system import IntelligentMonitoringSystem
from .anomaly_detection import AnomalyDetection
from .threshold_manager import ThresholdManager
from .trend_analyzer import TrendAnalyzer
from .resource_optimizer import ResourceOptimizer
from .alert_manager import AlertManager
from .metrics_collector import MetricsCollector

# Версия подсистемы мониторинга (для внутренней совместимости)
__version__ = "1.0.0"