# AI_FREELANCE_AUTOMATION/core/performance/strategy_selector.py

"""
Dynamic Strategy Selector for Performance Optimization.

Selects optimal caching, memory, and execution strategies based on:
- Current system load (CPU, RAM, GPU)
- Task type (transcription, translation, copywriting, etc.)
- Client priority & deadline urgency
- Historical performance metrics
- Resource availability

Ensures no conflicts with other components via service locator and config validation.
"""

import logging
from typing import Dict, Any, Optional, Literal
from enum import Enum

from core.dependency.service_locator import ServiceLocator
from core.config.unified_config_manager import UnifiedConfigManager
from core.monitoring.metrics_collector import MetricsCollector

logger = logging.getLogger(__name__)


class StrategyType(Enum):
    """Available performance strategy types."""
    LOW_LATENCY = "low_latency"
    HIGH_THROUGHPUT = "high_throughput"
    MEMORY_CONSERVATIVE = "memory_conservative"
    BALANCED = "balanced"
    ENERGY_EFFICIENT = "energy_efficient"
    AI_MODEL_OPTIMIZED = "ai_model_optimized"


class CachingStrategy(Enum):
    """Caching behavior options."""
    AGGRESSIVE = "aggressive"  # Cache all intermediate results
    SELECTIVE = "selective"  # Cache only high-value results
    MINIMAL = "minimal"  # Cache only final deliverables
    NONE = "none"  # Disable caching


class ExecutionMode(Enum):
    """Execution parallelism modes."""
    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"
    HYBRID = "hybrid"


