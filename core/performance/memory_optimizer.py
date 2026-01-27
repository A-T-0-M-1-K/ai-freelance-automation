# core/performance/memory_optimizer.py
"""
Memory Optimizer — intelligently manages RAM usage across the system.
Frees unused caches, unloads idle AI models, and prevents memory leaks.
Works in background with adaptive thresholds based on system load and config.
"""

import asyncio
import gc
import logging
import weakref
from typing import Dict, Any, Optional, Set
from dataclasses import dataclass
from datetime import datetime, timedelta

from core.config.unified_config_manager import UnifiedConfigManager
from core.monitoring.intelligent_monitoring_system import IntelligentMonitoringSystem
from core.security.audit_logger import AuditLogger


@dataclass
class MemoryThresholds:
    """Dynamic memory thresholds based on system profile."""
    soft_limit_mb: int
    hard_limit_mb: int
    model_unload_threshold_mb: int
    cache_eviction_threshold_mb: int
    gc_frequency_seconds: int


class MemoryOptimizer:
    """
    Autonomous memory management system.
    - Tracks memory consumption
    - Triggers garbage collection
    - Requests cache eviction from intelligent_cache_system
    - Signals model unload to intelligent_model_manager
    - Logs all actions for audit and debugging
    """

    def __init__(
        self,
        config_manager: UnifiedConfigManager,
        monitoring_system: IntelligentMonitoringSystem,
        audit_logger: Optional[AuditLogger] = None
    ):
        self.config_manager = config_manager
        self.monitoring = monitoring_system
        self.audit_logger = audit_logger or AuditLogger("memory_optimizer")
        self.logger = logging.getLogger("MemoryOptimizer")

        # State
        self._running = False
        self._last_gc = datetime.min
        self._active_components: Set[str] = set()
        self._thresholds: Optional[MemoryThresholds] = None

        # Weak references to avoid circular dependencies
        self._cache_system_ref: Optional[weakref.ReferenceType] = None
        self._model_manager_ref: Optional[weakref.ReferenceType] = None

        self._load_config()

    def register_cache_system(self, cache_system: Any) -> None:
        """Register intelligent_cache_system for coordinated eviction."""
        self._cache_system_ref = weakref.ref(cache_system)

    def register_model_manager(self, model_manager: Any) -> None:
        """Register intelligent_model_manager for model unloading."""
        self._model_manager_ref = weakref.ref(model_manager)

    def _load_config(self) -> None:
        """Load and validate memory optimization settings."""
        perf_config = self.config_manager.get_section("performance") or {}
        mem_config = perf_config.get("memory", {})

        defaults = {
            "soft_limit_mb": 2048,
            "hard_limit_mb": 3072,
            "model_unload_threshold_mb": 2500,
            "cache_eviction_threshold_mb": 2200,
            "gc_frequency_seconds": 60
        }

        # Merge with defaults
        effective = {**defaults, **mem_config}

        self._thresholds = MemoryThresholds(
            soft_limit_mb=int(effective["soft_limit_mb"]),
            hard_limit_mb=int(effective["hard_limit_mb"]),
            model_unload_threshold_mb=int(effective["model_unload_threshold_mb"]),
            cache_eviction_threshold_mb=int(effective["cache_eviction_threshold_mb"]),
            gc_frequency_seconds=int(effective["gc_frequency_seconds"])
        )

        self.logger.info(f"Loaded memory thresholds: {self._thresholds}")

    async def start(self) -> None:
        """Start autonomous memory optimization loop."""
        if self._running:
            return
        self._running = True
        self.logger.info("🟢 Memory optimizer started.")
        asyncio.create_task(self._optimization_loop())

    async def stop(self) -> None:
        """Stop the optimizer gracefully."""
        self._running = False
        self.logger.info("⏹️ Memory optimizer stopped.")

    async def _optimization_loop(self) -> None:
        """Main background loop for memory optimization."""
        while self._running:
            try:
                await self._optimize_memory()
                await asyncio.sleep(10)  # Check every 10 seconds
            except Exception as e:
                self.logger.error(f"Unexpected error in memory optimization loop: {e}", exc_info=True)
                await asyncio.sleep(30)  # Backoff on failure

    async def _optimize_memory(self) -> None:
        """Perform one cycle of memory optimization."""
        if not self._thresholds:
            return

        # Get current memory usage (in MB)
        current_mb = self._get_current_memory_usage()
        self.monitoring.record_metric("system.memory_usage_mb", current_mb)

        self.logger.debug(f"Current memory usage: {current_mb:.1f} MB")

        # 1. Garbage collection (if overdue)
        now = datetime.now()
        if (now - self._last_gc).total_seconds() > self._thresholds.gc_frequency_seconds:
            collected = gc.collect()
            self._last_gc = now
            if collected > 0:
                self.logger.debug(f"Garbage collector freed {collected} objects.")
                self.audit_logger.log("memory.gc", {"objects_freed": collected})

        # 2. Cache eviction (if above threshold)
        if current_mb > self._thresholds.cache_eviction_threshold_mb:
            await self._trigger_cache_eviction(current_mb)

        # 3. Model unloading (if near hard limit)
        if current_mb > self._thresholds.model_unload_threshold_mb:
            await self._trigger_model_unload(current_mb)

        # 4. Emergency action (if hard limit breached)
        if current_mb > self._thresholds.hard_limit_mb:
            await self._emergency_cleanup(current_mb)

    def _get_current_memory_usage(self) -> float:
        """Get current process memory usage in MB."""
        try:
            import psutil
            process = psutil.Process()
            mem_info = process.memory_info()
            return mem_info.rss / (1024 * 1024)  # RSS in MB
        except ImportError:
            # Fallback: rough estimate (not recommended for production)
            self.logger.warning("psutil not available; using fallback memory estimation.")
            return len(gc.get_objects()) * 0.001  # Very rough proxy

    async def _trigger_cache_eviction(self, current_mb: float) -> None:
        """Request cache system to evict least recently used items."""
        if self._cache_system_ref is None:
            return
        cache_system = self._cache_system_ref()
        if cache_system is None:
            self.logger.warning("Cache system reference lost.")
            return

        target_reduction_mb = current_mb - self._thresholds.soft_limit_mb
        if target_reduction_mb <= 0:
            return

        self.logger.info(f"MemoryWarning: Requesting cache eviction (~{target_reduction_mb:.1f} MB)")
        try:
            await cache_system.evict_by_memory_target(target_reduction_mb)
            self.audit_logger.log("memory.cache_eviction", {
                "requested_mb": target_reduction_mb,
                "timestamp": datetime.utcnow().isoformat()
            })
        except Exception as e:
            self.logger.error(f"Cache eviction failed: {e}", exc_info=True)

    async def _trigger_model_unload(self, current_mb: float) -> None:
        """Request model manager to unload least recently used models."""
        if self._model_manager_ref is None:
            return
        model_manager = self._model_manager_ref()
        if model_manager is None:
            self.logger.warning("Model manager reference lost.")
            return

        excess_mb = current_mb - self._thresholds.model_unload_threshold_mb
        if excess_mb <= 0:
            return

        self.logger.info(f"MemoryWarning: Requesting model unload (~{excess_mb:.1f} MB)")
        try:
            await model_manager.unload_least_used_models(memory_pressure_mb=excess_mb)
            self.audit_logger.log("memory.model_unload", {
                "pressure_mb": excess_mb,
                "timestamp": datetime.utcnow().isoformat()
            })
        except Exception as e:
            self.logger.error(f"Model unload failed: {e}", exc_info=True)

    async def _emergency_cleanup(self, current_mb: float) -> None:
        """Emergency: force aggressive cleanup."""
        self.logger.critical(f"🚨 EMERGENCY: Memory usage ({current_mb:.1f} MB) exceeds hard limit!")
        self.audit_logger.log("memory.emergency", {
            "usage_mb": current_mb,
            "hard_limit_mb": self._thresholds.hard_limit_mb,
            "timestamp": datetime.utcnow().isoformat()
        })

        # Force full GC
        gc.collect()

        # Aggressive cache purge
        if self._cache_system_ref and self._cache_system_ref():
            await self._cache_system_ref().purge_all_non_essential()

        # Unload all non-active models
        if self._model_manager_ref and self._model_manager_ref():
            await self._model_manager_ref().unload_all_inactive_models()

        # Notify monitoring system
        self.monitoring.trigger_alert(
            "memory.critical",
            f"Memory usage at {current_mb:.1f} MB — emergency cleanup performed."
        )

    def mark_component_active(self, component_name: str) -> None:
        """Mark a component as active (to protect its resources)."""
        self._active_components.add(component_name)

    def mark_component_inactive(self, component_name: str) -> None:
        """Mark a component as inactive (eligible for cleanup)."""
        self._active_components.discard(component_name)
