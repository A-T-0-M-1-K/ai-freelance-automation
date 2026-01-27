# AI_FREELANCE_AUTOMATION/ui/components/job_widgets.py
"""
Job Widgets Component — Interactive, draggable, theme-aware UI widgets for freelance job display.
Supports compact, expanded, and expert views. Fully responsive and integrated with system theming.
"""

from __future__ import annotations
import logging
from typing import Dict, Any, Optional, Literal
from dataclasses import dataclass
from enum import Enum

# Local imports (following project structure)
from ui.theming.theme_manager import ThemeManager
from ui.layout.responsive_layout import ResponsiveLayoutEngine
from core.dependency.service_locator import ServiceLocator
from core.config.unified_config_manager import UnifiedConfigManager
from core.monitoring.intelligent_monitor import log_ui_event

logger = logging.getLogger("UI.JobWidgets")


class JobViewMode(Enum):
    COMPACT = "compact"
    EXPANDED = "expanded"
    EXPERT = "expert"


@dataclass
class JobData:
    """Immutable representation of a job for UI rendering."""
    job_id: str
    platform: str
    title: str
    description: str
    budget: float
    currency: str
    deadline: str  # ISO 8601
    skills: list[str]
    client_rating: Optional[float] = None
    risk_score: Optional[float] = None  # 0.0–1.0
    status: str = "pending"  # e.g., pending, active, completed


class JobWidget:
    """
    A single draggable, theme-aware job widget.
    Renders differently based on view mode and device type.
    """

    def __init__(
        self,
        job_data: JobData,
        view_mode: JobViewMode = JobViewMode.COMPACT,
        parent_container: Optional[str] = None
    ):
        self.job_data = job_data
        self.view_mode = view_mode
        self.parent_container = parent_container
        self.is_dragging = False
        self._theme_manager = ServiceLocator.get_service("ThemeManager") or ThemeManager()
        self._layout_engine = ResponsiveLayoutEngine()
        self._config = ServiceLocator.get_service("ConfigManager") or UnifiedConfigManager()

        # Validate early
        if not isinstance(job_data, JobData):
            raise TypeError("job_data must be an instance of JobData")

        logger.debug(f"Intialized JobWidget for job {job_data.job_id} in {view_mode.value} mode")

    def render(self) -> Dict[str, Any]:
        """
        Render the widget as structured UI data (e.g., for frontend or TUI).
        Returns a JSON-serializable dict representing the widget state.
        """
        try:
            current_theme = self._theme_manager.get_current_theme()
            is_mobile = self._layout_engine.is_mobile()

            base_style = self._get_base_style(current_theme, is_mobile)
            content = self._build_content(is_mobile)

            widget = {
                "type": "job_widget",
                "id": self.job_data.job_id,
                "draggable": True,
                "container": self.parent_container,
                "view_mode": self.view_mode.value,
                "style": base_style,
                "content": content,
                "metadata": {
                    "platform": self.job_data.platform,
                    "risk_score": self.job_data.risk_score,
                    "status": self.job_data.status
                }
            }

            log_ui_event("job_widget_rendered", {"job_id": self.job_data.job_id, "mode": self.view_mode.value})
            return widget

        except Exception as e:
            logger.error(f"Failed to render job widget {self.job_data.job_id}: {e}", exc_info=True)
            raise RuntimeError(f"UI rendering failed for job {self.job_data.job_id}") from e

    def _get_base_style(self, theme: Dict[str, Any], is_mobile: bool) -> Dict[str, Any]:
        """Generate style dictionary based on theme and device."""
        padding = "8px" if is_mobile else "12px"
        font_size = "14px" if is_mobile else "16px"

        mode_styles = {
            JobViewMode.COMPACT: {"height": "80px", "border_radius": "8px"},
            JobViewMode.EXPANDED: {"height": "160px", "border_radius": "12px"},
            JobViewMode.EXPERT: {"height": "240px", "border_radius": "16px"},
        }

        base = {
            "background": theme.get("card_background", "#ffffff"),
            "color": theme.get("text_primary", "#000000"),
            "border": f"1px solid {theme.get('border_color', '#e0e0e0')}",
            "padding": padding,
            "font_size": font_size,
            "box_shadow": theme.get("card_shadow", "0 2px 8px rgba(0,0,0,0.1)"),
            **mode_styles[self.view_mode]
        }

        # Highlight high-risk jobs
        if self.job_data.risk_score and self.job_data.risk_score > 0.7:
            base["border_left"] = "4px solid #ff6b6b"

        return base

    def _build_content(self, is_mobile: bool) -> Dict[str, Any]:
        """Build content structure based on view mode."""
        content = {
            "title": self.job_data.title[:60] + "..." if len(self.job_data.title) > 60 and is_mobile else self.job_data.title,
            "platform": self.job_data.platform,
            "budget": f"{self.job_data.budget:.2f} {self.job_data.currency}",
            "deadline": self.job_data.deadline
        }

        if self.view_mode in (JobViewMode.EXPANDED, JobViewMode.EXPERT):
            content.update({
                "description": self.job_data.description[:200] + "..." if len(self.job_data.description) > 200 else self.job_data.description,
                "skills": self.job_data.skills[:5] if is_mobile else self.job_data.skills
            })

        if self.view_mode == JobViewMode.EXPERT:
            content.update({
                "client_rating": self.job_data.client_rating,
                "risk_score": self.job_data.risk_score,
                "job_id": self.job_data.job_id,
                "status": self.job_data.status
            })

        return content

    def update_view_mode(self, new_mode: JobViewMode) -> None:
        """Dynamically switch view mode."""
        if self.view_mode != new_mode:
            self.view_mode = new_mode
            logger.debug(f"JobWidget {self.job_data.job_id} switched to {new_mode.value} mode")

    def start_drag(self) -> None:
        """Initiate drag operation."""
        self.is_dragging = True
        log_ui_event("job_widget_drag_start", {"job_id": self.job_data.job_id})

    def end_drag(self) -> None:
        """End drag operation."""
        self.is_dragging = False
        log_ui_event("job_widget_drag_end", {"job_id": self.job_data.job_id})


