# AI_FREELANCE_AUTOMATION/core/monitoring/resource_optimizer.py
"""
Resource Optimizer — динамически управляет вычислительными ресурсами системы
на основе текущей нагрузки, приоритетов задач и предсказаний от predictive_analytics.
Цель: максимизировать эффективность, минимизировать задержки и избежать перегрузки.
"""

import asyncio
import logging
import psutil
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from datetime import datetime, timedelta

from core.config.config_manager import UnifiedConfigManager
from core.monitoring.metrics_collector import MetricsCollector
from core.monitoring.threshold_manager import ThresholdManager
from core.ai_management.intelligent_model_manager import IntelligentModelManager
from core.dependency.service_locator import ServiceLocator

logger = logging.getLogger("ResourceOptimizer")


@dataclass
class ResourceAllocation:
    cpu_cores: int
    memory_mb: int
    gpu_memory_mb: Optional[int] = None
    io_priority: int = 1  # 1-5, где 5 — highest


class ResourceOptimizer:
    """
    Оптимизатор ресурсов. Работает в фоне, адаптируя распределение CPU, RAM, GPU
    под текущие задачи (например: транскрибация vs копирайтинг).
    Интегрируется с:
      - MetricsCollector (для получения данных)
      - ThresholdManager (для реакции на пороги)
      - ModelManager (для управления загрузкой моделей)
    """

    def __init__(
        self,
        config_manager: UnifiedConfigManager,
        metrics_collector: MetricsCollector,
        threshold_manager: ThresholdManager,
        model_manager: IntelligentModelManager,
    ):
        self.config = config_manager.get_section("performance")
        self.metrics = metrics_collector
        self.thresholds = threshold_manager
        self.model_manager = model_manager
        self._running = False
        self._last_optimization = datetime.min
        self._optimization_interval = self.config.get("resource_optimization_interval_sec", 30)
        self._cooldown_period = timedelta(seconds=self.config.get("optimization_cooldown_sec", 60))

        # Параметры ограничений
        self._max_cpu_percent = self.config.get("max_cpu_usage_percent", 85)
        self._max_memory_percent = self.config.get("max_memory_usage_percent", 80)
        self._min_free_memory_mb = self.config.get("min_free_memory_mb", 1024)

        logger.info("Intialized ResourceOptimizer with config: %s", {
            "interval_sec": self._optimization_interval,
            "max_cpu%": self._max_cpu_percent,
            "max_mem%": self._max_memory_percent,
        })

    async def start(self):
        """Запуск фонового оптимизатора."""
        if self._running:
            logger.warning("ResourceOptimizer уже запущен.")
            return
        self._running = True
        logger.info("🚀 Запущен ResourceOptimizer.")
        while self._running:
            try:
                await self._optimize_cycle()
                await asyncio.sleep(self._optimization_interval)
            except Exception as e:
                logger.error("❌ Ошибка в цикле ResourceOptimizer: %s", e, exc_info=True)
                await asyncio.sleep(5)  # избежать спама

    async def stop(self):
        """Остановка оптимизатора."""
        self._running = False
        logger.info("⏹️ Остановлен ResourceOptimizer.")

    async def _optimize_cycle(self):
        """Один цикл оптимизации ресурсов."""
        now = datetime.now()
        if now - self._last_optimization < self._cooldown_period:
            return  # соблюдаем cooldown

        try:
            system_load = self._get_system_load()
            active_jobs = await self._get_active_job_priorities()

            # Анализ: есть ли риск перегрузки?
            if self._is_overloaded(system_load):
                logger.warning("⚠️ Обнаружена перегрузка системы. Запуск оптимизации...")
                await self._apply_load_shedding(active_jobs)
            else:
                # Нормальный режим: балансировка
                await self._balance_resources(active_jobs, system_load)

            self._last_optimization = now
            logger.debug("✅ Цикл оптимизации завершён.")

        except Exception as e:
            logger.exception("💥 Необработанная ошибка в _optimize_cycle: %s", e)

    def _get_system_load(self) -> Dict[str, Any]:
        """Сбор метрик использования ресурсов."""
        cpu_percent = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        disk_io = psutil.disk_io_counters()
        net_io = psutil.net_io_counters()

        return {
            "cpu_percent": cpu_percent,
            "memory_percent": memory.percent,
            "memory_available_mb": memory.available // (1024 * 1024),
            "disk_read_mb": disk_io.read_bytes // (1024 * 1024) if disk_io else 0,
            "disk_write_mb": disk_io.write_bytes // (1024 * 1024) if disk_io else 0,
            "net_sent_mb": net_io.bytes_sent // (1024 * 1024) if net_io else 0,
            "net_recv_mb": net_io.bytes_recv // (1024 * 1024) if net_io else 0,
        }

    def _is_overloaded(self, load: Dict[str, Any]) -> bool:
        """Проверяет, превышены ли пороги нагрузки."""
        return (
            load["cpu_percent"] > self._max_cpu_percent or
            load["memory_percent"] > self._max_memory_percent or
            load["memory_available_mb"] < self._min_free_memory_mb
        )

    async def _get_active_job_priorities(self) -> List[Dict[str, Any]]:
        """
        Получает список активных задач с их приоритетами.
        Формат: [{"job_id": str, "priority": int (1-10), "type": str, "deadline": datetime}]
        """
        # В реальной системе это может быть вызов через ServiceLocator или JobRegistry
        job_service = ServiceLocator.get_service("job_registry")
        if not job_service:
            logger.warning("Job registry недоступен. Используем пустой список задач.")
            return []

        try:
            return await job_service.get_active_jobs_with_priority()
        except Exception as e:
            logger.error("Не удалось получить активные задачи: %s", e)
            return []

    async def _apply_load_shedding(self, jobs: List[Dict[str, Any]]):
        """Снижает нагрузку: приостанавливает низкоприоритетные задачи."""
        logger.info("📉 Применение load shedding для %d задач.", len(jobs))
        low_priority_jobs = [j for j in jobs if j["priority"] <= 3]

        for job in low_priority_jobs:
            try:
                logger.info("⏸️ Приостановка задачи %s (низкий приоритет)", job["job_id"])
                # Здесь можно вызвать workflow_orchestrator.pause(job_id)
                orchestrator = ServiceLocator.get_service("workflow_orchestrator")
                if orchestrator:
                    await orchestrator.pause_task(job["job_id"])
            except Exception as e:
                logger.error("Не удалось приостановить задачу %s: %s", job["job_id"], e)

        # Выгрузка неиспользуемых AI-моделей
        await self.model_manager.unload_low_priority_models()

    async def _balance_resources(self, jobs: List[Dict[str, Any]], load: Dict[str, Any]):
        """Балансирует ресурсы между задачами."""
        # Пример: если много задач транскрибации — выделить больше CPU/GPU
        transcription_count = sum(1 for j in jobs if j["type"] == "transcription")
        translation_count = sum(1 for j in jobs if j["type"] == "translation")

        if transcription_count > 0:
            # Whisper требует CPU/GPU — убедимся, что модель загружена
            await self.model_manager.ensure_model_loaded("whisper-medium")

        if translation_count > 0:
            await self.model_manager.ensure_model_loaded("nllb-200")

        # Динамическое масштабирование пулов потоков (в будущем — через auto_scaler)
        logger.debug(
            "⚖️ Балансировка: транскрибация=%d, перевод=%d, CPU=%.1f%%, RAM=%.1f%%",
            transcription_count, translation_count,
            load["cpu_percent"], load["memory_percent"]
        )

    def get_current_allocation(self) -> ResourceAllocation:
        """Возвращает текущее распределение ресурсов (для отладки/API)."""
        load = self._get_system_load()
        total_cpu = psutil.cpu_count()
        allocated_cpu = min(total_cpu, max(1, int(total_cpu * (load["cpu_percent"] / 100))))
        memory_total = psutil.virtual_memory().total // (1024 * 1024)
        allocated_mem = memory_total - load["memory_available_mb"]

        return ResourceAllocation(
            cpu_cores=allocated_cpu,
            memory_mb=allocated_mem,
            gpu_memory_mb=None,  # TODO: добавить через nvidia-ml-py или аналог
            io_priority=3
        )