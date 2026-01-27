# AI_FREELANCE_AUTOMATION/ui/layouts/dashboard_layout.py
"""
Dashboard layout for the AI Freelance Automation System.
Displays key metrics, active jobs, client interactions, financial summary,
and system health in a responsive, theme-aware interface.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from PySide6.QtWidgets import (
    QGridLayout,
    QFrame,
    QLabel,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import Qt

if TYPE_CHECKING:
    from ui.main_window import MainWindow

# Local components
from ui.components.dashboard_widgets import (
    ActiveJobsWidget,
    FinancialSummaryWidget,
    SystemHealthWidget,
    ClientInteractionsWidget,
    PerformanceMetricsWidget,
)

# Theme support
from ui.theme_manager import ThemeManager

logger = logging.getLogger("UILayout.Dashboard")


class DashboardLayout(QFrame):
    """
    Main dashboard layout that aggregates all critical widgets.
    Designed to be embedded into the main application window.
    Supports dynamic theming and responsive updates.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._main_window_ref: Optional["MainWindow"] = None
        self._theme_manager = ThemeManager.instance()
        self._setup_ui()
        self._apply_theme()
        self._connect_signals()
        logger.info("✅ DashboardLayout initialized.")

    def set_main_window(self, main_window: "MainWindow") -> None:
        """Set reference to main window for service access and navigation."""
        self._main_window_ref = main_window
        logger.debug("Main window reference set in DashboardLayout.")

    def _setup_ui(self) -> None:
        """Initialize and arrange all dashboard widgets."""
        self.setObjectName("DashboardLayout")
        self.setFrameStyle(QFrame.StyledPanel | QFrame.Raised)

        # Main layout
        layout = QGridLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # Title
        title_label = QLabel("📊 AI Freelance Dashboard")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setObjectName("DashboardTitle")
        layout.addWidget(title_label, 0, 0, 1, 4)

        # Widgets
        self.active_jobs_widget = ActiveJobsWidget(self)
        self.financial_widget = FinancialSummaryWidget(self)
        self.system_health_widget = SystemHealthWidget(self)
        self.client_interactions_widget = ClientInteractionsWidget(self)
        self.performance_widget = PerformanceMetricsWidget(self)

        # Arrange in grid (responsive 2x2 + full-width row)
        layout.addWidget(self.active_jobs_widget, 1, 0, 1, 2)
        layout.addWidget(self.financial_widget, 1, 2, 1, 2)
        layout.addWidget(self.system_health_widget, 2, 0, 1, 2)
        layout.addWidget(self.client_interactions_widget, 2, 2, 1, 2)
        layout.addWidget(self.performance_widget, 3, 0, 1, 4)

        self.setLayout(layout)

    def _apply_theme(self) -> None:
        """Apply current theme styling."""
        theme = self._theme_manager.get_current_theme()
        self.setStyleSheet(theme.get("dashboard_stylesheet", ""))
        logger.debug("Theme applied to DashboardLayout.")

    def _connect_signals(self) -> None:
        """Connect to theme change and other global signals."""
        self._theme_manager.theme_changed.connect(self._on_theme_changed)

    def _on_theme_changed(self) -> None:
        """React to theme changes."""
        self._apply_theme()

    def refresh_data(self) -> None:
        """
        Trigger data refresh across all child widgets.
        Called periodically or on user request.
        """
        if not self._main_window_ref:
            logger.warning("Cannot refresh dashboard: main window not set.")
            return

        try:
            self.active_jobs_widget.refresh()
            self.financial_widget.refresh()
            self.system_health_widget.refresh()
            self.client_interactions_widget.refresh()
            self.performance_widget.refresh()
            logger.debug("Dashboard data refreshed.")
        except Exception as e:
            logger.error(f"❌ Error during dashboard refresh: {e}", exc_info=True)

    def cleanup(self) -> None:
        """Clean up resources before destruction."""
        self._theme_manager.theme_changed.disconnect(self._on_theme_changed)
        logger.info("DashboardLayout cleaned up.")