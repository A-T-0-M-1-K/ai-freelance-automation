# AI_FREELANCE_AUTOMATION/ui/main_window.py
"""
Главное окно пользовательского интерфейса автономного фрилансера.
Поддерживает адаптивный дизайн, переключение тем, виджеты и макеты.
"""

import sys
import logging
from typing import Optional, Dict, Any

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QStackedWidget, QMenuBar, QStatusBar, QMessageBox
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QIcon

# Локальные импорты — строго по структуре проекта
from .theme_manager import ThemeManager
from .components.dashboard_widgets import DashboardWidget
from .components.job_widgets import JobsWidget
from .components.client_widgets import ClientsWidget
from .components.finance_widgets import FinancesWidget
from .components.monitoring_widgets import MonitoringWidget
from .components.settings_widgets import SettingsWidget

from .layouts.dashboard_layout import DashboardLayout
from .layouts.jobs_layout import JobsLayout
from .layouts.clients_layout import ClientsLayout
from .layouts.finances_layout import FinancesLayout
from .layouts.monitoring_layout import MonitoringLayout
from .layouts.settings_layout import SettingsLayout

logger = logging.getLogger("UI.MainWindow")


class MainWindow(QMainWindow):
    """
    Главное окно приложения. Координирует все UI-компоненты.
    Поддерживает:
      - Переключение между вкладками (Dashboard, Заказы, Клиенты и т.д.)
      - Динамическую смену темы
      - Адаптивный интерфейс
      - Состояние загрузки и ошибки
    """

    # Сигналы для внутренней коммуникации
    theme_changed = pyqtSignal(str)
    layout_changed = pyqtSignal(str)

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__()
        self.config = config or {}
        self.setWindowTitle("AI Freelance Automation")
        self.setWindowIcon(QIcon("assets/icons/app_icon.png"))
        self.setMinimumSize(1024, 768)

        # Инициализация подсистем
        self.theme_manager = ThemeManager(self.config.get("ui", {}).get("theme", "dark"))
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)

        # Макеты и виджеты
        self.main_layout = QVBoxLayout(self.central_widget)
        self.content_stack = QStackedWidget()
        self.nav_bar = self._create_navigation_bar()
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        # Внутренние компоненты
        self.widgets: Dict[str, QWidget] = {}
        self.layouts: Dict[str, Any] = {}

        self._init_ui_components()
        self._apply_theme()
        self._setup_connections()

        logger.info("✅ Main window initialized successfully.")

    def _create_navigation_bar(self) -> QWidget:
        """Создает панель навигации (можно заменить на QTabBar или sidebar)."""
        from PyQt5.QtWidgets import QPushButton
        nav_widget = QWidget()
        nav_layout = QHBoxLayout(nav_widget)
        nav_layout.setContentsMargins(0, 0, 0, 0)

        self.nav_buttons = {}
        tabs = ["dashboard", "jobs", "clients", "finances", "monitoring", "settings"]
        for tab in tabs:
            btn = QPushButton(tab.capitalize())
            btn.setObjectName(f"nav_{tab}")
            btn.clicked.connect(lambda _, t=tab: self._switch_view(t))
            nav_layout.addWidget(btn)
            self.nav_buttons[tab] = btn

        return nav_widget

    def _init_ui_components(self):
        """Инициализирует все UI-виджеты и макеты."""
        try:
            # Виджеты
            self.widgets["dashboard"] = DashboardWidget()
            self.widgets["jobs"] = JobsWidget()
            self.widgets["clients"] = ClientsWidget()
            self.widgets["finances"] = FinancesWidget()
            self.widgets["monitoring"] = MonitoringWidget()
            self.widgets["settings"] = SettingsWidget()

            # Макеты (если нужны отдельные логики размещения)
            self.layouts["dashboard"] = DashboardLayout(self.widgets["dashboard"])
            self.layouts["jobs"] = JobsLayout(self.widgets["jobs"])
            self.layouts["clients"] = ClientsLayout(self.widgets["clients"])
            self.layouts["finances"] = FinancesLayout(self.widgets["finances"])
            self.layouts["monitoring"] = MonitoringLayout(self.widgets["monitoring"])
            self.layouts["settings"] = SettingsLayout(self.widgets["settings"])

            # Добавляем в стек
            for name, widget in self.widgets.items():
                self.content_stack.addWidget(widget)

            # Основной макет
            self.main_layout.addWidget(self.nav_bar)
            self.main_layout.addWidget(self.content_stack)

            # По умолчанию — Dashboard
            self._switch_view("dashboard")

        except Exception as e:
            logger.error(f"❌ Failed to initialize UI components: {e}", exc_info=True)
            QMessageBox.critical(self, "Ошибка инициализации", f"Не удалось загрузить интерфейс:\n{str(e)}")
            sys.exit(1)

    def _switch_view(self, view_name: str):
        """Переключает активную вкладку."""
        if view_name not in self.widgets:
            logger.warning(f"⚠️ Unknown view requested: {view_name}")
            return

        widget = self.widgets[view_name]
        self.content_stack.setCurrentWidget(widget)
        self.status_bar.showMessage(f"Переключено на: {view_name.capitalize()}")
        logger.debug(f"Switched to view: {view_name}")

        # Обновляем стиль кнопок
        for name, btn in self.nav_buttons.items():
            if name == view_name:
                btn.setStyleSheet("background-color: #4A90E2; color: white;")
            else:
                btn.setStyleSheet("")

    def _apply_theme(self):
        """Применяет текущую тему ко всему интерфейсу."""
        try:
            stylesheet = self.theme_manager.get_stylesheet()
            self.setStyleSheet(stylesheet)
            logger.info(f"🎨 Theme applied: {self.theme_manager.current_theme}")
        except Exception as e:
            logger.error(f"⚠️ Failed to apply theme: {e}", exc_info=True)

    def _setup_connections(self):
        """Настраивает сигналы/слоты."""
        self.theme_manager.theme_changed.connect(self._on_theme_change)

    def _on_theme_change(self, theme_name: str):
        """Обработчик смены темы."""
        self._apply_theme()
        self.theme_changed.emit(theme_name)

    def closeEvent(self, event):
        """Корректное завершение работы."""
        logger.info("CloseOperation: Closing main window...")
        reply = QMessageBox.question(
            self,
            "Выход",
            "Завершить работу автономного фрилансера?\nВсе активные задачи будут сохранены.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            event.accept()
            logger.info("CloseOperation: Application closed by user.")
        else:
            event.ignore()


# Для запуска в standalone-режиме (только для тестирования UI)
if __name__ == "__main__":
    from PyQt5.QtWidgets import QApplication
    import json
    import os

    logging.basicConfig(level=logging.DEBUG)

    app = QApplication(sys.argv)

    # Загружаем конфиг, если есть
    config_path = os.path.join(os.path.dirname(__file__), "..", "config", "ui_config.json")
    config = {}
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

    window = MainWindow(config=config)
    window.show()
    sys.exit(app.exec_())