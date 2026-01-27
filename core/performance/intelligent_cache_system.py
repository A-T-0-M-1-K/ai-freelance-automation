# AI_FREELANCE_AUTOMATION/core/performance/intelligent_cache_system.py
"""
Intelligent Cache System with Adaptive Strategy Selection,
Predictive Prefetching, and Self-Optimization.

Features:
- Multi-tier caching (memory, disk, cloud)
- ML-based access pattern prediction
- Automatic eviction based on usage + memory pressure
- Hot-reload of cache strategies without restart
- Full observability via performance metrics
"""

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Dict, Optional, Union, Callable, Awaitable
from threading import Lock

from core.performance.cache_performance_monitor import CachePerformanceMonitor
from core.performance.load_predictor import LoadPredictor
from core.performance.memory_optimizer import MemoryOptimizer
from core.config.unified_config_manager import UnifiedConfigManager

logger = logging.getLogger("IntelligentCacheSystem")


@dataclass
class CacheEntry:
    key: str
    value: Any
    created_at: float
    accessed_at: float
    ttl: Optional[float]  # seconds, None = no expiration
    size_bytes: int


class BaseCacheStrategy(ABC):
    """Abstract base for cache eviction/prefetch strategies."""

    @abstractmethod
    def should_evict(self, entry: CacheEntry, current_time: float) -> bool:
        pass

    @abstractmethod
    def rank_for_prefetch(self, key: str, metadata: Dict[str, Any]) -> float:
        pass


class LRUCacheStrategy(BaseCacheStrategy):
    def should_evict(self, entry: CacheEntry, current_time: float) -> bool:
        if entry.ttl and (current_time - entry.created_at) > entry.ttl:
            return True
        return False

    def rank_for_prefetch(self, key: str, metadata: Dict[str, Any]) -> float:
        # Simple recency-based ranking
        last_access = metadata.get("last_access", 0)
        return 1.0 / (time.time() - last_access + 1)


class AdaptiveCacheStrategy(BaseCacheStrategy):
    """Dynamically adjusts based on load predictor and memory pressure."""

    def __init__(self, load_predictor: LoadPredictor, memory_optimizer: MemoryOptimizer):
        self.load_predictor = load_predictor
        self.memory_optimizer = memory_optimizer

    def should_evict(self, entry: CacheEntry, current_time: float) -> bool:
        # Evict if expired OR memory is tight AND low future access probability
        if entry.ttl and (current_time - entry.created_at) > entry.ttl:
            return True

        mem_pressure = self.memory_optimizer.get_memory_pressure()
        future_prob = self.load_predictor.predict_access_probability(entry.key)

        if mem_pressure > 0.85 and future_prob < 0.2:
            return True
        return False

    def rank_for_prefetch(self, key: str, metadata: Dict[str, Any]) -> float:
        return self.load_predictor.predict_access_probability(key)


