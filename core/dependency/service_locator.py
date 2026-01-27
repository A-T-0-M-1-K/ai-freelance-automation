# core/dependency/service_locator.py
"""
Service Locator — централизованный реестр сервисов с поддержкой ленивой инициализации,
многопоточной безопасности и hot-reload.

Используется как fallback при невозможности внедрения через конструктор (например, в плагинах).
Рекомендуется использовать только там, где DI невозможен.
"""

import logging
import threading
from typing import Any, Callable, Dict, Optional, Type
from functools import wraps

# Локальный импорт для избежания циклических зависимостей
from core.config.unified_config_manager import UnifiedConfigManager
from core.security.advanced_crypto_system import AdvancedCryptoSystem

logger = logging.getLogger("ServiceLocator")


class ServiceLocator:
    """
    Thread-safe singleton service locator with lazy instantiation and lifecycle control.
    """

    _instance: Optional["ServiceLocator"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "ServiceLocator":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._services: Dict[str, Any] = {}
        self._factories: Dict[str, Callable[[], Any]] = {}
        self._singleton_flags: Dict[str, bool] = {}
        self._lock = threading.RLock()
        self._initialized = True

    def register_service(
        self,
        name: str,
        factory: Callable[[], Any],
        singleton: bool = True,
        override: bool = False
    ) -> None:
        """
        Регистрирует сервис по имени.

        :param name: Уникальное имя сервиса (обычно FQN или alias)
        :param factory: Фабричная функция без аргументов, возвращающая экземпляр
        :param singleton: Если True — создаётся один раз и кэшируется
        :param override: Разрешить перезапись существующего сервиса
        """
        with self._lock:
            if name in self._services or name in self._factories:
                if not override:
                    raise ValueError(f"Service '{name}' already registered. Use override=True to replace.")
                logger.warning(f"⚠️ Overriding existing service: {name}")

            self._factories[name] = factory
            self._singleton_flags[name] = singleton
            # Очистка старого экземпляра, если был
            self._services.pop(name, None)
            logger.debug(f"✅ Registered service: {name} (singleton={singleton})")

    def get_service(self, name: str) -> Any:
        """
        Получает экземпляр сервиса по имени.
        При первом вызове — создаёт через фабрику.
        """
        with self._lock:
            if name in self._services:
                return self._services[name]

            if name not in self._factories:
                raise KeyError(f"Service '{name}' is not registered in ServiceLocator.")

            factory = self._factories[name]
            instance = factory()

            if self._singleton_flags.get(name, True):
                self._services[name] = instance

            logger.debug(f"🔧 Instantiated service: {name}")
            return instance

    def has_service(self, name: str) -> bool:
        """Проверяет, зарегистрирован ли сервис."""
        return name in self._factories

    def unregister_service(self, name: str) -> None:
        """Удаляет сервис из реестра (для hot-swap или очистки)."""
        with self._lock:
            self._factories.pop(name, None)
            self._services.pop(name, None)
            self._singleton_flags.pop(name, None)
            logger.info(f"🗑️ Unregistered service: {name}")

    def reset(self) -> None:
        """Полный сброс всех сервисов (только для тестов!)."""
        with self._lock:
            self._services.clear()
            self._factories.clear()
            self._singleton_flags.clear()
            logger.warning("💥 ServiceLocator reset complete (TEST MODE ONLY)")


# Глобальная точка доступа (безопасна благодаря thread-safe singleton)
def get_service(name: str) -> Any:
    """Удобная глобальная функция для получения сервиса."""
    locator = ServiceLocator()
    return locator.get_service(name)


# Декоратор для автоматической регистрации в ServiceLocator
def register_in_locator(name: str, singleton: bool = True):
    """
    Декоратор для автоматической регистрации класса как сервиса.

    Пример:
        @register_in_locator("my_service")
        class MyService:
            pass
    """
    def decorator(cls: Type[Any]) -> Type[Any]:
        locator = ServiceLocator()

        def factory() -> Any:
            # Автоматическое внедрение известных системных зависимостей
            # Это можно расширить до полного DI контейнера позже
            init_kwargs = {}
            if hasattr(cls, "__init__"):
                import inspect
                sig = inspect.signature(cls.__init__)
                for param_name in sig.parameters:
                    if param_name == "self":
                        continue
                    if param_name == "config":
                        init_kwargs[param_name] = UnifiedConfigManager()
                    elif param_name == "crypto":
                        init_kwargs[param_name] = AdvancedCryptoSystem()
                    # Можно добавить другие системные зависимости по имени параметра
            return cls(**init_kwargs)

        locator.register_service(name, factory, singleton=singleton)
        return cls
    return decorator


# Инициализация базовых системных сервисов (вызывается один раз при старте)
def initialize_core_services() -> None:
    """Регистрирует ключевые системные сервисы, необходимые для работы ядра."""
    locator = ServiceLocator()

    # Регистрация конфигурации и криптосистемы как синглтонов
    locator.register_service("config", UnifiedConfigManager, singleton=True)
    locator.register_service("crypto", AdvancedCryptoSystem, singleton=True)

    logger.info("🔐 Core system services registered in ServiceLocator")