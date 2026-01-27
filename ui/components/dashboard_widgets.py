# AI_FREELANCE_AUTOMATION/ui/components/dashboard_widgets.py
"""
Dashboard widgets for the AI Freelance Automation UI.
Provides real-time, interactive components for monitoring system status,
active jobs, finances, performance metrics, and AI activity.

Designed to be framework-agnostic (supports Qt, web, CLI via adapters).
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Union
from datetime import datetime, timedelta

# Local imports (relative to project root)
from ui.theme_manager import ThemeManager
from core.dependency.service_locator import ServiceLocator
from core.config.unified_config_manager import UnifiedConfigManager

# Configure logger
logger = logging.getLogger(__name__)


class BaseDashboardWidget(ABC):
    """
    Abstract base class for all dashboard widgets.
    Enforces consistent interface and lifecycle management.
    """

    def __init__(self, name: str, config: Optional[Dict[str, Any]] = None):
        self.name = name
        self.config = config or {}
        self._initialized = False
        self._data: Dict[str, Any] = {}
        self.logger = logging.getLogger(f"Widget.{name}")

    @abstractmethod
    async def fetch_data(self) -> Dict[str, Any]:
        """Fetch fresh data from relevant services."""
        pass

    @abstractmethod
    def render(self) -> str:
        """
        Return a string representation of the widget (for CLI/web) or trigger UI update.
        In GUI frameworks, this would emit signals or update internal state.
        """
        pass

    async def refresh(self) -> bool:
        """Refresh widget data and trigger re-render."""
        try:
            self._data = await self.fetch_data()
            self._initialized = True
            self.logger.debug(f"Widget '{self.name}' refreshed successfully.")
            return True
        except Exception as e:
            self.logger.error(f"Failed to refresh widget '{self.name}': {e}", exc_info=True)
            return False

    def get_data(self) -> Dict[str, Any]:
        """Return current data (safe after refresh)."""
        return self._data.copy()

    @property
    def is_ready(self) -> bool:
        return self._initialized


class ActiveJobsWidget(BaseDashboardWidget):
    """Displays count and status of active freelance jobs."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__("ActiveJobs", config)

    async def fetch_data(self) -> Dict[str, Any]:
        job_service = ServiceLocator.get("job_service")  # assumed registered
        active_jobs = await job_service.get_active_jobs()
        overdue = [j for j in active_jobs if j.get("deadline") and datetime.fromisoformat(j["deadline"]) < datetime.utcnow()]
        return {
            "total": len(active_jobs),
            "overdue": len(overdue),
            "by_platform": self._group_by_platform(active_jobs),
            "recent": active_jobs[:5]  # last 5
        }

    def _group_by_platform(self, jobs: List[Dict]) -> Dict[str, int]:
        counts = {}
        for job in jobs:
            platform = job.get("platform", "unknown")
            counts[platform] = counts.get(platform, 0) + 1
        return counts

    def render(self) -> str:
        if not self.is_ready:
            return "[ActiveJobs] Loading..."
        data = self._data
        lines = [
            f"💼 Active Jobs: {data['total']}",
            f"⚠️ Overdue: {data['overdue']}",
            "By Platform:",
        ]
        for plat, count in data["by_platform"].items():
            lines.append(f"  • {plat.capitalize()}: {count}")
        return "\n".join(lines)


