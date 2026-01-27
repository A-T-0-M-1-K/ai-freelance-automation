# AI_FREELANCE_AUTOMATION/ui/layouts/jobs_layout.py
"""
Jobs Layout Module
==================

Provides the UI layout for managing freelance jobs:
- Active / completed / pending job lists
- Job detail view
- Status indicators
- Action buttons (accept, deliver, revise, etc.)
- Integration with core automation system

Follows:
- Clean separation of concerns (UI vs logic)
- Responsive design principles
- Theme-aware styling
- Full error resilience and logging
- Compatibility with Qt/PySide or Tkinter abstraction layer (via ui/components)

Author: AI Freelance Automation System
"""

import logging
from typing import Optional, Dict, Any, Callable
from pathlib import Path

# Local imports — using relative paths to respect project structure
from ..components.job_widgets import (
    JobCardWidget,
    JobDetailPanel,
    JobStatusIndicator,
    JobActionToolbar
)
from ..theme_manager import ThemeManager
from ...core.config.unified_config_manager import UnifiedConfigManager
from ...core.dependency.service_locator import ServiceLocator

# Setup module-specific logger
logger = logging.getLogger(__name__)


class JobsLayout:
    """
    Manages the complete UI layout for the Jobs section.
    Designed to be embedded into a main window or tab.

    Responsibilities:
    - Rendering job lists by status
    - Displaying detailed job views
    - Handling user-triggered actions (via callbacks)
    - Adapting to theme and localization
    - Remaining decoupled from business logic
    """

    def __init__(
            self,
            parent: Optional[Any] = None,
            config: Optional[UnifiedConfigManager] = None,
            theme_manager: Optional[ThemeManager] = None,
            on_action_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None
    ):
        """
        Initialize the Jobs Layout.

        Args:
            parent: Parent UI container (e.g., QMainWindow, QTabWidget)
            config: Unified configuration manager (injected via DI)
            theme_manager: Handles dynamic theming
            on_action_callback: Callback for propagating UI actions to core logic
        """
        self.parent = parent
        self.config = config or ServiceLocator.get("config")
        self.theme_manager = theme_manager or ServiceLocator.get("theme_manager")
        self.on_action_callback = on_action_callback or self._default_action_handler

        # UI components
        self.job_cards: Dict[str, JobCardWidget] = {}
        self.detail_panel: Optional[JobDetailPanel] = None
        self.action_toolbar: Optional[JobActionToolbar] = None
        self.status_filters = ["active", "pending", "completed", "archived"]

        # State
        self.current_job_id: Optional[str] = None
        self.visible_jobs: Dict[str, Dict[str, Any]] = {}

        logger.info("Intialized JobsLayout with config profile: %s", self.config.get("profile", "default"))

    def build_layout(self) -> Any:
        """
        Construct and return the full layout object.
        Abstracts underlying UI framework (Qt, Tkinter, etc.) via component wrappers.

        Returns:
            Framework-specific layout/container object ready for embedding.
        """
        try:
            logger.debug("Building Jobs layout...")

            # Create main container
            main_container = self._create_main_container()

            # Top: Filter bar
            filter_bar = self._create_filter_bar()
            main_container.add_widget(filter_bar, region="top")

            # Left: Job list panel
            job_list_panel = self._create_job_list_panel()
            main_container.add_widget(job_list_panel, region="left", stretch=1)

            # Right: Detail panel
            self.detail_panel = JobDetailPanel(theme_manager=self.theme_manager)
            main_container.add_widget(self.detail_panel, region="center", stretch=2)

            # Bottom: Action toolbar
            self.action_toolbar = JobActionToolbar(
                on_action=self._handle_action,
                theme_manager=self.theme_manager
            )
            main_container.add_widget(self.action_toolbar, region="bottom")

            logger.info("Jobs layout built successfully.")
            return main_container

        except Exception as e:
            logger.exception("Failed to build Jobs layout: %s", str(e))
            raise RuntimeError(f"UI layout construction failed: {e}") from e

    def update_jobs(self, jobs_data: Dict[str, Dict[str, Any]]) -> None:
        """
        Update the displayed jobs from external data source (e.g., core/job_service).

        Args:
            jobs_data: Dict {job_id: job_metadata}
        """
        try:
            self.visible_jobs = jobs_data
            self._refresh_job_list()
            if self.current_job_id and self.current_job_id in jobs_data:
                self._show_job_details(self.current_job_id)
            logger.debug("Updated %d jobs in UI.", len(jobs_data))
        except Exception as e:
            logger.error("Error updating jobs in UI: %s", e, exc_info=True)

    def select_job(self, job_id: str) -> None:
        """Programmatically select a job by ID."""
        if job_id not in self.visible_jobs:
            logger.warning("Attempted to select non-existent job: %s", job_id)
            return
        self.current_job_id = job_id
        self._show_job_details(job_id)
        self._highlight_selected_card(job_id)

    def _create_main_container(self) -> Any:
        """Create abstract main container. Framework-agnostic via component system."""
        from ..components import create_split_layout  # deferred import to avoid circular deps
        return create_split_layout(parent=self.parent, orientation="horizontal")

    def _create_filter_bar(self) -> Any:
        """Create status filter buttons."""
        from ..components import FilterBar
        return FilterBar(
            filters=self.status_filters,
            on_filter_change=self._on_filter_change,
            theme_manager=self.theme_manager
        )

    def _create_job_list_panel(self) -> Any:
        """Create scrollable job list."""
        from ..components import ScrollableList
        self.job_list_widget = ScrollableList(parent=self.parent)
        self._refresh_job_list()
        return self.job_list_widget

    def _refresh_job_list(self) -> None:
        """Rebuild job cards based on current visible jobs."""
        self.job_cards.clear()
        self.job_list_widget.clear()

        for job_id, job_data in self.visible_jobs.items():
            card = JobCardWidget(
                job_id=job_id,
                title=job_data.get("title", "Untitled"),
                client=job_data.get("client_name", "Anonymous"),
                status=job_data.get("status", "unknown"),
                deadline=job_data.get("deadline"),
                budget=job_data.get("budget"),
                on_click=lambda jid=job_id: self.select_job(jid),
                theme_manager=self.theme_manager
            )
            self.job_cards[job_id] = card
            self.job_list_widget.add_item(card)

    def _show_job_details(self, job_id: str) -> None:
        """Display detailed view for selected job."""
        if not self.detail_panel:
            return
        job_data = self.visible_jobs.get(job_id, {})
        self.detail_panel.update_content(job_data)

    def _highlight_selected_card(self, job_id: str) -> None:
        """Visually highlight the selected job card."""
        for jid, card in self.job_cards.items():
            card.set_selected(jid == job_id)

    def _on_filter_change(self, filter_name: str) -> None:
        """Handle filter selection (stub — delegate to controller)."""
        logger.debug("Filter changed to: %s", filter_name)
        # In full app, this would trigger a re-fetch from JobService with filter

    def _handle_action(self, action: str, **kwargs) -> None:
        """Forward UI actions to the core system."""
        payload = {"action": action, "job_id": self.current_job_id, **kwargs}
        self.on_action_callback(action, payload)

    def _default_action_handler(self, action: str, payload: Dict[str, Any]) -> None:
        """Fallback handler if no callback provided."""
        logger.warning("UI action '%s' triggered with no handler. Payload: %s", action, payload)

    def apply_theme(self) -> None:
        """Reapply current theme to all components."""
        if self.theme_manager:
            theme = self.theme_manager.get_current_theme()
            # Propagate to children
            for card in self.job_cards.values():
                card.apply_theme(theme)
            if self.detail_panel:
                self.detail_panel.apply_theme(theme)
            if self.action_toolbar:
                self.action_toolbar.apply_theme(theme)
            logger.debug("Applied theme '%s' to JobsLayout", theme.get("name", "unknown"))


# Optional: standalone test mode
if __name__ == "__main__":
    print("This module is part of a larger UI system and cannot run standalone.")
    print("Use `main.py` or `ui/main_window.py` to launch the application.")