# AI_FREELANCE_AUTOMATION/ui/layouts/__init__.py
"""
Модуль инициализации компоновок (layouts) пользовательского интерфейса.

Этот пакет содержит все макеты окон приложения:
- Панель управления (dashboard)
- Управление заказами (jobs)
- Работа с клиентами (clients)
- Финансы (finances)
- Мониторинг системы (monitoring)
- Настройки (settings)

Импортирует все layout-классы для удобного централизованного доступа.
Поддерживает lazy-loading через явные импорты только при необходимости,
чтобы избежать циклических зависимостей и ускорить запуск UI.

Согласовано с архитектурой core/dependency/service_locator.py и ui/main_window.py.
"""

# Импорты организованы в порядке использования и алфавита
# Явные импорты вместо * для прозрачности и анализа типов

from .dashboard_layout import DashboardLayout
from .jobs_layout import JobsLayout
from .clients_layout import ClientsLayout
from .finances_layout import FinancesLayout
from .monitoring_layout import MonitoringLayout
from .settings_layout import SettingsLayout

# Публичный API модуля
__all__ = [
    "DashboardLayout",
    "JobsLayout",
    "ClientsLayout",
    "FinancesLayout",
    "MonitoringLayout",
    "SettingsLayout",
]

# Дополнительно: метаданные для внутренней интроспекции (опционально)
LAYOUT_REGISTRY = {
    "dashboard": DashboardLayout,
    "jobs": JobsLayout,
    "clients": ClientsLayout,
    "finances": FinancesLayout,
    "monitoring": MonitoringLayout,
    "settings": SettingsLayout,
}