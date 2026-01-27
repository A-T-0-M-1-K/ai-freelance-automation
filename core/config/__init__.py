"""
Модуль конфигурации ядра системы.
Предоставляет унифицированный интерфейс для работы с настройками приложения.
Обеспечивает безопасную, валидируемую и горячо-перезагружаемую конфигурацию.
"""
from typing import Dict

from .unified_config_manager import UnifiedConfigManager
from .config_validator import ConfigValidator
from .env_loader import EnvLoader
from .config_migrator import ConfigMigrator
from .legacy_config_adapter import LegacyConfigAdapter
from .hierarchical_config_manager import HierarchicalConfigManager
from .config_validator import ConfigValidator

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


class UnifiedConfigManager(HierarchicalConfigManager):
    """Обратно совместимая обертка для существующего кода"""

    def __init__(self, config_dir: str = "config"):
        super().__init__(base_path=".")
        self.load_all_layers()

    # Методы для совместимости со старым интерфейсом
    def get_config(self, section: str) -> Dict:
        return self.get(section, {})

    def set_config(self, section: str, data: Dict):
        for key, value in data.items():
            self.set(f"{section}.{key}", value)

    def save_config(self):
        # Автоматическое сохранение в .env.local
        pass


# Глобальный экземпляр для использования в системе
config_manager = UnifiedConfigManager()

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