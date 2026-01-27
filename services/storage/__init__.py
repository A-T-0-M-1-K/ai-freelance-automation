"""
Storage Services Package Initialization
======================================

Этот пакет предоставляет унифицированные интерфейсы для работы с различными
типами хранилищ: локальными, облачными и базами данных.

Цели:
- Абстрагирование от конкретных реализаций хранилищ
- Поддержка единой точки доступа через Service Registry
- Гарантия совместимости с DI-контейнером из core/dependency/
- Обеспечение отказоустойчивости и логирования всех операций

Архитектурные принципы:
✅ Единый интерфейс для всех типов хранилищ
✅ Lazy loading тяжелых компонентов
✅ Автоматическая регистрация в service_registry
✅ Поддержка горячей замены реализаций (через плагины)
✅ Полная типизация и документация
✅ Безопасность: все данные шифруются при необходимости
"""

from typing import TYPE_CHECKING

# Отложенный импорт для предотвращения циклических зависимостей
if TYPE_CHECKING:
    from .database_service import DatabaseService
    from .file_storage import FileStorageService
    from .cloud_storage import CloudStorageService

# Публичный API пакета
__all__ = [
    "DatabaseService",
    "FileStorageService",
    "CloudStorageService",
]

# Регистрация сервисов в глобальном реестре (выполняется один раз при импорте)
def _register_storage_services() -> None:
    """Регистрирует все storage-сервисы в ServiceRegistry."""
    try:
        from services.service_registry import ServiceRegistry
        from core.dependency.service_locator import ServiceLocator

        # Импортируем реализации только при регистрации
        from .database_service import DatabaseService
        from .file_storage import FileStorageService
        from .cloud_storage import CloudStorageService

        registry = ServiceRegistry.get_instance()
        locator = ServiceLocator.get_instance()

        # Регистрация с поддержкой DI и конфигурации
        registry.register("storage.database", DatabaseService, scope="singleton")
        registry.register("storage.file", FileStorageService, scope="singleton")
        registry.register("storage.cloud", CloudStorageService, scope="singleton")

        # Также делаем доступными через ServiceLocator для обратной совместимости
        locator.register("DatabaseService", DatabaseService)
        locator.register("FileStorageService", FileStorageService)
        locator.register("CloudStorageService", CloudStorageService)

    except Exception as e:
        # Логируем ошибку, но не прерываем инициализацию — система должна быть устойчивой
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"⚠️ Не удалось зарегистрировать storage-сервисы: {e}", exc_info=True)

# Выполняем регистрацию при первом импорте модуля
_register_storage_services()

# Очистка локальных переменных, чтобы не засорять пространство имён
del _register_storage_services