# AI_FREELANCE_AUTOMATION/core/dependency/dependency_manager.py
"""
Dependency Manager — центральный контейнер внедрения зависимостей (DI Container).
Обеспечивает:
- Устранение циклических импортов
- Ленивую инициализацию тяжелых компонентов
- Единый доступ к сервисам по интерфейсам
- Поддержку hot-reload и self-healing
- Безопасность через изоляцию и проверку типов

Следует принципу: "Зависимости создаются один раз, живут всё время работы системы".
"""

import logging
from typing import Any, Dict, Optional, Type, Callable, Union
from threading import Lock

from core.dependency.service_locator import ServiceLocator


class DependencyManager:
    """
    Основной DI-контейнер системы.
    Регистрирует фабрики сервисов и предоставляет их экземпляры по запросу.
    Гарантирует синглтонность (по умолчанию) и thread-safe поведение.
    """

    def __init__(self):
        self._logger = logging.getLogger("DependencyManager")
        self._factories: Dict[str, Callable[[], Any]] = {}
        self._instances: Dict[str, Any] = {}
        self._locks: Dict[str, Lock] = {}
        self._locator: Optional[ServiceLocator] = None
        self._is_initialized = False

    def register(
        self,
        name: str,
        factory: Callable[[], Any],
        singleton: bool = True
    ) -> None:
        """
        Регистрирует фабрику для создания сервиса.

        :param name: Уникальное имя сервиса (например, 'config', 'crypto', 'decision_engine')
        :param factory: Функция без аргументов, возвращающая экземпляр сервиса
        :param singleton: Если True — возвращает один и тот же экземпляр при каждом вызове
        """
        if not callable(factory):
            raise ValueError(f"Factory for '{name}' must be callable")
        if name in self._factories:
            self._logger.warning(f"Перерегистрация сервиса: {name}")
        self._factories[name] = factory
        if singleton:
            self._locks[name] = Lock()
        self._logger.debug(f"Зарегистрирован сервис: {name} (singleton={singleton})")

    def get(self, name: str) -> Any:
        """
        Получает экземпляр сервиса по имени.
        Для singleton-сервисов гарантируется один экземпляр.
        Для не-singleton — каждый вызов создаёт новый объект.

        :raises KeyError: если сервис не зарегистрирован
        :raises RuntimeError: если возникла ошибка при создании
        """
        if name not in self._factories:
            raise KeyError(f"Сервис '{name}' не зарегистрирован в DependencyManager")

        factory = self._factories[name]

        # Проверяем, singleton ли это
        is_singleton = name in self._locks

        if is_singleton:
            if name in self._instances:
                return self._instances[name]

            with self._locks[name]:
                # Двойная проверка на случай гонки потоков
                if name in self._instances:
                    return self._instances[name]

                try:
                    instance = factory()
                    self._instances[name] = instance
                    self._logger.info(f"✅ Инициализирован singleton-сервис: {name}")
                    return instance
                except Exception as e:
                    self._logger.error(f"💥 Ошибка при создании сервиса '{name}': {e}", exc_info=True)
                    raise RuntimeError(f"Не удалось создать сервис '{name}': {str(e)}") from e

        else:
            # Non-singleton: создаём новый экземпляр каждый раз
            try:
                instance = factory()
                self._logger.debug(f"🆕 Создан новый экземпляр сервиса: {name}")
                return instance
            except Exception as e:
                self._logger.error(f"💥 Ошибка при создании non-singleton сервиса '{name}': {e}", exc_info=True)
                raise RuntimeError(f"Не удалось создать non-singleton сервис '{name}': {str(e)}") from e

    def has(self, name: str) -> bool:
        """Проверяет, зарегистрирован ли сервис."""
        return name in self._factories

    def set_service_locator(self, locator: ServiceLocator) -> None:
        """Привязывает ServiceLocator для обратной совместимости."""
        self._locator = locator
        self._logger.debug("ServiceLocator привязан к DependencyManager")

    def initialize_core_services(self) -> None:
        """
        Инициализирует критически важные сервисы на старте системы.
        Вызывается один раз из ApplicationCore.
        """
        if self._is_initialized:
            return

        core_services = ["config", "crypto", "monitoring", "health"]
        for svc in core_services:
            if self.has(svc):
                self.get(svc)  # Принудительная инициализация

        self._is_initialized = True
        self._logger.info("✅ Все core-сервисы инициализированы")

    def reset_instance(self, name: str) -> None:
        """
        Сбрасывает экземпляр singleton-сервиса (для self-healing или hot-reload).
        Новый экземпляр будет создан при следующем вызове get().
        """
        if name in self._instances:
            del self._instances[name]
            self._logger.info(f"🔄 Сброшен экземпляр сервиса: {name}")

    def shutdown(self) -> None:
        """Корректное завершение всех управляемых сервисов (если они поддерживают close())."""
        self._logger.info("🛑 Завершение работы DependencyManager...")
        for name, instance in self._instances.items():
            if hasattr(instance, 'shutdown') and callable(getattr(instance, 'shutdown')):
                try:
                    instance.shutdown()
                    self._logger.debug(f"Выполнен shutdown для сервиса: {name}")
                except Exception as e:
                    self._logger.warning(f"Ошибка при shutdown сервиса {name}: {e}")
        self._instances.clear()
        self._logger.info("✅ DependencyManager завершил работу")