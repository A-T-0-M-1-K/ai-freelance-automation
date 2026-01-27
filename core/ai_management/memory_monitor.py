# AI_FREELANCE_AUTOMATION/core/ai_management/memory_monitor.py
"""
Memory Monitor for AI Models

Continuously tracks memory usage of loaded AI models and system resources.
Triggers alerts or model offloading when thresholds are exceeded.
Integrates with IntelligentModelManager and IntelligentMonitoringSystem.

Key Features:
- Real-time memory tracking per model
- Threshold-based alerting
- Automatic offloading suggestions
- Integration with system health metrics
- Thread-safe operation
"""

import asyncio
import logging
import psutil
import threading
from typing import Dict, Optional, Callable, Any
from dataclasses import dataclass
from datetime import datetime

# Local imports (relative to avoid circular dependencies)
from ..monitoring.intelligent_monitoring_system import MetricsCollector
from ..config.unified_config_manager import UnifiedConfigManager

logger = logging.getLogger(__name__)


@dataclass
class ModelMemorySnapshot:
    """Represents a point-in-time memory usage of a model."""
    model_id: str
    process_memory_mb: float
    gpu_memory_mb: Optional[float]
    timestamp: datetime
    metadata: Dict[str, Any]


class MemoryMonitor:
    """
    Monitors memory consumption of AI models and overall system.
    Designed to work alongside IntelligentModelManager.
    """

    def __init__(
        self,
        config_manager: UnifiedConfigManager,
        metrics_collector: Optional[MetricsCollector] = None,
        on_threshold_exceeded: Optional[Callable[[str, float], None]] = None
    ):
        """
        Initialize the memory monitor.

        :param config_manager: Unified configuration manager
        :param metrics_collector: Optional external metrics collector
        :param on_threshold_exceeded: Callback when memory threshold is breached
        """
        self.config = config_manager.get_section("ai_management.memory_monitor")
        self.metrics_collector = metrics_collector
        self.on_threshold_exceeded = on_threshold_exceeded

        # Internal state
        self._snapshots: Dict[str, ModelMemorySnapshot] = {}
        self._system_snapshot: Optional[Dict[str, float]] = None
        self._lock = threading.RLock()
        self._running = False
        self._monitor_task: Optional[asyncio.Task] = None

        # Load thresholds from config
        self.system_memory_threshold_percent = self.config.get("system_memory_threshold_percent", 85.0)
        self.per_model_memory_limit_mb = self.config.get("per_model_memory_limit_mb", 4096.0)
        self.check_interval_seconds = self.config.get("check_interval_seconds", 10)

        logger.info("Intialized MemoryMonitor with config: "
                    f"sys_thresh={self.system_memory_threshold_percent}%, "
                    f"model_limit={self.per_model_memory_limit_mb}MB, "
                    f"interval={self.check_interval_seconds}s")

    async def start_monitoring(self):
        """Start continuous memory monitoring in background."""
        if self._running:
            logger.warning("MemoryMonitor already running.")
            return

        self._running = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        logger.info("✅ MemoryMonitor started.")

    async def stop_monitoring(self):
        """Stop monitoring gracefully."""
        if not self._running:
            return

        self._running = False
        if self._monitor_task:
            await self._monitor_task
        logger.info("⏹️ MemoryMonitor stopped.")

    async def _monitor_loop(self):
        """Main monitoring loop."""
        while self._running:
            try:
                await self._collect_and_analyze()
                await asyncio.sleep(self.check_interval_seconds)
            except Exception as e:
                logger.error(f"Error in memory monitoring loop: {e}", exc_info=True)
                # Do not crash — continue monitoring

    async def _collect_and_analyze(self):
        """Collect system and model memory, then analyze thresholds."""
        with self._lock:
            # 1. System-wide memory
            system_mem = psutil.virtual_memory()
            system_usage_percent = system_mem.percent
            available_mb = system_mem.available / (1024 * 1024)

            self._system_snapshot = {
                "total_mb": system_mem.total / (1024 * 1024),
                "available_mb": available_mb,
                "used_percent": system_usage_percent,
            }

            # Report to global metrics
            if self.metrics_collector:
                self.metrics_collector.record("system.memory.used_percent", system_usage_percent)
                self.metrics_collector.record("system.memory.available_mb", available_mb)

            # 2. Check system threshold
            if system_usage_percent > self.system_memory_threshold_percent:
                logger.warning(
                    f"MemoryWarning: System memory usage at {system_usage_percent:.1f}% "
                    f"(threshold: {self.system_memory_threshold_percent}%)"
                )
                if self.on_threshold_exceeded:
                    self.on_threshold_exceeded("system", system_usage_percent)

            # 3. TODO: Per-model memory tracking (requires model-process mapping)
            # For now, log placeholder
            logger.debug("Per-model memory tracking: not implemented (requires GPU/process hooks)")

    def record_model_snapshot(
        self,
        model_id: str,
        process_memory_mb: float,
        gpu_memory_mb: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """
        Manually record a memory snapshot for a specific model.
        Called by IntelligentModelManager after model load/inference.

        :param model_id: Unique identifier of the model
        :param process_memory_mb: RAM used by the model process (MB)
        :param gpu_memory_mb: VRAM used (if applicable)
        :param metadata: Additional context (e.g., batch size, input length)
        """
        with self._lock:
            snapshot = ModelMemorySnapshot(
                model_id=model_id,
                process_memory_mb=process_memory_mb,
                gpu_memory_mb=gpu_memory_mb,
                timestamp=datetime.utcnow(),
                metadata=metadata or {}
            )
            self._snapshots[model_id] = snapshot

            # Check per-model limit
            if process_memory_mb > self.per_model_memory_limit_mb:
                msg = (
                    f"Model {model_id} exceeds memory limit: "
                    f"{process_memory_mb:.1f}MB > {self.per_model_memory_limit_mb}MB"
                )
                logger.warning(msg)
                if self.on_threshold_exceeded:
                    self.on_threshold_exceeded(model_id, process_memory_mb)

            # Report to metrics
            if self.metrics_collector:
                self.metrics_collector.record(f"model.{model_id}.memory.ram_mb", process_memory_mb)
                if gpu_memory_mb is not None:
                    self.metrics_collector.record(f"model.{model_id}.memory.vram_mb", gpu_memory_mb)

    def get_latest_snapshot(self, model_id: str) -> Optional[ModelMemorySnapshot]:
        """Retrieve the latest memory snapshot for a model."""
        with self._lock:
            return self._snapshots.get(model_id)

    def get_system_memory_status(self) -> Dict[str, float]:
        """Get latest system memory status."""
        with self._lock:
            return self._system_snapshot.copy() if self._system_snapshot else {}

    def get_all_snapshots(self) -> Dict[str, ModelMemorySnapshot]:
        """Get all model snapshots (read-only copy)."""
        with self._lock:
            return self._snapshots.copy()

    def clear_snapshots(self):
        """Clear all recorded snapshots (e.g., after model unload)."""
        with self._lock:
            self._snapshots.clear()
            logger.debug("Cleared all model memory snapshots.")