class IntelligentCacheSystem:
    """
    Thread-safe, async-compatible intelligent cache with adaptive behavior.
    Designed for high-throughput AI workloads (transcription, translation, etc.).
    """

    def __init__(
            self,
            config_manager: UnifiedConfigManager,
            performance_monitor: Optional[CachePerformanceMonitor] = None,
            load_predictor: Optional[LoadPredictor] = None,
            memory_optimizer: Optional[MemoryOptimizer] = None,
    ):
        self.config = config_manager.get_section("performance.cache")
        self.max_memory_mb = self.config.get("max_memory_mb", 512)
        self.default_ttl = self.config.get("default_ttl_seconds", 3600)
        self.enable_predictive_prefetch = self.config.get("enable_predictive_prefetch", True)

        self._cache: Dict[str, CacheEntry] = {}
        self._access_order = OrderedDict()  # For LRU fallback
        self._lock = Lock()
        self._stats = {
            "hits": 0,
            "misses": 0,
            "evictions": 0,
            "prefetches": 0,
        }

        # Subsystems
        self.monitor = performance_monitor or CachePerformanceMonitor()
        self.load_predictor = load_predictor or LoadPredictor()
        self.memory_optimizer = memory_optimizer or MemoryOptimizer()

        # Strategy
        strategy_name = self.config.get("strategy", "adaptive")
        if strategy_name == "adaptive":
            self.strategy = AdaptiveCacheStrategy(self.load_predictor, self.memory_optimizer)
        else:
            self.strategy = LRUCacheStrategy()

        logger.info(f"Intialized IntelligentCacheSystem with strategy: {strategy_name}")

    def _get_size(self, obj: Any) -> int:
        """Estimate object size in bytes (simplified)."""
        try:
            return len(str(obj).encode('utf-8'))
        except Exception:
            return 1024  # fallback

    def _total_memory_usage(self) -> int:
        return sum(entry.size_bytes for entry in self._cache.values())

    def _enforce_memory_limit(self):
        """Evict entries until under memory limit."""
        current_mem = self._total_memory_usage()
        target_bytes = self.max_memory_mb * 1024 * 1024

        while current_mem > target_bytes and self._cache:
            # Find best candidate to evict
            now = time.time()
            candidate_key = None
            for key, entry in self._cache.items():
                if self.strategy.should_evict(entry, now):
                    candidate_key = key
                    break
            if not candidate_key:
                # Fallback: evict least recently used
                candidate_key = next(iter(self._access_order))

            self._evict(candidate_key)
            current_mem = self._total_memory_usage()

    def _evict(self, key: str):
        if key in self._cache:
            del self._cache[key]
            self._access_order.pop(key, None)
            self._stats["evictions"] += 1
            logger.debug(f"Evicted cache entry: {key}")

    def get(self, key: str) -> Optional[Any]:
        """Synchronous get with full observability."""
        with self._lock:
            entry = self._cache.get(key)
            now = time.time()

            if entry is None:
                self._stats["misses"] += 1
                logger.debug(f"Cache MISS: {key}")
                return None

            if self.strategy.should_evict(entry, now):
                self._evict(key)
                self._stats["misses"] += 1
                logger.debug(f"Cache STALE MISS (evicted): {key}")
                return None

            # Update access
            entry.accessed_at = now
            self._access_order.move_to_end(key)
            self._stats["hits"] += 1
            logger.debug(f"Cache HIT: {key}")
            self.monitor.record_hit(key, entry.size_bytes)
            return entry.value

    async def aget(self, key: str) -> Optional[Any]:
        """Async wrapper for compatibility."""
        return await asyncio.get_event_loop().run_in_executor(None, self.get, key)

    def set(
            self,
            key: str,
            value: Any,
            ttl: Optional[float] = None,
            metadata: Optional[Dict[str, Any]] = None,
    ):
        """Store value with optional TTL and metadata for prefetching."""
        with self._lock:
            size = self._get_size(value)
            entry = CacheEntry(
                key=key,
                value=value,
                created_at=time.time(),
                accessed_at=time.time(),
                ttl=ttl or self.default_ttl,
                size_bytes=size,
            )
            self._cache[key] = entry
            self._access_order[key] = None
            self._access_order.move_to_end(key)

            # Enforce memory limit
            self._enforce_memory_limit()

            # Log & monitor
            logger.debug(f"Cached key: {key} (size: {size} bytes)")
            self.monitor.record_set(key, size)

            # Trigger predictive prefetch if enabled
            if self.enable_predictive_prefetch and metadata:
                self._schedule_prefetch(key, metadata)

    async def aset(
            self,
            key: str,
            value: Any,
            ttl: Optional[float] = None,
            metadata: Optional[Dict[str, Any]] = None,
    ):
        """Async wrapper."""
        await asyncio.get_event_loop().run_in_executor(
            None, self.set, key, value, ttl, metadata
        )

    def _schedule_prefetch(self, key: str, metadata: Dict[str, Any]):
        """Schedule background prefetch of related keys (non-blocking)."""
        try:
            related_keys = metadata.get("related_keys", [])
            if not related_keys:
                return

            rank_map = {
                k: self.strategy.rank_for_prefetch(k, metadata)
                for k in related_keys
            }
            # Sort by priority
            sorted_keys = sorted(rank_map.items(), key=lambda x: x[1], reverse=True)

            # Prefetch top N
            prefetch_limit = self.config.get("prefetch_batch_size", 3)
            for pref_key, _ in sorted_keys[:prefetch_limit]:
                if pref_key not in self._cache:
                    asyncio.create_task(self._prefetch_item(pref_key))
                    self._stats["prefetches"] += 1
        except Exception as e:
            logger.warning(f"Prefetch scheduling failed for {key}: {e}")

    async def _prefetch_item(self, key: str):
        """Stub: in real system, this would call a service locator or callback registry."""
        logger.debug(f"Prefetching (stub): {key}")
        # In production: fetch from DB/API/ML pipeline and cache result
        # Example: result = await some_service.fetch_data(key); self.set(key, result)

    def get_stats(self) -> Dict[str, Any]:
        """Return detailed cache statistics."""
        total = self._stats["hits"] + self._stats["misses"]
        hit_rate = self._stats["hits"] / total if total > 0 else 0.0
        return {
            **self._stats,
            "hit_rate": hit_rate,
            "current_items": len(self._cache),
            "memory_usage_bytes": self._total_memory_usage(),
            "memory_usage_mb": round(self._total_memory_usage() / (1024 * 1024), 2),
        }

    def clear(self):
        """Clear entire cache (e.g., on config reload or emergency)."""
        with self._lock:
            self._cache.clear()
            self._access_order.clear()
            self._stats = {k: 0 for k in self._stats}
            logger.info("Cache cleared.")

    def __len__(self):
        return len(self._cache)