class StrategySelector:
    """
    Dynamically selects optimal performance strategies based on real-time context.

    Integrates with:
    - MetricsCollector (for live system stats)
    - LoadPredictor (for future load estimation)
    - MemoryOptimizer (for RAM/GPU pressure signals)
    - ConfigManager (for user-defined constraints)
    """

    def __init__(self, config: Optional[UnifiedConfigManager] = None):
        self.config = config or ServiceLocator.get("config")
        self.metrics_collector: MetricsCollector = ServiceLocator.get("metrics_collector")
        self._strategies_cache: Dict[str, Dict[str, Any]] = {}
        self._last_load_check = 0.0
        self._initialized = False
        self._validate_config()

    def _validate_config(self) -> None:
        """Validates performance-related configuration."""
        perf_config = self.config.get("performance", {})
        required_keys = {"strategy_selection_thresholds", "default_strategy", "caching_policy"}
        if not all(k in perf_config for k in required_keys):
            raise ValueError("Missing required keys in performance config")
        self._initialized = True

    def select_strategy(
            self,
            task_type: str,
            client_priority: Literal["low", "medium", "high", "critical"] = "medium",
            deadline_hours: float = 24.0,
            estimated_resource_usage: Optional[Dict[str, float]] = None
    ) -> Dict[str, Any]:
        """
        Selects the optimal performance strategy for a given task.

        Args:
            task_type: e.g., 'transcription', 'translation', 'copywriting'
            client_priority: Client importance level
            deadline_hours: Time until deadline
            estimated_resource_usage: Estimated CPU/RAM/GPU usage (optional)

        Returns:
            Dict containing selected strategies:
            {
                "strategy_type": StrategyType,
                "caching": CachingStrategy,
                "execution_mode": ExecutionMode,
                "model_precision": "fp16" | "fp32" | "int8",
                "batch_size": int,
                "prefetch_window": int
            }
        """
        if not self._initialized:
            raise RuntimeError("StrategySelector not initialized")

        # Generate cache key
        cache_key = f"{task_type}_{client_priority}_{deadline_hours}"
        if cache_key in self._strategies_cache:
            return self._strategies_cache[cache_key]

        # Gather current system state
        metrics = self.metrics_collector.get_current_metrics()
        cpu_load = metrics.get("cpu_utilization", 0.0)
        ram_usage = metrics.get("ram_usage_percent", 0.0)
        gpu_available = metrics.get("gpu_available", False)
        active_tasks = metrics.get("active_task_count", 0)

        # Predict short-term load (if available)
        load_predictor = ServiceLocator.get_optional("load_predictor")
        predicted_load = load_predictor.predict_next_hour() if load_predictor else None

        # Determine urgency
        is_urgent = deadline_hours <= 2.0
        is_high_value = client_priority in ("high", "critical")

        # Base strategy selection logic
        strategy_type = self._determine_strategy_type(
            cpu_load, ram_usage, gpu_available, is_urgent, is_high_value, active_tasks
        )
        caching = self._determine_caching_strategy(strategy_type, task_type)
        execution_mode = self._determine_execution_mode(strategy_type, active_tasks)
        model_precision = self._determine_model_precision(gpu_available, strategy_type)
        batch_size = self._calculate_batch_size(strategy_type, ram_usage, gpu_available)
        prefetch_window = self._calculate_prefetch_window(strategy_type, task_type)

        result = {
            "strategy_type": strategy_type.value,
            "caching": caching.value,
            "execution_mode": execution_mode.value,
            "model_precision": model_precision,
            "batch_size": batch_size,
            "prefetch_window": prefetch_window,
            "timestamp": metrics.get("timestamp", 0)
        }

        # Cache for reuse (TTL handled externally)
        self._strategies_cache[cache_key] = result
        logger.debug(f"Selected strategy for {cache_key}: {result}")

        return result

    def _determine_strategy_type(
            self,
            cpu_load: float,
            ram_usage: float,
            gpu_available: bool,
            is_urgent: bool,
            is_high_value: bool,
            active_tasks: int
    ) -> StrategyType:
        """Chooses high-level strategy based on system state and task context."""
        perf_config = self.config.get("performance", {})
        thresholds = perf_config["strategy_selection_thresholds"]

        # Critical path: urgent + high-value → low latency
        if is_urgent and is_high_value:
            return StrategyType.LOW_LATENCY

        # High memory pressure → memory conservative
        if ram_usage > thresholds.get("high_memory_threshold", 0.85):
            return StrategyType.MEMORY_CONSERVATIVE

        # Low load + non-urgent → energy efficient
        if cpu_load < thresholds.get("low_cpu_threshold", 0.3) and not is_urgent:
            return StrategyType.ENERGY_EFFICIENT

        # Many concurrent tasks → high throughput
        if active_tasks > thresholds.get("high_concurrency_threshold", 20):
            return StrategyType.HIGH_THROUGHPUT

        # GPU available + AI task → model optimized
        if gpu_available and active_tasks > 0:
            return StrategyType.AI_MODEL_OPTIMIZED

        # Default
        return StrategyType.BALANCED

    def _determine_caching_strategy(
            self, strategy_type: StrategyType, task_type: str
    ) -> CachingStrategy:
        """Selects caching behavior based on strategy and task."""
        if strategy_type == StrategyType.MEMORY_CONSERVATIVE:
            return CachingStrategy.MINIMAL
        if strategy_type == StrategyType.LOW_LATENCY:
            return CachingStrategy.AGGRESSIVE
        if task_type in ("transcription", "translation"):
            return CachingStrategy.SELECTIVE  # Reusable outputs
        return CachingStrategy.MINIMAL

    def _determine_execution_mode(
            self, strategy_type: StrategyType, active_tasks: int
    ) -> ExecutionMode:
        """Chooses execution parallelism."""
        if strategy_type == StrategyType.LOW_LATENCY:
            return ExecutionMode.SEQUENTIAL  # Minimize context switching
        if active_tasks > 10:
            return ExecutionMode.HYBRID
        return ExecutionMode.PARALLEL

    def _determine_model_precision(self, gpu_available: bool, strategy_type: StrategyType) -> str:
        """Selects model precision for AI inference."""
        if not gpu_available:
            return "fp32"
        if strategy_type == StrategyType.MEMORY_CONSERVATIVE:
            return "int8"
        if strategy_type == StrategyType.LOW_LATENCY:
            return "fp16"  # Best speed/accuracy tradeoff on GPU
        return "fp16"

    def _calculate_batch_size(
            self, strategy_type: StrategyType, ram_usage: float, gpu_available: bool
    ) -> int:
        """Dynamically adjusts batch size."""
        base_size = 4
        if strategy_type == StrategyType.HIGH_THROUGHPUT:
            base_size = 16
        elif strategy_type == StrategyType.MEMORY_CONSERVATIVE:
            base_size = 1

        if ram_usage > 0.8:
            base_size = max(1, base_size // 2)
        if not gpu_available:
            base_size = min(4, base_size)

        return base_size

    def _calculate_prefetch_window(self, strategy_type: StrategyType, task_type: str) -> int:
        """Determines how far ahead to prefetch data."""
        if strategy_type == StrategyType.LOW_LATENCY:
            return 0  # No prefetching — immediate execution
        if task_type in ("transcription", "translation"):
            return 3  # Prefetch next 3 segments
        return 1

    def clear_cache(self) -> None:
        """Clears internal strategy cache (e.g., after config reload)."""
        self._strategies_cache.clear()
        logger.info("Strategy selector cache cleared.")

    def get_supported_strategies(self) -> Dict[str, list]:
        """Returns all supported strategy options (for UI/API)."""
        return {
            "strategy_types": [s.value for s in StrategyType],
            "caching_strategies": [c.value for c in CachingStrategy],
            "execution_modes": [m.value for m in ExecutionMode],
            "model_precisions": ["fp32", "fp16", "int8"]
        }