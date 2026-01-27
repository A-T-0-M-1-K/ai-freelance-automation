# AI_FREELANCE_AUTOMATION/ui/components/finance_widgets.py
"""
Finance Widgets for the UI Layer

Provides reusable, composable widgets for displaying financial data:
- Income/expense charts
- Transaction lists
- Invoice status panels
- Tax summaries
- Payment method indicators

All widgets are designed to be:
- Theme-aware (respect current UI theme)
- Responsive (adapt to window size)
- Data-driven (accept structured finance data from core/services)
- Observable (emit events for user interactions)
- Testable (no side effects in __init__)

Integrates with:
- core/monitoring/
- services/storage/database_service.py
- data/finances/
"""

import logging
from typing import Any, Dict, List, Optional, Callable
from datetime import datetime, timedelta

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QLabel, QFrame, QHeaderView, QPushButton, QProgressBar
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont

# Local imports (relative to avoid circular dependencies)
from ..theme_manager import ThemeManager
from ...core.config.unified_config_manager import UnifiedConfigManager

# Logger
logger = logging.getLogger("UI.FinanceWidgets")


class FinanceWidgetBase(QWidget):
    """Base class for all finance-related UI widgets."""
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.theme = ThemeManager.get_instance()
        self.config = UnifiedConfigManager.get_instance()
        self._setup_ui()

    def _setup_ui(self):
        """Override in subclasses to define widget layout."""
        raise NotImplementedError


class IncomeExpenseChartWidget(FinanceWidgetBase):
    """Visualizes income vs expenses over time using a bar-style progress indicator."""
    def _setup_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(10, 10, 10, 10)

        title = QLabel("📊 Income vs Expenses (Last 30 Days)")
        title.setFont(QFont("Segoe UI", 12, QFont.Bold))
        title.setStyleSheet(f"color: {self.theme.get_color('text_primary')};")
        layout.addWidget(title)

        # Placeholder for actual chart (in real app, use matplotlib or QtCharts)
        self.income_bar = QProgressBar()
        self.expense_bar = QProgressBar()
        self.income_bar.setFormat("Income: %v")
        self.expense_bar.setFormat("Expenses: %v")
        self.income_bar.setStyleSheet(self._get_bar_style("#4CAF50"))  # green
        self.expense_bar.setStyleSheet(self._get_bar_style("#F44336"))  # red

        layout.addWidget(self.income_bar)
        layout.addWidget(self.expense_bar)
        self.setLayout(layout)

    def _get_bar_style(self, color: str) -> str:
        return f"""
            QProgressBar {{
                border: 1px solid {self.theme.get_color('border')};
                border-radius: 4px;
                text-align: center;
                color: {self.theme.get_color('text_primary')};
            }}
            QProgressBar::chunk {{
                background-color: {color};
                width: 20px;
            }}
        """

    def update_data(self, income: float, expenses: float, max_value: float = 1000.0):
        """Update chart with new financial data."""
        self.income_bar.setMaximum(int(max_value))
        self.expense_bar.setMaximum(int(max_value))
        self.income_bar.setValue(int(income))
        self.expense_bar.setValue(int(expenses))
        logger.debug(f"Updated finance chart: income={income}, expenses={expenses}")


class TransactionListWidget(FinanceWidgetBase):
    """Displays a scrollable list of recent transactions."""
    transaction_selected = pyqtSignal(str)  # Emits transaction_id

    def _setup_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        title = QLabel("💳 Recent Transactions")
        title.setFont(QFont("Segoe UI", 11, QFont.Bold))
        title.setStyleSheet(f"color: {self.theme.get_color('text_primary')}; margin-bottom: 8px;")
        layout.addWidget(title)

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Date", "Description", "Amount", "Status"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.cellClicked.connect(self._on_row_clicked)

        layout.addWidget(self.table)
        self.setLayout(layout)

    def _on_row_clicked(self, row: int, column: int):
        item = self.table.item(row, 0)
        if item and hasattr(item, 'transaction_id'):
            self.transaction_selected.emit(item.transaction_id)

    def update_transactions(self, transactions: List[Dict[str, Any]]):
        """Replace table contents with new transaction data."""
        self.table.setRowCount(len(transactions))
        for i, tx in enumerate(transactions):
            date_str = datetime.fromisoformat(tx['timestamp']).strftime("%Y-%m-%d %H:%M")
            desc = tx.get('description', '—')
            amount = f"{tx['amount']:.2f} {tx.get('currency', 'USD')}"
            status = tx.get('status', 'pending').capitalize()

            date_item = QTableWidgetItem(date_str)
            desc_item = QTableWidgetItem(desc)
            amount_item = QTableWidgetItem(amount)
            status_item = QTableWidgetItem(status)

            # Store transaction ID for event emission
            date_item.transaction_id = tx['id']

            # Color coding
            if tx.get('type') == 'income':
                amount_item.setForeground(QColor("#4CAF50"))
            else:
                amount_item.setForeground(QColor("#F44336"))

            self.table.setItem(i, 0, date_item)
            self.table.setItem(i, 1, desc_item)
            self.table.setItem(i, 2, amount_item)
            self.table.setItem(i, 3, status_item)

        logger.debug(f"Updated transaction list with {len(transactions)} items.")


