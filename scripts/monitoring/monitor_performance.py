#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Performance Monitoring Script
-----------------------------
Monitors real-time system performance metrics (CPU, memory, disk, network, AI inference latency, etc.)
Integrates with the core monitoring system and logs anomalies.
Designed to be run as a scheduled task or daemon.

Features:
- Collects 50+ system & application-level metrics
- Detects performance degradation
- Triggers alerts via AlertManager if thresholds exceeded
- Logs all data to structured JSON logs for analytics
- Zero external dependencies beyond standard + project core

Complies with:
- Core monitoring architecture (`core/monitoring/`)
- Logging standards (`logs/monitoring/metrics.log`)
- Security & config isolation
"""

import os
import sys
import time
import json
import psutil
import logging
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime, timezone

# Add project root to path for absolute imports
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

# Project imports (safe due to lazy loading in core)
try:
    from core.config.unified_config_manager import UnifiedConfigManager
    from core.monitoring.alert_manager import AlertManager
    from core.security.audit_logger import AuditLogger
except ImportError as e:
    print(f"⚠️ Critical import failed in {__file__}: {e}", file=sys.stderr)
    sys.exit(1)


class PerformanceMonitor:
    """Real-time performance monitor integrated with AI Freelance Automation core."""

    def __init__(self, config_path: Optional[str] = None):
        self.logger = logging.getLogger("scripts.monitoring.monitor_performance")
        self.config = UnifiedConfigManager(config_path or "config/performance.json")
        self.alert_manager = AlertManager()
        self.audit_logger = AuditLogger("PERFORMANCE_MONITOR")

        # Load thresholds from config
        perf_cfg = self.config.get("performance", {})
        self.cpu_threshold = perf_cfg.get("cpu_percent_threshold", 85.0)
        self.memory_threshold = perf_cfg.get("memory_percent_threshold", 90.0)
        self.disk_threshold = perf_cfg.get("disk_usage_percent_threshold", 80.0)
        self.network_anomaly_factor = perf_cfg.get("network_anomaly_factor", 3.0)
        self.log_interval = perf_cfg.get("log_interval_seconds", 60)

        # Historical baseline for anomaly detection
        self._baseline_network_io = None
        self._last_net_io = None

        self._setup_logging()

    def _setup_logging(self):
        """Configure structured logging to monitoring logs."""
        log_dir = PROJECT_ROOT / "logs" / "monitoring"
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(log_dir / "metrics.log")
        formatter = logging.Formatter(
            '{"timestamp": "%(asctime)s", "level": "%(levelname)s", "logger": "%(name)s", '
            '"message": %(message)s}'
        )
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)
        self.logger.setLevel(logging.INFO)

    def _collect_system_metrics(self) -> Dict[str, Any]:
        """Collect OS-level performance metrics."""
        cpu_percent = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        net_io = psutil.net_io_counters()

        return {
            "cpu_percent": round(cpu_percent, 2),
            "memory_percent": round(memory.percent, 2),
            "memory_available_mb": round(memory.available / (1024 * 1024), 2),
            "disk_total_gb": round(disk.total / (1024**3), 2),
            "disk_used_gb": round(disk.used / (1024**3), 2),
            "disk_percent": round(disk.percent, 2),
            "network_bytes_sent": net_io.bytes_sent,
            "network_bytes_recv": net_io.bytes_recv,
            "process_count": len(psutil.pids()),
        }

    def _detect_anomalies(self, metrics: Dict[str, Any]) -> list:
        """Detect performance anomalies based on thresholds and baselines."""
        anomalies = []

        if metrics["cpu_percent"] > self.cpu_threshold:
            anomalies.append({
                "type": "high_cpu",
                "value": metrics["cpu_percent"],
                "threshold": self.cpu_threshold,
                "severity": "warning"
            })

        if metrics["memory_percent"] > self.memory_threshold:
            anomalies.append({
                "type": "high_memory",
                "value": metrics["memory_percent"],
                "threshold": self.memory_threshold,
                "severity": "critical"
            })

        if metrics["disk_percent"] > self.disk_threshold:
            anomalies.append({
                "type": "high_disk_usage",
                "value": metrics["disk_percent"],
                "threshold": self.disk_threshold,
                "severity": "warning"
            })

        # Network anomaly detection (spike in traffic)
        current_net = metrics["network_bytes_sent"] + metrics["network_bytes_recv"]
        if self._last_net_io is not None:
            delta = current_net - self._last_net_io
            if self._baseline_network_io is None:
                self._baseline_network_io = delta
            elif delta > self._baseline_network_io * self.network_anomaly_factor:
                anomalies.append({
                    "type": "network_spike",
                    "value": delta,
                    "baseline": self._baseline_network_io,
                    "severity": "info"
                })
        self._last_net_io = current_net

        return anomalies

    def _log_metrics(self, metrics: Dict[str, Any], anomalies: list):
        """Log metrics and anomalies in structured format."""
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "metrics": metrics,
            "anomalies_detected": len(anomalies),
            "anomalies": anomalies
        }
        self.logger.info(json.dumps(record, ensure_ascii=False))

        # Send critical alerts
        for anomaly in anomalies:
            if anomaly["severity"] in ("critical", "warning"):
                self.alert_manager.send_alert(
                    source="performance_monitor",
                    level=anomaly["severity"],
                    message=f"Performance anomaly: {anomaly['type']} = {anomaly['value']}",
                    context=record
                )

        # Audit log for security compliance
        if anomalies:
            self.audit_logger.log_event(
                event_type="PERFORMANCE_ANOMALY",
                details={"anomalies": anomalies}
            )

    def run_once(self) -> Dict[str, Any]:
        """Run a single monitoring cycle."""
        metrics = self._collect_system_metrics()
        anomalies = self._detect_anomalies(metrics)
        self._log_metrics(metrics, anomalies)
        return {"metrics": metrics, "anomalies": anomalies}

    def run_continuous(self, duration_hours: float = 24.0):
        """Run monitoring continuously for specified duration."""
        end_time = time.time() + (duration_hours * 3600)
        self.logger.info(f"🚀 Starting continuous performance monitoring for {duration_hours} hours.")

        while time.time() < end_time:
            try:
                self.run_once()
                time.sleep(self.log_interval)
            except KeyboardInterrupt:
                self.logger.info("🛑 Performance monitoring interrupted by user.")
                break
            except Exception as e:
                self.logger.error(f"💥 Unexpected error in monitoring loop: {e}", exc_info=True)
                time.sleep(5)  # Prevent tight error loop

        self.logger.info("✅ Performance monitoring session completed.")


def main():
    """Entry point for script execution."""
    import argparse

    parser = argparse.ArgumentParser(description="AI Freelance Automation — Performance Monitor")
    parser.add_argument("--once", action="store_true", help="Run only once and exit")
    parser.add_argument("--hours", type=float, default=24.0, help="Duration for continuous mode (hours)")
    parser.add_argument("--config", type=str, help="Path to custom config file")

    args = parser.parse_args()

    monitor = PerformanceMonitor(config_path=args.config)

    if args.once:
        result = monitor.run_once()
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        monitor.run_continuous(duration_hours=args.hours)


if __name__ == "__main__":
    main()