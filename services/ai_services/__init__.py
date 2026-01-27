"""
AI Services Package — Initialization Module

Этот модуль обеспечивает корректный импорт и экспорт всех AI-сервисов,
используемых в системе автономного фрилансера. Каждый сервис реализует
одну из ключевых функций: транскрибация, перевод, копирайтинг, редактура и суммаризация.

Соблюдены принципы:
- Чистый импорт без побочных эффектов (no side effects on import)
- Явный контроль экспорта через __all__
- Поддержка lazy loading при необходимости
- Совместимость с DI-контейнером из core/dependency/

Автоматически регистрирует все сервисы в Service Registry при первом обращении.
"""

from typing import TYPE_CHECKING

# Ленивые импорты для предотвращения циклических зависимостей и ускорения старта
if TYPE_CHECKING:
    from .transcription_service import TranscriptionService
    from .translation_service import TranslationService
    from .copywriting_service import CopywritingService
    from .editing_service import EditingService
    from .summarization_service import SummarizationService

# Экспорт публичного API
__all__ = [
    "TranscriptionService",
    "TranslationService",
    "CopywritingService",
    "EditingService",
    "SummarizationService",
]

# Регистрация сервисов в глобальном реестре (lazy initialization)
def _register_ai_services() -> None:
    """Регистрирует AI-сервисы в service_registry при первом использовании."""
    from ..service_registry import ServiceRegistry
    registry = ServiceRegistry.get_instance()

    # Проверяем, не зарегистрированы ли уже
    if not registry.has_service("TranscriptionService"):
        from .transcription_service import TranscriptionService
        registry.register_service("TranscriptionService", TranscriptionService)

    if not registry.has_service("TranslationService"):
        from .translation_service import TranslationService
        registry.register_service("TranslationService", TranslationService)

    if not registry.has_service("CopywritingService"):
        from .copywriting_service import CopywritingService
        registry.register_service("CopywritingService", CopywritingService)

    if not registry.has_service("EditingService"):
        from .editing_service import EditingService
        registry.register_service("EditingService", EditingService)

    if not registry.has_service("SummarizationService"):
        from .summarization_service import SummarizationService
        registry.register_service("SummarizationService", SummarizationService)

# Автоматическая регистрация при первом обращении к любому сервису
# (выполняется один раз благодаря флагу)
_registered = False

def _ensure_registered():
    global _registered
    if not _registered:
        _register_ai_services()
        _registered = True

# Обёртки для безопасного доступа (опционально, но рекомендуется)
def get_transcription_service():
    _ensure_registered()
    from ..service_registry import ServiceRegistry
    return ServiceRegistry.get_instance().get_service("TranscriptionService")

def get_translation_service():
    _ensure_registered()
    from ..service_registry import ServiceRegistry
    return ServiceRegistry.get_instance().get_service("TranslationService")

def get_copywriting_service():
    _ensure_registered()
    from ..service_registry import ServiceRegistry
    return ServiceRegistry.get_instance().get_service("CopywritingService")

def get_editing_service():
    _ensure_registered()
    from ..service_registry import ServiceRegistry
    return ServiceRegistry.get_instance().get_service("EditingService")

def get_summarization_service():
    _ensure_registered()
    from ..service_registry import ServiceRegistry
    return ServiceRegistry.get_instance().get_service("SummarizationService")