class InvoiceStatusPanel(FinanceWidgetBase):
    """Shows summary of unpaid/paid invoices and quick actions."""
    pay_invoice_requested = pyqtSignal(str)  # invoice_id

    def _setup_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(12)

        title = QLabel("🧾 Invoices Overview")
        title.setFont(QFont("Segoe UI", 11, QFont.Bold))
        title.setStyleSheet(f"color: {self.theme.get_color('text_primary')};")
        layout.addWidget(title)

        self.summary_label = QLabel()
        self.summary_label.setStyleSheet(f"color: {self.theme.get_color('text_secondary')};")
        layout.addWidget(self.summary_label)

        self.pay_button = QPushButton("Pay Outstanding")
        self.pay_button.clicked.connect(self._on_pay_clicked)
        self.pay_button.setEnabled(False)
        layout.addWidget(self.pay_button)

        self.setLayout(layout)

    def _on_pay_clicked(self):
        # In real app: open payment modal or redirect
        logger.info("User requested to pay outstanding invoices.")
        # Emit signal if we had a specific invoice context
        # For now, just log

    def update_invoices(self, stats: Dict[str, int], total_unpaid: float):
        """Update panel with invoice statistics."""
        paid = stats.get('paid', 0)
        unpaid = stats.get('unpaid', 0)
        total = paid + unpaid

        self.summary_label.setText(
            f"Total: {total} | Paid: {paid} | Unpaid: {unpaid} "
            f"({total_unpaid:.2f} USD pending)"
        )

        self.pay_button.setEnabled(unpaid > 0)
        if unpaid > 0:
            self.pay_button.setStyleSheet(f"background-color: {self.theme.get_color('accent')}; color: white;")
        else:
            self.pay_button.setStyleSheet("")

        logger.debug(f"Updated invoice panel: {stats}")


class TaxSummaryWidget(FinanceWidgetBase):
    """Displays estimated tax liability and filing status."""
    def _setup_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(10, 10, 10, 10)

        title = QLabel("⚖️ Tax Summary")
        title.setFont(QFont("Segoe UI", 11, QFont.Bold))
        title.setStyleSheet(f"color: {self.theme.get_color('text_primary')};")
        layout.addWidget(title)

        self.tax_label = QLabel("Loading...")
        self.tax_label.setStyleSheet(f"color: {self.theme.get_color('text_secondary')};")
        layout.addWidget(self.tax_label)

        self.setLayout(layout)

    def update_tax_info(self, estimated_tax: float, currency: str = "USD", next_deadline: Optional[str] = None):
        """Update tax information."""
        text = f"Estimated Tax: {estimated_tax:.2f} {currency}"
        if next_deadline:
            text += f"\nNext Filing: {next_deadline}"
        self.tax_label.setText(text)
        logger.debug(f"Updated tax info: {estimated_tax} {currency}")


# Optional: Composite widget that combines all finance views
class FinanceDashboardWidget(QWidget):
    """Main finance dashboard combining all sub-widgets."""
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(16)

        layout.addWidget(IncomeExpenseChartWidget())
        layout.addWidget(TransactionListWidget())
        layout.addWidget(InvoiceStatusPanel())
        layout.addWidget(TaxSummaryWidget())

        self.setLayout(layout)