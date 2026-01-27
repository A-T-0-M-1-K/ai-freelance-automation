# AI_FREELANCE_AUTOMATION/ui/components/monitoring_widgets.py
"""
Мониторинговые виджеты для UI.
Отображают метрики, аномалии, предупреждения и статус системы.
Поддерживают темы, масштабирование и обновление в реальном времени.
"""

import logging
from typing import Dict, Any, Optional, List
from datetime import datetime

from core.monitoring.intelligent_monitoring_system import IntelligentMonitoringSystem
from core.config.unified_config_manager import UnifiedConfigManager
from ui.theme_manager import ThemeManager

# Логгер компонента
logger = logging.getLogger("UI.MonitoringWidgets")


class MonitoringWidgetBase:
    """Базовый класс для всех мониторинговых виджетов."""

    def __init__(self, config: UnifiedConfigManager, theme_manager: ThemeManager):
        self.config = config
        self.theme = theme_manager
        self._last_update: Optional[datetime] = None
        self._data_cache: Dict[str, Any] = {}
        logger.debug(f"Intialized {self.__class__.__name__}")

    def refresh(self) -> bool:
        """Обновить данные виджета. Возвращает True при успехе."""
        raise NotImplementedError("Subclasses must implement refresh()")

    def render(self) -> str:
        """Вернуть строковое представление виджета (для TUI) или подготовить данные (для GUI)."""
        raise NotImplementedError("Subclasses must implement render()")


class SystemMetricsWidget(MonitoringWidgetBase):
    """Виджет отображения системных метрик: CPU, RAM, диск, сеть."""

    def __init__(
            self,
            monitoring_system: IntelligentMonitoringSystem,
            config: UnifiedConfigManager,
            theme_manager: ThemeManager
    ):
        super().__init__(config, theme_manager)
        self.monitoring = monitoring_system
        self.metrics_keys = ["cpu_usage", "memory_usage", "disk_usage", "network_in", "network_out"]

    def refresh(self) -> bool:
        try:
            metrics = self.monitoring.get_current_metrics()
            self._data_cache = {k: metrics.get(k, "N/A") for k in self.metrics_keys}
            self._last_update = datetime.now()
            return True
        except Exception as e:
            logger.error(f"Failed to refresh system metrics: {e}")
            return False

    def render(self) -> Dict[str, Any]:
        """Возвращает структурированные данные для GUI-рендера."""
        return {
            "type": "system_metrics",
            "last_update": self._last_update.isoformat() if self._last_update else None,
            "metrics": self._data_cache,
            "theme": self.theme.get_current_theme_name(),
            "status": "healthy" if all(v != "N/A" and (isinstance(v, (int, float)) and v < 90) for v in
                                       self._data_cache.values()) else "warning"
        }


class AnomalyAlertWidget(MonitoringWidgetBase):
    """Виджет отображения последних аномалий и предупреждений."""

    def __init__(
            self,
            monitoring_system: IntelligentMonitoringSystem,
            config: UnifiedConfigManager,
            theme_manager: ThemeManager
    ):
        super().__init__(config, theme_manager)
        self.monitoring = monitoring_system
        self.max_alerts = self.config.get("ui.monitoring.max_alerts", default=10)

    def refresh(self) -> bool:
        try:
            anomalies = self.monitoring.get_recent_anomalies(limit=self.max_alerts)
            self._data_cache = {
                "alerts": [
                    {
                        "timestamp": a.get("timestamp"),
                        "level": a.get("severity", "info"),
                        "component": a.get("component", "unknown"),
                        "message": a.get("description", "No description"),
                        "resolved": a.get("resolved", False)
                    }
                    for a in anomalies
                ]
            }
            self._last_update = datetime.now()
            return True
        except Exception as e:
            logger.error(f"Failed to refresh anomaly alerts: {e}")
            return False

    def render(self) -> Dict[str, Any]:
        unresolved = [a for a in self._data_cache.get("alerts", []) if not a["resolved"]]
        status = "critical" if any(a["level"] == "critical" for a in unresolved) else \
            "warning" if unresolved else "healthy"

        return {
            "type": "anomaly_alerts",
            "last_update": self._last_update.isoformat() if self._last_update else None,
            "alerts": self._data_cache["alerts"],
            "unresolved_count": len(unresolved),
            "status": status,
            "theme": self.theme.get_current_theme_name()
        }


class PerformanceTrendWidget(MonitoringWidgetBase):
    """Виджет отображения трендов производительности (последние 24 часа)."""

    def __init__(
            self,
            monitoring_system: IntelligentMonitoringSystem,
            config: UnifiedConfigManager,
            theme_manager: ThemeManager
    ):
        super().__init__(config, theme_manager)
        self.monitoring = monitoring_system
        self.trend_metrics = ["job_success_rate", "avg_response_time", "revenue_24h"]

    def refresh(self) -> bool:
        try:
            trends = self.monitoring.get_performance_trends(hours=24)
            self._data_cache = {k: trends.get(k, []) for k in self.trend_metrics}
            self._last_update = datetime.now()
            return True
        except Exception as e:
            logger.error(f"Failed to refresh performance trends: {e}")
            return False

    def render(self) -> Dict[str, Any]:
        return {
            "type": "performance_trends",
            "last_update": self._last_update.isoformat() if self._last_update else None,
            "trends": self._data_cache,
            "theme": self.theme.get_current_theme_name()
        }


class MonitoringDashboard:
    """Агрегатор всех мониторинговых виджетов."""

    def __init__(
            self,
            monitoring_system: IntelligentMonitoringSystem,
            config: UnifiedConfigManager,
            theme_manager: ThemeManager
    ):
        self.widgets: List[MonitoringWidgetBase] = [
            SystemMetricsWidget(monitoring_system, config, theme_manager),
            AnomalyAlertWidget(monitoring_system, config, theme_manager),
            PerformanceTrendWidget(monitoring_system, config, theme_manager)
        ]
        logger.info("Monitoring dashboard initialized with %d widgets", len(self.widgets))

    def refresh_all(self) -> Dict[str, Any]:
        """Обновить все виджеты и вернуть их данные."""
        result = {}
        for widget in self.widgets:
            success = widget.refresh()
            data = widget.render()
            data["refresh_success"] = success
            result[widget.__class__.__name__] = data
        return result


# Пример использования (не вызывается напрямую в production)
if __name__ == "__main__":
    from core.config.unified_config_manager import UnifiedConfigManager
    from core.monitoring.intelligent_monitoring_system import IntelligentMonitoringSystem
    from ui.theme_manager import ThemeManager

    config = UnifiedConfigManager()
    theme = ThemeManager(config)
    monitor = IntelligentMonitoringSystem(config)

    dashboard = MonitoringDashboard(monitor, config, theme)
    data = dashboard.refresh_all()
    print(data)