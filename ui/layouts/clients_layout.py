# AI_FREELANCE_AUTOMATION/ui/layouts/clients_layout.py
"""
Клиентский макет интерфейса — отображает список клиентов, историю взаимодействий,
статус текущих заказов и инструменты для управления отношениями.

Следует принципам:
- Разделение логики и представления (MVC-like)
- Поддержка тем оформления
- Адаптивность к разным режимам (compact, extended, expert)
- Интеграция с core через service locator
"""

import logging
from typing import Optional, Dict, Any, List
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QTabWidget,
    QLabel, QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QTextEdit, QFrame
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont

from core.dependency.service_locator import ServiceLocator
from ui.components.client_widgets import (
    ClientProfileWidget,
    ClientCommunicationWidget,
    ClientProjectsWidget,
    ClientFinancialsWidget
)
from ui.theme_manager import ThemeManager


class ClientsLayout(QWidget):
    """
    Основной макет для вкладки 'Клиенты'.
    Состоит из:
      - Списка клиентов (слева)
      - Детального просмотра (справа): профиль, переписка, проекты, финансы
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.logger = logging.getLogger("ClientsLayout")
        self.service_locator = ServiceLocator()
        self.theme_manager = ThemeManager()

        # Инициализация UI
        self._init_ui()
        self._apply_theme()
        self._load_clients()

        self.logger.info("ClientsLayout initialized successfully.")

    def _init_ui(self) -> None:
        """Инициализация компонентов интерфейса."""
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        # Заголовок
        title_label = QLabel("Мои клиенты")
        title_label.setFont(QFont("Segoe UI", 16, QFont.Bold))
        title_label.setAlignment(Qt.AlignLeft)
        main_layout.addWidget(title_label)

        # Горизонтальный разделитель: список + детали
        splitter = QSplitter(Qt.Horizontal)

        # Левая панель: таблица клиентов
        self.clients_table = self._create_clients_table()
        splitter.addWidget(self.clients_table)

        # Правая панель: детали клиента
        self.details_tabs = QTabWidget()
        self.details_tabs.addTab(ClientProfileWidget(), "Профиль")
        self.details_tabs.addTab(ClientCommunicationWidget(), "Переписка")
        self.details_tabs.addTab(ClientProjectsWidget(), "Проекты")
        self.details_tabs.addTab(ClientFinancialsWidget(), "Финансы")
        self.details_tabs.setTabPosition(QTabWidget.North)
        splitter.addWidget(self.details_tabs)

        # Пропорции: 30% / 70%
        splitter.setSizes([300, 700])
        main_layout.addWidget(splitter)

        # Кнопки действий
        actions_layout = QHBoxLayout()
        refresh_btn = QPushButton("Обновить")
        refresh_btn.clicked.connect(self._load_clients)
        actions_layout.addWidget(refresh_btn)
        actions_layout.addStretch()

        main_layout.addLayout(actions_layout)
        self.setLayout(main_layout)

    def _create_clients_table(self) -> QTableWidget:
        """Создает таблицу клиентов."""
        table = QTableWidget()
        table.setColumnCount(5)
        table.setHorizontalHeaderLabels(["ID", "Имя", "Платформа", "Активных заказов", "Репутация"])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.SingleSelection)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.cellClicked.connect(self._on_client_selected)
        return table

    def _load_clients(self) -> None:
        """Загружает клиентов из сервиса управления клиентами."""
        try:
            client_service = self.service_locator.get_service("client_service")
            clients: List[Dict[str, Any]] = client_service.get_all_clients()

            self.clients_table.setRowCount(len(clients))
            for row, client in enumerate(clients):
                self.clients_table.setItem(row, 0, QTableWidgetItem(str(client.get("id", ""))))
                self.clients_table.setItem(row, 1, QTableWidgetItem(client.get("name", "—")))
                self.clients_table.setItem(row, 2, QTableWidgetItem(client.get("platform", "—")))
                self.clients_table.setItem(row, 3, QTableWidgetItem(str(client.get("active_jobs", 0))))
                self.clients_table.setItem(row, 4, QTableWidgetItem(f"{client.get('reputation', 0):.1f}"))

            self.logger.debug(f"Loaded {len(clients)} clients.")
        except Exception as e:
            self.logger.error(f"Failed to load clients: {e}", exc_info=True)
            # В реальном приложении: показать уведомление через notification_service

    def _on_client_selected(self, row: int, column: int) -> None:
        """Обработчик выбора клиента в таблице."""
        client_id = self.clients_table.item(row, 0).text()
        self.logger.info(f"Client selected: {client_id}")

        # Обновляем все вкладки деталей
        for i in range(self.details_tabs.count()):
            widget = self.details_tabs.widget(i)
            if hasattr(widget, "load_client_data"):
                widget.load_client_data(client_id)

    def _apply_theme(self) -> None:
        """Применяет текущую тему оформления."""
        theme = self.theme_manager.get_current_theme()
        palette = self.palette()
        palette.setColor(self.backgroundRole(), theme["background"])
        palette.setColor(self.foregroundRole(), theme["text"])
        self.setPalette(palette)

        # Применить стиль к таблице
        self.clients_table.setStyleSheet(f"""
            QTableWidget {{
                background-color: {theme["surface"]};
                color: {theme["text"]};
                gridline-color: {theme["divider"]};
            }}
            QHeaderView::section {{
                background-color: {theme["header"]};
                color: {theme["text"]};
                padding: 4px;
                border: 1px solid {theme["divider"]};
            }}
        """)

    def refresh(self) -> None:
        """Публичный метод для обновления данных."""
        self._load_clients()