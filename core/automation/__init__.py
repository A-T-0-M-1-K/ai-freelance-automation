# AI_FREELANCE_AUTOMATION/core/automation/__init__.py
"""
Модуль автоматизации фриланс-деятельности.
Содержит компоненты, отвечающие за автономное выполнение полного цикла работы фрилансера:
поиск заказов, принятие решений, выполнение задач, контроль качества, взаимодействие с клиентом.
"""

from .saga_orchestrator import SagaOrchestrator
from .auto_freelancer_core import AutoFreelancerCore
from .decision_engine import DecisionEngine
from .job_analyzer import JobAnalyzer
from .quality_controller import QualityController
from .reputation_manager import ReputationManager
from .task_orchestrator import TaskOrchestrator

# Совместимость: старые классы остаются доступными, но рекомендуется использовать SagaOrchestrator
__all__ = [
    'SagaOrchestrator',  # Новый рекомендуемый оркестратор
    'AutoFreelancerCore',
    'DecisionEngine',
    'JobAnalyzer',
    'QualityController',
    'ReputationManager',
    'TaskOrchestrator'
]
# Версия модуля (для внутреннего отслеживания)
__version__ = "1.0.0"