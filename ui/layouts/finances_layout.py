# AI_FREELANCE_AUTOMATION/ui/layouts/finances_layout.py
"""
Финансовый макет интерфейса — отображает доходы, расходы, транзакции,
счета, налоги и аналитику по финансам автономного фрилансера.
Интегрируется с core.payment и data/finances/.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from PyQt5.QtWidgets import (
    QGridLayout,
    QGroupBox,
    QLabel,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from PyQt5.QtCore import Qt

if TYPE_CHECKING:
    from ui.theme_manager import ThemeManager
    from services.storage.database_service import DatabaseService

logger = logging.getLogger("FinancesLayout")


class FinancesLayout(QWidget):
    """
    Основной макет для вкладки 'Финансы'.
    Содержит подвкладки: Обзор, Транзакции, Счета, Налоги, Аналитика.
    """

    def __init__(
        self,
        theme_manager: Optional["ThemeManager"] = None,
        db_service: Optional["DatabaseService"] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.theme_manager = theme_manager
        self.db_service = db_service
        self._tabs: Dict[str, QWidget] = {}
        self._init_ui()
        logger.info("✅ FinancesLayout initialized")

    def _init_ui(self) -> None:
        """Инициализация пользовательского интерфейса."""
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(10, 10, 10, 10)

        # Вкладки
        self.tab_widget = QTabWidget()
        self._create_overview_tab()
        self._create_transactions_tab()
        self._create_invoices_tab()
        self._create_taxes_tab()
        self._create_analytics_tab()

        main_layout.addWidget(self.tab_widget)
        self.setLayout(main_layout)

        # Применить тему, если доступна
        if self.theme_manager:
            self.apply_theme()

    def _create_overview_tab(self) -> None:
        """Создает вкладку 'Обзор' — сводка по финансам."""
        tab = QWidget()
        layout = QGridLayout()

        # Пример меток (в реальности данные будут загружаться из БД)
        layout.addWidget(QLabel("Общий доход:"), 0, 0)
        layout.addWidget(QLabel("0.00 USD"), 0, 1, alignment=Qt.AlignRight)

        layout.addWidget(QLabel("Выполнено заказов:"), 1, 0)
        layout.addWidget(QLabel("0"), 1, 1, alignment=Qt.AlignRight)

        layout.addWidget(QLabel("Ожидаемые платежи:"), 2, 0)
        layout.addWidget(QLabel("0.00 USD"), 2, 1, alignment=Qt.AlignRight)

        layout.addWidget(QLabel("Налоги к уплате:"), 3, 0)
        layout.addWidget(QLabel("0.00 USD"), 3, 1, alignment=Qt.AlignRight)

        tab.setLayout(layout)
        self._tabs["overview"] = tab
        self.tab_widget.addTab(tab, "📊 Обзор")

    def _create_transactions_tab(self) -> None:
        """Создает вкладку 'Транзакции'."""
        tab = QGroupBox("История транзакций")
        layout = QVBoxLayout()
        layout.addWidget(QLabel("Загрузка транзакций..."))
        tab.setLayout(layout)
        self._tabs["transactions"] = tab
        self.tab_widget.addTab(tab, "💳 Транзакции")

    def _create_invoices_tab(self) -> None:
        """Создает вкладку 'Счета'."""
        tab = QGroupBox("Выставленные и оплаченные счета")
        layout = QVBoxLayout()
        layout.addWidget(QLabel("Список счетов будет здесь"))
        tab.setLayout(layout)
        self._tabs["invoices"] = tab
        self.tab_widget.addTab(tab, "🧾 Счета")

    def _create_taxes_tab(self) -> None:
        """Создает вкладку 'Налоги'."""
        tab = QGroupBox("Налоговые обязательства")
        layout = QVBoxLayout()
        layout.addWidget(QLabel("Расчет налогов по юрисдикциям"))
        tab.setLayout(layout)
        self._tabs["taxes"] = tab
        self.tab_widget.addTab(tab, "🏛️ Налоги")

    def _create_analytics_tab(self) -> None:
        """Создает вкладку 'Аналитика'."""
        tab = QGroupBox("Финансовая аналитика")
        layout = QVBoxLayout()
        layout.addWidget(QLabel("Графики доходов, расходов, ROI"))
        tab.setLayout(layout)
        self._tabs["analytics"] = tab
        self.tab_widget.addTab(tab, "📈 Аналитика")

    def apply_theme(self) -> None:
        """Применяет текущую тему оформления."""
        if not self.theme_manager:
            return
        try:
            palette = self.theme_manager.get_palette("finances")
            if palette:
                self.setPalette(palette)
            font = self.theme_manager.get_font("finances")
            if font:
                self.setFont(font)
            logger.debug("🎨 Theme applied to FinancesLayout")
        except Exception as e:
            logger.warning(f"⚠️ Failed to apply theme: {e}")

    def refresh_data(self) -> None:
        """Обновляет данные во всех вкладках (вызывается извне)."""
        logger.info("🔄 Refreshing finances data...")
        # Здесь будет интеграция с self.db_service или core.payment
        # Например: self._load_transactions(), self._update_overview() и т.д.
        pass

    def export_report(self, format: str = "pdf") -> bool:
        """Экспортирует финансовый отчет (stub для будущего расширения)."""
        logger.info(f"📤 Exporting finances report as {format}")
        return True