class FinancialSummaryWidget(BaseDashboardWidget):
    """Shows revenue, pending payments, and weekly trend."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__("FinancialSummary", config)

    async def fetch_data(self) -> Dict[str, Any]:
        finance_service = ServiceLocator.get("finance_service")
        now = datetime.utcnow()
        week_ago = now - timedelta(days=7)

        revenue_week = await finance_service.get_revenue(start_date=week_ago, end_date=now)
        pending = await finance_service.get_pending_payments()
        total_balance = await finance_service.get_total_balance()

        return {
            "weekly_revenue": round(revenue_week, 2),
            "pending_payments": round(pending, 2),
            "total_balance": round(total_balance, 2),
            "currency": "USD"
        }

    def render(self) -> str:
        if not self.is_ready:
            return "[Finance] Loading..."
        d = self._data
        return (
            f"💰 Weekly Revenue: {d['weekly_revenue']} {d['currency']}\n"
            f"⏳ Pending: {d['pending_payments']} {d['currency']}\n"
            f"🏦 Balance: {d['total_balance']} {d['currency']}"
        )


class SystemHealthWidget(BaseDashboardWidget):
    """Displays CPU, memory, uptime, and anomaly alerts."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__("SystemHealth", config)

    async def fetch_data(self) -> Dict[str, Any]:
        monitor = ServiceLocator.get("intelligent_monitoring_system")
        metrics = await monitor.get_current_metrics()
        anomalies = await monitor.get_recent_anomalies(limit=3)

        return {
            "cpu_percent": round(metrics.get("cpu_usage", 0), 1),
            "memory_percent": round(metrics.get("memory_usage", 0), 1),
            "uptime_hours": round(metrics.get("uptime_seconds", 0) / 3600, 1),
            "anomalies": anomalies,
            "status": "✅ Healthy" if not anomalies else "⚠️ Issues Detected"
        }

    def render(self) -> str:
        if not self.is_ready:
            return "[System] Loading..."
        d = self._data
        lines = [
            f"{d['status']}",
            f"⏱️ Uptime: {d['uptime_hours']}h",
            f"💻 CPU: {d['cpu_percent']}% | RAM: {d['memory_percent']}%"
        ]
        if d["anomalies"]:
            lines.append("Recent Anomalies:")
            for a in d["anomalies"]:
                lines.append(f"  • {a.get('description', 'Unknown')}")
        return "\n".join(lines)


class AIPerformanceWidget(BaseDashboardWidget):
    """Shows AI model usage, accuracy, and latency stats."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__("AIPerformance", config)

    async def fetch_data(self) -> Dict[str, Any]:
        ai_mgr = ServiceLocator.get("intelligent_model_manager")
        perf = await ai_mgr.get_aggregated_performance()

        return {
            "models_in_use": perf.get("active_models", 0),
            "avg_accuracy": round(perf.get("avg_accuracy", 0.0), 2),
            "avg_latency_ms": round(perf.get("avg_latency_ms", 0), 1),
            "tasks_completed_24h": perf.get("tasks_24h", 0)
        }

    def render(self) -> str:
        if not self.is_ready:
            return "[AI] Loading..."
        d = self._data
        return (
            f"🧠 AI Models Active: {d['models_in_use']}\n"
            f"🎯 Avg Accuracy: {d['avg_accuracy'] * 100:.1f}%\n"
            f"⚡ Latency: {d['avg_latency_ms']}ms\n"
            f"✅ Tasks (24h): {d['tasks_completed_24h']}"
        )


class DashboardWidgetFactory:
    """Factory to instantiate and manage dashboard widgets."""

    _widget_classes = {
        "active_jobs": ActiveJobsWidget,
        "finance": FinancialSummaryWidget,
        "system_health": SystemHealthWidget,
        "ai_performance": AIPerformanceWidget,
    }

    @classmethod
    def create_widget(cls, widget_type: str, config: Optional[Dict[str, Any]] = None) -> BaseDashboardWidget:
        if widget_type not in cls._widget_classes:
            raise ValueError(f"Unknown widget type: {widget_type}")
        return cls._widget_classes[widget_type](config)

    @classmethod
    def get_available_widgets(cls) -> List[str]:
        return list(cls._widget_classes.keys())


# Optional: Pre-configured dashboard layout
DEFAULT_DASHBOARD_LAYOUT = [
    "system_health",
    "active_jobs",
    "finance",
    "ai_performance"
]