# AI_FREELANCE_AUTOMATION/tools/testing/performance_test.py
"""
Performance testing suite for AI Freelance Automation System.
Measures system behavior under load: latency, throughput, memory usage, concurrency.
Integrates with monitoring and config systems. Safe for production diagnostics.
"""

import asyncio
import logging
import time
import tracemalloc
import psutil
import os
from typing import Dict, Any, Optional, List, Callable, Awaitable
from pathlib import Path

# Импорты из ядра — через service locator или напрямую (только read-only)
from core.config.unified_config_manager import UnifiedConfigManager
from core.monitoring.intelligent_monitoring_system import IntelligentMonitoringSystem
from core.security.audit_logger import AuditLogger

# Локальные импорты
from tools.testing.test_runner import TestResult

# Настройка логгера
logger = logging.getLogger("PerformanceTest")
logger.setLevel(logging.INFO)

# Путь к корню проекта (для относительных путей)
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent.resolve()


class PerformanceTest:
    """
    Comprehensive performance testing framework.
    Supports:
      - Memory profiling
      - CPU usage tracking
      - Latency & throughput measurement
      - Concurrent task simulation
      - Resource leak detection
    """

    def __init__(
            self,
            config: Optional[UnifiedConfigManager] = None,
            monitor: Optional[IntelligentMonitoringSystem] = None,
            audit_logger: Optional[AuditLogger] = None
    ):
        self.config = config or UnifiedConfigManager()
        self.monitor = monitor or IntelligentMonitoringSystem(self.config)
        self.audit_logger = audit_logger or AuditLogger()
        self.results: List[TestResult] = []
        self._is_running = False

    async def run_concurrent_load_test(
            self,
            task_factory: Callable[[], Awaitable[Any]],
            num_concurrent: int = 10,
            duration_seconds: int = 60
    ) -> Dict[str, Any]:
        """
        Запускает нагрузочный тест с параллельными задачами.

        Args:
            task_factory: Фабрика асинхронных задач (например, вызов transcription_service)
            num_concurrent: Количество одновременных задач
            duration_seconds: Длительность теста в секундах

        Returns:
            Сводка по производительности
        """
        if self._is_running:
            raise RuntimeError("Performance test already running")

        self._is_running = True
        logger.info(f"🚀 Starting concurrent load test: {num_concurrent} tasks for {duration_seconds}s")

        # Включаем трассировку памяти
        tracemalloc.start()

        # Снимаем начальные метрики
        process = psutil.Process(os.getpid())
        start_cpu = process.cpu_percent()
        start_memory = process.memory_info().rss / (1024 * 1024)  # MB
        start_time = time.time()

        tasks = []
        completed = 0
        errors = 0
        latencies: List[float] = []

        async def _wrapped_task():
            nonlocal completed, errors
            try:
                t0 = time.perf_counter()
                await task_factory()
                lat = time.perf_counter() - t0
                latencies.append(lat)
                completed += 1
            except Exception as e:
                errors += 1
                logger.warning(f"Task failed during load test: {e}")
            finally:
                # Ограничиваем общее время выполнения
                if time.time() - start_time > duration_seconds:
                    return

        # Запускаем цикл задач до истечения времени
        while time.time() - start_time < duration_seconds:
            if len(tasks) < num_concurrent:
                tasks.append(asyncio.create_task(_wrapped_task()))
            else:
                # Ждём завершения хотя бы одной задачи
                done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                tasks = list(pending)

        # Дожидаемся завершения всех оставшихся
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        # Финальные метрики
        end_time = time.time()
        end_memory = process.memory_info().rss / (1024 * 1024)
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        # Расчёт результатов
        total_duration = end_time - start_time
        throughput = completed / total_duration if total_duration > 0 else 0
        avg_latency = sum(latencies) / len(latencies) if latencies else 0
        p95_latency = sorted(latencies)[int(0.95 * len(latencies))] if latencies else 0
        memory_delta = end_memory - start_memory

        result = {
            "test_type": "concurrent_load",
            "duration_seconds": total_duration,
            "tasks_submitted": num_concurrent,
            "tasks_completed": completed,
            "errors": errors,
            "throughput_tasks_per_sec": throughput,
            "avg_latency_sec": avg_latency,
            "p95_latency_sec": p95_latency,
            "start_memory_mb": start_memory,
            "end_memory_mb": end_memory,
            "memory_delta_mb": memory_delta,
            "traced_memory_current_kb": current / 1024,
            "traced_memory_peak_kb": peak / 1024,
            "cpu_usage_start_percent": start_cpu,
            "cpu_usage_end_percent": process.cpu_percent(),
        }

        # Сохраняем результат
        self.results.append(TestResult(
            name="concurrent_load_test",
            status="passed" if errors == 0 else "failed",
            metrics=result,
            timestamp=end_time
        ))

        # Логируем в систему мониторинга
        await self.monitor.record_metric("performance_test.throughput", throughput)
        await self.monitor.record_metric("performance_test.avg_latency", avg_latency)
        await self.monitor.record_metric("performance_test.memory_delta_mb", memory_delta)

        # Аудит
        self.audit_logger.log_security_event(
            event_type="PERFORMANCE_TEST_EXECUTED",
            details={"result_summary": result}
        )

        logger.info(f"✅ Load test completed. Throughput: {throughput:.2f} tasks/sec, Errors: {errors}")

        self._is_running = False
        return result

    async def run_memory_leak_test(
            self,
            task_factory: Callable[[], Awaitable[Any]],
            iterations: int = 100
    ) -> Dict[str, Any]:
        """Проверяет утечки памяти при повторном выполнении задач."""
        logger.info(f"🔍 Starting memory leak test ({iterations} iterations)...")

        tracemalloc.start()
        initial_snapshot = tracemalloc.take_snapshot()

        for i in range(iterations):
            await task_factory()
            if i % 10 == 0:
                logger.debug(f"Memory leak test: iteration {i}/{iterations}")

        final_snapshot = tracemalloc.take_snapshot()
        tracemalloc.stop()

        # Анализ утечек
        top_stats = final_snapshot.compare_to(initial_snapshot, 'lineno')
        significant_leaks = [stat for stat in top_stats if stat.size_diff > 1024 * 10]  # >10KB

        result = {
            "test_type": "memory_leak",
            "iterations": iterations,
            "significant_leaks_count": len(significant_leaks),
            "top_leak_kb": significant_leaks[0].size_diff / 1024 if significant_leaks else 0,
            "leak_details": [
                {
                    "filename": stat.traceback.format()[-1].strip(),
                    "size_kb": stat.size_diff / 1024,
                    "count": stat.count_diff
                }
                for stat in significant_leaks[:5]
            ]
        }

        has_leak = len(significant_leaks) > 0
        self.results.append(TestResult(
            name="memory_leak_test",
            status="failed" if has_leak else "passed",
            metrics=result,
            timestamp=time.time()
        ))

        if has_leak:
            logger.warning("⚠️ Potential memory leak detected!")
        else:
            logger.info("✅ No significant memory leaks found.")

        return result

    def get_results(self) -> List[TestResult]:
        """Возвращает все накопленные результаты тестов."""
        return self.results

    def export_results_to_file(self, filepath: Optional[str] = None) -> str:
        """Экспортирует результаты в JSON-файл."""
        import json
        from datetime import datetime

        if filepath is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filepath = PROJECT_ROOT / "logs" / "performance" / f"perf_test_{timestamp}.json"

        os.makedirs(os.path.dirname(filepath), exist_ok=True)

        serializable = [
            {
                "name": r.name,
                "status": r.status,
                "metrics": r.metrics,
                "timestamp": r.timestamp
            }
            for r in self.results
        ]

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(serializable, f, indent=2, ensure_ascii=False)

        logger.info(f"📄 Performance results exported to: {filepath}")
        return str(filepath)


# Утилита для быстрого запуска из CLI (опционально)
if __name__ == "__main__":
    # Пример использования
    async def dummy_task():
        await asyncio.sleep(0.1)
        return "ok"


    async def main():
        tester = PerformanceTest()
        await tester.run_concurrent_load_test(dummy_task, num_concurrent=20, duration_seconds=10)
        await tester.run_memory_leak_test(dummy_task, iterations=50)
        tester.export_results_to_file()


    asyncio.run(main())