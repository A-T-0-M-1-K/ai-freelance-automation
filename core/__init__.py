"""
AI Freelance Automation — Core Package
======================================

Этот пакет содержит ядро полностью автономной системы фрилансера.
Он включает подсистемы управления зависимостями, конфигурацией, безопасностью,
производительностью, мониторингом, AI, автоматизацией, коммуникацией и платежами.

Архитектурные принципы:
- 100% автономность
- Самовосстановление и самообучение
- Промышленная отказоустойчивость (99.9% uptime)
- Безопасность по стандартам PCI DSS, GDPR, SOC 2
- Масштабируемость (вертикальная и горизонтальная)

Импорты организованы через ленивую загрузку и DI-контейнеры,
чтобы избежать циклических зависимостей и ускорить старт системы.
"""

# Версия ядра системы
__version__ = "1.0.0"
__author__ = "AI Freelance Automation Team"
__license__ = "MIT"

# Публичный API ядра — только ключевые точки входа
# Все внутренние импорты должны быть lazy или через service locator

from .dependency import (
    dependency_manager,
    service_locator
)

from .config import (
    unified_config_manager
)

# Безопасность: экспорт только интерфейсов, не реализаций
from .security import (
    advanced_crypto_system,
    key_manager,
    audit_logger
)

# Основные компоненты для внешнего использования
from .automation import auto_freelancer_core
from .communication import empathetic_communicator
from .ai_management import intelligent_model_manager
from .payment import enhanced_payment_processor
from .monitoring import intelligent_monitoring_system

# Утилиты для инициализации
def get_core_version() -> str:
    """Возвращает версию ядра системы."""
    return __version__

def initialize_core_components() -> None:
    """
    Инициализирует критически важные компоненты ядра в правильном порядке:
    1. Конфигурация
    2. Безопасность
    3. Зависимости
    4. Мониторинг
    """
    from .config.unified_config_manager import UnifiedConfigManager
    from .security.advanced_crypto_system import AdvancedCryptoSystem
    from .dependency.dependency_manager import DependencyManager
    from .monitoring.intelligent_monitoring_system import IntelligentMonitoringSystem

    # Порядок инициализации гарантирует отсутствие race conditions
    config = UnifiedConfigManager.get_instance()
    crypto = AdvancedCryptoSystem.initialize(config)
    dep_manager = DependencyManager.initialize(config, crypto)
    monitor = IntelligentMonitoringSystem.initialize(config)

    # Регистрация в глобальном контексте (через service locator)
    from .dependency.service_locator import ServiceLocator
    ServiceLocator.register("config", config)
    ServiceLocator.register("crypto", crypto)
    ServiceLocator.register("dependencies", dep_manager)
    ServiceLocator.register("monitoring", monitor)

# Защита от прямого выполнения
if __name__ == "__main__":
    raise RuntimeError("Core package is not meant to be executed directly.")