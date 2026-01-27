"""
Инициализация модуля интеграции с платформой Freelance.ru.

Этот файл обеспечивает:
- Корректный импорт всех компонентов модуля.
- Единообразный интерфейс для внешнего использования.
- Поддержку lazy loading и изоляцию от конфликтов.
- Совместимость с platform_factory и plugin system.

Автоматически регистрирует модуль в системе плагинов при импорте,
если используется через `platform_factory.py`.
"""

from typing import TYPE_CHECKING

# Защита от циклических импортов и ускорение загрузки
if TYPE_CHECKING:
    from .client import FreelanceRuClient
    from .scraper import FreelanceRuScraper
    from .api_wrapper import FreelanceRuAPIWrapper

# Публичный API модуля
__all__ = [
    "FreelanceRuClient",
    "FreelanceRuScraper",
    "FreelanceRuAPIWrapper",
]

# Ленивая загрузка классов (чтобы избежать тяжелых импортов на старте)
def __getattr__(name):
    if name == "FreelanceRuClient":
        from .client import FreelanceRuClient
        return FreelanceRuClient
    elif name == "FreelanceRuScraper":
        from .scraper import FreelanceRuScraper
        return FreelanceRuScraper
    elif name == "FreelanceRuAPIWrapper":
        from .api_wrapper import FreelanceRuAPIWrapper
        return FreelanceRuAPIWrapper
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")

# Метаданные модуля (для диагностики и мониторинга)
__platform_name__ = "freelance.ru"
__platform_version__ = "1.0.0"
__supports_api__ = True
__supports_scraping__ = True
__auth_methods__ = ["session", "cookies"]
__capabilities__ = {
    "job_search": True,
    "bid_submission": True,
    "messaging": True,
    "contract_management": True,
    "payment_tracking": False,  # через внешние системы
}

# Регистрация в глобальном реестре платформ (опционально, через factory)
try:
    from ..platform_factory import register_platform
    register_platform("freelance_ru", __name__)
except ImportError:
    # Допустимо при частичной загрузке или тестировании
    pass