class JobWidgetFactory:
    """
    Factory for creating consistent JobWidgets with system-wide settings.
    Ensures compatibility with dependency injection and config changes.
    """

    @staticmethod
    def create_from_raw_data(
        raw_job: Dict[str, Any],
        view_mode: Literal["compact", "expanded", "expert"] = "compact",
        container: Optional[str] = None
    ) -> JobWidget:
        """
        Create a JobWidget from raw job data (e.g., from platform API).
        Performs validation and normalization.
        """
        try:
            # Normalize view mode
            mode_enum = JobViewMode(view_mode)

            # Validate required fields
            required = ["job_id", "title", "budget", "currency", "platform"]
            for field in required:
                if field not in raw_job:
                    raise ValueError(f"Missing required field: {field}")

            job_data = JobData(
                job_id=str(raw_job["job_id"]),
                platform=str(raw_job["platform"]),
                title=str(raw_job["title"]),
                description=str(raw_job.get("description", "")),
                budget=float(raw_job["budget"]),
                currency=str(raw_job["currency"]),
                deadline=str(raw_job.get("deadline", "N/A")),
                skills=list(raw_job.get("skills", [])),
                client_rating=float(raw_job["client_rating"]) if raw_job.get("client_rating") is not None else None,
                risk_score=float(raw_job["risk_score"]) if raw_job.get("risk_score") is not None else None,
                status=str(raw_job.get("status", "pending"))
            )

            return JobWidget(job_data=job_data, view_mode=mode_enum, parent_container=container)

        except (ValueError, TypeError, KeyError) as e:
            logger.error(f"Invalid job data for widget creation: {e}")
            raise ValueError(f"Cannot create JobWidget from invalid data: {e}") from e


# Example usage (not executed in production)
if __name__ == "__main__":
    sample_job = {
        "job_id": "upw_12345",
        "platform": "Upwork",
        "title": "Transcribe 1-hour interview",
        "description": "Need accurate transcription of a business interview in English.",
        "budget": 85.0,
        "currency": "USD",
        "deadline": "2026-02-01T23:59:59Z",
        "skills": ["transcription", "english", "accuracy"],
        "client_rating": 4.8,
        "risk_score": 0.15,
        "status": "pending"
    }

    widget = JobWidgetFactory.create_from_raw_data(sample_job, "expanded")
    print(widget.render())