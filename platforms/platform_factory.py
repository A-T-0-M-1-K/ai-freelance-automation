# platforms/platform_factory.py
"""
Platform Factory — централизованная фабрика для создания и управления интеграциями
с фриланс-платформами (Upwork, Freelance.ru, Kwork и др.).

Поддерживает:
- Динамическую загрузку платформ через плагины
- Единообразный интерфейс взаимодействия
- Изоляцию ошибок (падение одной платформы не ломает систему)
- Поддержку кастомных платформ через plugins/
"""

import logging
import importlib
from typing import Dict, Optional, Type, Any
from pathlib import Path

from core.config.unified_config_manager import UnifiedConfigManager
from core.dependency.service_locator import ServiceLocator
from core.security.advanced_crypto_system import AdvancedCryptoSystem

# Базовый интерфейс платформы (можно вынести в отдельный файл, но для простоты — здесь)
class BasePlatformClient:
    """Базовый абстрактный класс для всех платформ."""
    def __init__(self, config: dict, crypto: AdvancedCryptoSystem, services: ServiceLocator):
        self.config = config
        self.crypto = crypto
        self.services = services
        self.logger = logging.getLogger(f"Platform.{self.__class__.__name__}")

    async def authenticate(self) -> bool:
        raise NotImplementedError

    async def scrape_jobs(self) -> list:
        raise NotImplementedError

    async def place_bid(self, job_id: str, proposal: str, price: float) -> bool:
        raise NotImplementedError

    async def get_messages(self, job_id: str) -> list:
        raise NotImplementedError

    async def send_message(self, job_id: str, message: str) -> bool:
        raise NotImplementedError

    async def deliver_work(self, job_id: str, deliverables: dict) -> bool:
        raise NotImplementedError


class PlatformFactory:
    """
    Фабрика платформ. Создаёт экземпляры клиентов платформ на основе конфигурации.
    Поддерживает как встроенные, так и плагинные платформы.
    """

    # Встроенные платформы: имя → путь к модулю и классу
    BUILTIN_PLATFORMS = {
        "upwork": ("platforms.upwork.client", "UpworkClient"),
        "freelance_ru": ("platforms.freelance_ru.client", "FreelanceRuClient"),
        "kwork": ("platforms.kwork.client", "KworkClient"),
    }

    def __init__(
        self,
        config_manager: UnifiedConfigManager,
        crypto_system: AdvancedCryptoSystem,
        service_locator: ServiceLocator
    ):
        self.config_manager = config_manager
        self.crypto = crypto_system
        self.services = service_locator
        self._instances: Dict[str, BasePlatformClient] = {}
        self.logger = logging.getLogger("PlatformFactory")

    def get_platform(self, platform_name: str) -> Optional[BasePlatformClient]:
        """
        Возвращает экземпляр платформы по имени.
        Кэширует созданные экземпляры для повторного использования.
        """
        if platform_name in self._instances:
            return self._instances[platform_name]

        try:
            platform_config = self.config_manager.get_platform_config(platform_name)
            if not platform_config or not platform_config.get("enabled", False):
                self.logger.warning(f"Платформа '{platform_name}' отключена или не найдена в конфигурации.")
                return None

            client_class = self._load_platform_class(platform_name)
            if client_class is None:
                return None

            instance = client_class(
                config=platform_config,
                crypto=self.crypto,
                services=self.services
            )
            self._instances[platform_name] = instance
            self.logger.info(f"✅ Платформа '{platform_name}' успешно инициализирована.")
            return instance

        except Exception as e:
            self.logger.error(f"❌ Ошибка при инициализации платформы '{platform_name}': {e}", exc_info=True)
            return None

    def _load_platform_class(self, platform_name: str) -> Optional[Type[BasePlatformClient]]:
        """
        Загружает класс клиента платформы:
        - Сначала проверяет встроенные платформы
        - Затем ищет плагин в plugins/platform_plugins/
        """
        # 1. Встроенные платформы
        if platform_name in self.BUILTIN_PLATFORMS:
            module_path, class_name = self.BUILTIN_PLATFORMS[platform_name]
            try:
                module = importlib.import_module(module_path)
                return getattr(module, class_name)
            except (ImportError, AttributeError) as e:
                self.logger.error(f"Не удалось загрузить встроенную платформу '{platform_name}': {e}")
                return None

        # 2. Плагины (динамическая загрузка)
        plugin_path = Path("plugins") / "platform_plugins" / f"{platform_name}_plugin.py"
        if plugin_path.exists():
            try:
                spec = importlib.util.spec_from_file_location(f"{platform_name}_plugin", plugin_path)
                plugin_module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(plugin_module)
                # Ожидается, что плагин предоставляет класс с именем {PlatformName}Client
                class_name = f"{platform_name.capitalize()}Client"
                if hasattr(plugin_module, class_name):
                    return getattr(plugin_module, class_name)
                else:
                    self.logger.error(f"Плагин '{platform_name}' не содержит класс {class_name}")
                    return None
            except Exception as e:
                self.logger.error(f"Ошибка при загрузке плагина '{platform_name}': {e}", exc_info=True)
                return None

        self.logger.warning(f"Платформа '{platform_name}' не найдена ни среди встроенных, ни среди плагинов.")
        return None

    def list_available_platforms(self) -> list[str]:
        """Возвращает список всех доступных платформ (встроенных + плагинов)."""
        available = list(self.BUILTIN_PLATFORMS.keys())

        # Поиск плагинов
        plugin_dir = Path("plugins") / "platform_plugins"
        if plugin_dir.exists():
            for file in plugin_dir.glob("*_plugin.py"):
                name = file.stem.replace("_plugin", "")
                if name not in available:
                    available.append(name)

        return available

    def reload_platform(self, platform_name: str) -> bool:
        """Перезагружает платформу (например, после обновления конфигурации)."""
        if platform_name in self._instances:
            del self._instances[platform_name]
        return self.get_platform(platform_name) is not None