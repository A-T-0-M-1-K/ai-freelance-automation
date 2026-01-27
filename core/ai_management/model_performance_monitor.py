# AI_FREELANCE_AUTOMATION/core/ai_management/model_performance_monitor.py
"""
Model Performance Monitor — отслеживает производительность, точность, задержки и ресурсоемкость AI-моделей.
Интегрируется с IntelligentMonitoringSystem для аномалий и predictive analytics.
Поддерживает hot-reload метрик и адаптивные пороги.
"""

import asyncio
import logging
import time
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta

# Локальные импорты (без циклических зависимостей)
from core.config.unified_config_manager import UnifiedConfigManager
from core.monitoring.intelligent_monitoring_system import IntelligentMonitoringSystem
from core.security.audit_logger import AuditLogger


@dataclass
class ModelMetrics:
    """Структура метрик модели."""
    model_id: str
    timestamp: datetime
    inference_time_sec: float
    memory_usage_mb: float
    cpu_usage_percent: float
    accuracy_score: Optional[float] = None
    token_per_sec: Optional[float] = None
    error_count: int = 0
    success_count: int = 0
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None


class ModelPerformanceMonitor:
    """
    Монитор производительности AI-моделей.
    Собирает метрики в реальном времени, обнаруживает деградацию,
    отправляет данные в центральный мониторинг и триггерит оптимизацию.
    """

    def __init__(
        self,
        config_manager: UnifiedConfigManager,
        monitoring_system: IntelligentMonitoringSystem,
        audit_logger: Optional[AuditLogger] = None
    ):
        self.config = config_manager.get_section("ai_management")
        self.monitoring_system = monitoring_system
        self.audit_logger = audit_logger or AuditLogger()
        self.logger = logging.getLogger("ModelPerformanceMonitor")

        # Внутреннее состояние
        self._metrics_buffer: Dict[str, List[ModelMetrics]] = {}
        self._running = False
        self._collection_interval = self.config.get("performance_collection_interval_sec", 30)
        self._retention_window = timedelta(hours=self.config.get("metrics_retention_hours", 24))

        self.logger.info("Intialized ModelPerformanceMonitor with interval=%ds", self._collection_interval)

    async def start(self):
        """Запуск фонового сбора метрик."""
        if self._running:
            self.logger.warning("ModelPerformanceMonitor уже запущен.")
            return
        self._running = True
        self.logger.info("🟢 Запуск фонового мониторинга производительности моделей...")
        asyncio.create_task(self._metrics_collection_loop())

    async def stop(self):
        """Остановка мониторинга."""
        self._running = False
        self.logger.info("⏹️ Остановка ModelPerformanceMonitor.")

    async def _metrics_collection_loop(self):
        """Основной цикл сбора и отправки метрик."""
        while self._running:
            try:
                await self._collect_and_send_metrics()
                await asyncio.sleep(self._collection_interval)
            except Exception as e:
                self.logger.error("❌ Ошибка в цикле сбора метрик: %s", e, exc_info=True)
                await self.audit_logger.log_security_event(
                    event_type="monitoring_failure",
                    details={"error": str(e), "component": "ModelPerformanceMonitor"}
                )

    async def _collect_and_send_metrics(self):
        """Собирает метрики из буфера, фильтрует устаревшие, отправляет в мониторинг."""
        now = datetime.utcnow()
        for model_id in list(self._metrics_buffer.keys()):
            # Удаляем устаревшие записи
            self._metrics_buffer[model_id] = [
                m for m in self._metrics_buffer[model_id]
                if now - m.timestamp <= self._retention_window
            ]
            if not self._metrics_buffer[model_id]:
                del self._metrics_buffer[model_id]
                continue

            # Агрегируем метрики
            recent = self._metrics_buffer[model_id][-10:]  # последние 10 записей
            avg_inference = sum(m.inference_time_sec for m in recent) / len(recent)
            avg_memory = sum(m.memory_usage_mb for m in recent) / len(recent)
            total_success = sum(m.success_count for m in recent)
            total_errors = sum(m.error_count for m in recent)
            error_rate = total_errors / (total_success + total_errors + 1e-8)

            # Отправка в центральный мониторинг
            metric_payload = {
                "model_id": model_id,
                "avg_inference_time_sec": avg_inference,
                "avg_memory_usage_mb": avg_memory,
                "error_rate": error_rate,
                "throughput_tps": sum(m.token_per_sec or 0 for m in recent) / len(recent),
                "last_updated": now.isoformat()
            }

            await self.monitoring_system.submit_metric(
                source="ai_model",
                metric_name=f"model.{model_id}.performance",
                value=metric_payload
            )

            # Проверка аномалий (например, резкий рост latency)
            if len(recent) >= 5:
                baseline = sum(m.inference_time_sec for m in recent[:-1]) / (len(recent) - 1)
                current = recent[-1].inference_time_sec
                if current > baseline * 2.0:  # +100% — аномалия
                    await self.monitoring_system.trigger_alert(
                        severity="warning",
                        message=f"Аномальный рост latency у модели {model_id}: {current:.2f}s (baseline: {baseline:.2f}s)",
                        context={"model_id": model_id, "metric": "inference_time"}
                    )

    def record_inference(
        self,
        model_id: str,
        inference_time_sec: float,
        memory_usage_mb: float,
        cpu_usage_percent: float,
        success: bool = True,
        accuracy_score: Optional[float] = None,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
    ):
        """
        Записывает результат одного вызова модели.
        Вызывается из inference_engine или model_manager после завершения задачи.
        """
        if not self._running:
            return  # Игнорировать, если мониторинг не запущен

        metrics = ModelMetrics(
            model_id=model_id,
            timestamp=datetime.utcnow(),
            inference_time_sec=inference_time_sec,
            memory_usage_mb=memory_usage_mb,
            cpu_usage_percent=cpu_usage_percent,
            accuracy_score=accuracy_score,
            token_per_sec=(
                (output_tokens or 0) / inference_time_sec
                if inference_time_sec > 0 else 0
            ),
            success_count=int(success),
            error_count=int(not success),
            input_tokens=input_tokens,
            output_tokens=output_tokens
        )

        if model_id not in self._metrics_buffer:
            self._metrics_buffer[model_id] = []
        self._metrics_buffer[model_id].append(metrics)

        # Логирование критических событий
        if not success:
            self.logger.warning("⚠️ Неудачный вызов модели %s", model_id)
        elif inference_time_sec > self.config.get("max_inference_time_sec", 30):
            self.logger.warning("🐢 Медленный вызов модели %s: %.2fs", model_id, inference_time_sec)

    def get_recent_metrics(self, model_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Возвращает последние N записей метрик для модели (для отладки/API)."""
        records = self._metrics_buffer.get(model_id, [])
        return [asdict(r) for r in records[-limit:]]

    def clear_metrics(self, model_id: Optional[str] = None):
        """Очищает метрики (для тестов или перезагрузки модели)."""
        if model_id:
            self._metrics_buffer.pop(model_id, None)
        else:
            self._metrics_buffer.clear()
        self.logger.info("🧹 Очищены метрики для модели %s", model_id or "всех")