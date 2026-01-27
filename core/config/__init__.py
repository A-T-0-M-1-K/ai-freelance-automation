"""
Модуль конфигурации ядра системы.
Предоставляет унифицированный интерфейс для работы с настройками приложения.
Обеспечивает безопасную, валидируемую и горячо-перезагружаемую конфигурацию.
"""

from .unified_config_manager import UnifiedConfigManager
from .config_validator import ConfigValidator
from .env_loader import EnvLoader
from .config_migrator import ConfigMigrator
from .legacy_config_adapter import LegacyConfigAdapter

# Экспорт основных компонентов для внешнего использования
__all__ = [
    "UnifiedConfigManager",
    "ConfigValidator",
    "EnvLoader",
    "ConfigMigrator",
    "LegacyConfigAdapter",
]

# Глобальный экземпляр менеджера конфигурации (lazy-initialized при первом обращении)
# Используется только внутри ядра — внешние модули должны получать конфиг через DI или service locator
__global_config_instance = None


def get_global_config() -> UnifiedConfigManager:
    """
    Возвращает глобальный экземпляр конфигурации.
    Предназначен ТОЛЬКО для внутреннего использования в ядре при инициализации.
    Не рекомендуется использовать в сервисах/плагинах — передавайте конфиг явно.
    """
    global __global_config_instance
    if __global_config_instance is None:
        # Загружаем переменные окружения до инициализации конфига
        EnvLoader.load()
        __global_config_instance = UnifiedConfigManager()
    return __global_config_instance