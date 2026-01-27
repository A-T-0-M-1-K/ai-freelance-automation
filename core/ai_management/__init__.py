# AI_FREELANCE_AUTOMATION/core/ai_management/__init__.py
"""
AI Management Module — Entry point for AI model orchestration.

This package handles:
- Intelligent loading/unloading of AI models
- Runtime performance monitoring
- Memory-aware model optimization
- Registry of available models and their metadata
- Seamless integration with the core dependency and config systems

All public components are explicitly exported to avoid namespace pollution
and ensure clean imports across the system.
"""

from .intelligent_model_manager import IntelligentModelManager
from .model_registry import ModelRegistry
from .model_optimizer import ModelOptimizer
from .model_performance_monitor import ModelPerformanceMonitor
from .memory_monitor import MemoryMonitor
from .adaptive_model_loader import AdaptiveModelLoader
from .intelligent_model_manager import IntelligentModelManager
from .lazy_model_loader import LazyModelLoader
from .memory_monitor import MemoryMonitor
from .model_optimizer import ModelOptimizer
from .model_performance_monitor import ModelPerformanceMonitor
from .model_registry import ModelRegistry

# Optional: define __all__ for explicit public API
__all__ = [
    'AdaptiveModelLoader',  # Новый рекомендуемый загрузчик
    'IntelligentModelManager',
    'LazyModelLoader',
    'MemoryMonitor',
    'ModelOptimizer',
    'ModelPerformanceMonitor',
    'ModelRegistry'
]

# Глобальный экземпляр для использования в системе
adaptive_loader = AdaptiveModelLoader()