# AI_FREELANCE_AUTOMATION/core/automation/__init__.py
"""
Модуль автоматизации фриланс-деятельности.
Содержит компоненты, отвечающие за автономное выполнение полного цикла работы фрилансера:
поиск заказов, принятие решений, выполнение задач, контроль качества, взаимодействие с клиентом.
"""

from .auto_freelancer_core import AutoFreelancerCore
from .job_analyzer import JobAnalyzer
from .decision_engine import DecisionEngine
from .task_orchestrator import TaskOrchestrator
from .quality_controller import QualityController
from .reputation_manager import ReputationManager

# Публичный API модуля
__all__ = [
    "AutoFreelancerCore",
    "JobAnalyzer",
    "DecisionEngine",
    "TaskOrchestrator",
    "QualityController",
    "ReputationManager",
]

# Версия модуля (для внутреннего отслеживания)
__version__ = "1.0.0"