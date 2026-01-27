# AI_FREELANCE_AUTOMATION/core/performance/cache_performance_monitor.py
"""
Модуль мониторинга производительности кэш-системы.
Следит за hit rate, latency, размером кэша, частотой промахов,
обнаруживает деградацию и инициирует оптимизацию или восстановление.
"""

import asyncio
import logging
import time
from typing import Dict, Any, Optional
from dataclasses import dataclass
from collections import deque

from core.monitoring.metrics_collector import MetricsCollector
from core.security.audit_logger import AuditLogger
from core.dependency.service_locator import ServiceLocator


@dataclass
class CacheMetrics:
    """Структура для хранения метрик кэша."""
    timestamp: float
    hit_rate: float
    miss_rate: float
    avg_get_latency_ms: float
    avg_set_latency_ms: float
    cache_size_bytes: int
    evictions_count: int
    memory_usage_percent: float


class CachePerformanceMonitor:
    """
    Наблюдатель за производительностью кэш-системы.
    Работает асинхронно, собирает метрики каждые N секунд,
    сравнивает с порогами из конфигурации и реагирует на аномалии.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.logger = logging.getLogger("CachePerformanceMonitor")
        self.config = config or self._load_default_config()
        self.metrics_history: deque = deque(maxlen=self.config.get("history_window", 100))
        self.is_running = False
        self._monitor_task: Optional[asyncio.Task] = None

        # Зависимости через Service Locator (избегаем циклических импортов)
        self.metrics_collector: MetricsCollector = ServiceLocator.get("metrics_collector")
        self.audit_logger: AuditLogger = ServiceLocator.get("audit_logger")

        self.logger.info("Intialized CachePerformanceMonitor with config: %s", self.config)

    def _load_default_config(self) -> Dict[str, Any]:
        """Загружает конфигурацию по умолчанию, если не передана."""
        return {
            "monitoring_interval_sec": 10,
            "history_window": 100,
            "thresholds": {
                "min_hit_rate": 0.75,
                "max_avg_latency_ms": 50.0,
                "max_memory_usage_percent": 85.0,
                "max_eviction_rate_per_min": 100
            },
            "enable_anomaly_detection": True,
            "auto_optimize_on_degradation": True
        }

    async def start_monitoring(self):
        """Запускает цикл мониторинга в фоне."""
        if self.is_running:
            self.logger.warning("Monitoring already running.")
            return

        self.is_running = True
        self._monitor_task = asyncio.create_task(self._monitoring_loop())
        self.logger.info("✅ Cache performance monitoring started.")

    async def stop_monitoring(self):
        """Останавливает мониторинг."""
        if not self.is_running:
            return

        self.is_running = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        self.logger.info("⏹️ Cache performance monitoring stopped.")

    async def _monitoring_loop(self):
        """Основной цикл сбора метрик."""
        while self.is_running:
            try:
                metrics = await self._collect_current_metrics()
                self.metrics_history.append(metrics)
                await self._report_metrics(metrics)
                await self._analyze_and_react(metrics)
            except Exception as e:
                self.logger.error("❌ Error in cache monitoring loop: %s", e, exc_info=True)
                await self.audit_logger.log_security_event(
                    event_type="cache_monitoring_failure",
                    details={"error": str(e)},
                    severity="high"
                )
            finally:
                await asyncio.sleep(self.config["monitoring_interval_sec"])

    async def _collect_current_metrics(self) -> CacheMetrics:
        """Собирает актуальные метрики от кэш-системы."""
        cache_system = ServiceLocator.get("intelligent_cache_system")
        if not cache_system:
            raise RuntimeError("IntelligentCacheSystem not found in ServiceLocator")

        # Получаем метрики напрямую из кэш-системы
        stats = await cache_system.get_performance_stats()

        now = time.time()
        return CacheMetrics(
            timestamp=now,
            hit_rate=stats.get("hit_rate", 0.0),
            miss_rate=1.0 - stats.get("hit_rate", 0.0),
            avg_get_latency_ms=stats.get("avg_get_latency_ms", 0.0),
            avg_set_latency_ms=stats.get("avg_set_latency_ms", 0.0),
            cache_size_bytes=stats.get("cache_size_bytes", 0),
            evictions_count=stats.get("evictions_count", 0),
            memory_usage_percent=stats.get("memory_usage_percent", 0.0)
        )

    async def _report_metrics(self, metrics: CacheMetrics):
        """Отправляет метрики в централизованную систему мониторинга."""
        self.metrics_collector.record("cache.hit_rate", metrics.hit_rate)
        self.metrics_collector.record("cache.miss_rate", metrics.miss_rate)
        self.metrics_collector.record("cache.avg_get_latency_ms", metrics.avg_get_latency_ms)
        self.metrics_collector.record("cache.avg_set_latency_ms", metrics.avg_set_latency_ms)
        self.metrics_collector.record("cache.size_bytes", metrics.cache_size_bytes)
        self.metrics_collector.record("cache.evictions_total", metrics.evictions_count)
        self.metrics_collector.record("cache.memory_usage_percent", metrics.memory_usage_percent)

    async def _analyze_and_react(self, metrics: CacheMetrics):
        """Анализирует метрики и реагирует на проблемы."""
        thresholds = self.config["thresholds"]
        issues = []

        if metrics.hit_rate < thresholds["min_hit_rate"]:
            issues.append(f"Low hit rate: {metrics.hit_rate:.2%} < {thresholds['min_hit_rate']:.2%}")

        if metrics.avg_get_latency_ms > thresholds["max_avg_latency_ms"]:
            issues.append(f"High GET latency: {metrics.avg_get_latency_ms:.2f}ms > {thresholds['max_avg_latency_ms']}ms")

        if metrics.memory_usage_percent > thresholds["max_memory_usage_percent"]:
            issues.append(f"High memory usage: {metrics.memory_usage_percent:.2f}% > {thresholds['max_memory_usage_percent']}%")

        # Анализ скорости вытеснений (evictions)
        if len(self.metrics_history) >= 2:
            prev = self.metrics_history[-2]
            current = metrics
            time_diff_sec = current.timestamp - prev.timestamp
            if time_diff_sec > 0:
                eviction_rate = (current.evictions_count - prev.evictions_count) / (time_diff_sec / 60)
                if eviction_rate > thresholds["max_eviction_rate_per_min"]:
                    issues.append(f"High eviction rate: {eviction_rate:.1f}/min > {thresholds['max_eviction_rate_per_min']}/min")

        if issues:
            self.logger.warning("⚠️ Cache performance degradation detected: %s", "; ".join(issues))
            await self.audit_logger.log_security_event(
                event_type="cache_performance_degradation",
                details={"issues": issues, "metrics": metrics.__dict__},
                severity="medium"
            )

            # Автоматическая реакция
            if self.config.get("auto_optimize_on_degradation", False):
                await self._trigger_optimization(issues)

    async def _trigger_optimization(self, issues: list):
        """Инициирует оптимизацию кэш-стратегии."""
        try:
            strategy_selector = ServiceLocator.get("strategy_selector")
            if strategy_selector:
                self.logger.info("🔄 Triggering cache strategy optimization due to: %s", issues)
                await strategy_selector.optimize_strategy(reasons=issues)
            else:
                self.logger.warning("StrategySelector not available for optimization.")
        except Exception as e:
            self.logger.error("Failed to trigger cache optimization: %s", e)
            await self.audit_logger.log_security_event(
                event_type="cache_optimization_failure",
                details={"error": str(e)},
                severity="medium"
            )

    def get_latest_metrics(self) -> Optional[CacheMetrics]:
        """Возвращает последние собранные метрики (для отладки/UI)."""
        return self.metrics_history[-1] if self.metrics_history else None

    def get_health_status(self) -> Dict[str, Any]:
        """Возвращает статус здоровья кэш-системы."""
        latest = self.get_latest_metrics()
        if not latest:
            return {"status": "unknown", "reason": "no metrics collected yet"}

        thresholds = self.config["thresholds"]
        healthy = (
            latest.hit_rate >= thresholds["min_hit_rate"] and
            latest.avg_get_latency_ms <= thresholds["max_avg_latency_ms"] and
            latest.memory_usage_percent <= thresholds["max_memory_usage_percent"]
        )

        return {
            "status": "healthy" if healthy else "degraded",
            "last_update": latest.timestamp,
            "hit_rate": latest.hit_rate,
            "latency_ms": latest.avg_get_latency_ms,
            "memory_usage_percent": latest.memory_usage_percent
        }