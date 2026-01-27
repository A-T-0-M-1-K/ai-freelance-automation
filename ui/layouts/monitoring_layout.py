# AI_FREELANCE_AUTOMATION/ui/layouts/monitoring_layout.py
"""
Monitoring Layout — UI layout for real-time system health, performance, and AI analytics.
Integrates with core/monitoring/ and supports dark/light themes, responsive design,
and live metric updates via event-driven architecture.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel,
    QProgressBar, QScrollArea, QFrame
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont

if TYPE_CHECKING:
    from core.monitoring.intelligent_monitoring_system import IntelligentMonitoringSystem

logger = logging.getLogger("UILayout.Monitoring")


class MonitoringLayout(QWidget):
    """
    Centralized monitoring dashboard layout.
    Displays real-time metrics: system health, AI performance, job status, anomalies, and alerts.
    Designed for extensibility and seamless integration with the monitoring subsystem.
    """

    def __init__(
        self,
        monitoring_system: Optional[IntelligentMonitoringSystem] = None,
        parent: Optional[QWidget] = None
    ) -> None:
        super().__init__(parent)
        self.monitoring_system = monitoring_system
        self._init_ui()
        self._setup_update_timer()

    def _init_ui(self) -> None:
        """Initialize the UI components."""
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(15)

        # Title
        title_label = QLabel("📊 System Monitoring Dashboard")
        title_label.setFont(QFont("Segoe UI", 14, QFont.Bold))
        title_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title_label)

        # Scrollable area for all widgets
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setSpacing(20)

        # Add metric panels
        scroll_layout.addWidget(self._create_system_health_panel())
        scroll_layout.addWidget(self._create_ai_performance_panel())
        scroll_layout.addWidget(self._create_job_status_panel())
        scroll_layout.addWidget(self._create_anomaly_alerts_panel())

        scroll_area.setWidget(scroll_content)
        main_layout.addWidget(scroll_area)

        self.setLayout(main_layout)
        logger.info("Monitoring layout initialized.")

    def _create_system_health_panel(self) -> QGroupBox:
        """Create panel for CPU, memory, disk, network."""
        group = QGroupBox("🖥️ System Health")
        layout = QVBoxLayout()

        self.cpu_bar = QProgressBar()
        self.memory_bar = QProgressBar()
        self.disk_bar = QProgressBar()
        self.network_label = QLabel("Network: —")

        for label, bar in [("CPU Usage", self.cpu_bar), ("Memory Usage", self.memory_bar), ("Disk Usage", self.disk_bar)]:
            bar_label = QLabel(label)
            bar.setRange(0, 100)
            bar.setTextVisible(True)
            layout.addWidget(bar_label)
            layout.addWidget(bar)

        layout.addWidget(self.network_label)
        group.setLayout(layout)
        return group

    def _create_ai_performance_panel(self) -> QGroupBox:
        """Create panel for AI model latency, accuracy, throughput."""
        group = QGroupBox("🧠 AI Performance")
        layout = QVBoxLayout()

        self.model_latency_label = QLabel("Avg. Inference Latency: — ms")
        self.model_accuracy_label = QLabel("Model Accuracy: — %")
        self.throughput_label = QLabel("Throughput: — req/sec")

        for lbl in [self.model_latency_label, self.model_accuracy_label, self.throughput_label]:
            layout.addWidget(lbl)

        group.setLayout(layout)
        return group

    def _create_job_status_panel(self) -> QGroupBox:
        """Create panel for active jobs, completion rate, deadlines."""
        group = QGroupBox("💼 Job Status")
        layout = QVBoxLayout()

        self.active_jobs_label = QLabel("Active Jobs: —")
        self.completed_today_label = QLabel("Completed Today: —")
        self.deadline_risk_label = QLabel("Jobs at Risk: —")

        for lbl in [self.active_jobs_label, self.completed_today_label, self.deadline_risk_label]:
            layout.addWidget(lbl)

        group.setLayout(layout)
        return group

    def _create_anomaly_alerts_panel(self) -> QGroupBox:
        """Create panel for detected anomalies and recent alerts."""
        group = QGroupBox("⚠️ Anomalies & Alerts")
        layout = QVBoxLayout()

        self.anomaly_count_label = QLabel("Active Anomalies: —")
        self.last_alert_label = QLabel("Last Alert: —")
        self.recovery_status_label = QLabel("Auto-Recovery: —")

        for lbl in [self.anomaly_count_label, self.last_alert_label, self.recovery_status_label]:
            layout.addWidget(lbl)

        group.setLayout(layout)
        return group

    def _setup_update_timer(self) -> None:
        """Set up a timer to refresh metrics every 5 seconds."""
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self._refresh_metrics)
        self.update_timer.start(5000)  # 5 seconds
        logger.debug("Monitoring update timer started (5s interval).")

    def _refresh_metrics(self) -> None:
        """Fetch latest metrics from monitoring system and update UI."""
        if not self.monitoring_system:
            logger.warning("Monitoring system not connected. Skipping metric refresh.")
            return

        try:
            metrics = self.monitoring_system.get_current_metrics()

            # System Health
            self.cpu_bar.setValue(int(metrics.get("cpu_usage", 0)))
            self.memory_bar.setValue(int(metrics.get("memory_usage_percent", 0)))
            self.disk_bar.setValue(int(metrics.get("disk_usage_percent", 0)))
            net_in = metrics.get("network_in_kbps", 0)
            net_out = metrics.get("network_out_kbps", 0)
            self.network_label.setText(f"Network: ↓{net_in:.1f} ↑{net_out:.1f} kbps")

            # AI Performance
            self.model_latency_label.setText(f"Avg. Inference Latency: {metrics.get('ai_avg_latency_ms', '—')} ms")
            self.model_accuracy_label.setText(f"Model Accuracy: {metrics.get('ai_accuracy_percent', '—')}%")
            self.throughput_label.setText(f"Throughput: {metrics.get('ai_throughput_req_sec', '—')} req/sec")

            # Job Status
            self.active_jobs_label.setText(f"Active Jobs: {metrics.get('active_jobs', '—')}")
            self.completed_today_label.setText(f"Completed Today: {metrics.get('jobs_completed_today', '—')}")
            self.deadline_risk_label.setText(f"Jobs at Risk: {metrics.get('jobs_at_deadline_risk', '—')}")

            # Anomalies
            self.anomaly_count_label.setText(f"Active Anomalies: {metrics.get('active_anomalies', '—')}")
            last_alert = metrics.get("last_alert_message", "None")
            self.last_alert_label.setText(f"Last Alert: {last_alert}")
            recovery = "✅ Active" if metrics.get("auto_recovery_active", False) else "❌ Inactive"
            self.recovery_status_label.setText(f"Auto-Recovery: {recovery}")

        except Exception as e:
            logger.error(f"Failed to refresh monitoring metrics: {e}", exc_info=True)

    def shutdown(self) -> None:
        """Gracefully stop the update timer."""
        if hasattr(self, 'update_timer') and self.update_timer.isActive():
            self.update_timer.stop()
        logger.info("Monitoring layout shutdown complete.")
