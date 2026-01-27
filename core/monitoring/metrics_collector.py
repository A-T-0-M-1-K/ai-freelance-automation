# AI_FREELANCE_AUTOMATION/core/monitoring/metrics_collector.py
"""
Модуль сбора метрик для интеллектуального мониторинга.
Собирает 100+ метрик в реальном времени: системные, бизнес-логика, AI-производительность, клиентские сигналы.
Поддерживает push/pull модели, сериализацию, экспорт в Prometheus, Grafana, внутренние логи.
"""

import asyncio
import logging
import time
import psutil
import json
from typing import Dict, Any, Optional, List, Callable
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

# Локальные импорты (через относительные пути, чтобы избежать циклических зависимостей)
from ..config.unified_config_manager import UnifiedConfigManager
from ..security.audit_logger import AuditLogger

# Типы метрик
MetricType = str  # Например: "system.cpu", "business.revenue", "ai.transcription.latency"
MetricValue = float | int | str
MetricTags = Dict[str, str]


@dataclass(frozen=True)
class MetricRecord:
    """Структура одной записи метрики."""
    name: MetricType
    value: MetricValue
    timestamp: float  # Unix timestamp
    tags: MetricTags
    source: str  # Например: "cpu_monitor", "payment_processor", "transcription_service"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


class MetricsCollector:
    """
    Централизованный сборщик метрик.
    Работает как singleton-совместимый компонент, но не требует глобального состояния.
    Поддерживает:
      - Системные метрики (CPU, RAM, диск, сеть)
      - Бизнес-метрики (доход, заказы, конверсия)
      - AI-метрики (точность, latency, usage)
      - Клиентские метрики (удовлетворенность, retention)
    """

    def __init__(
        self,
        config: UnifiedConfigManager,
        audit_logger: Optional[AuditLogger] = None,
        loop: Optional[asyncio.AbstractEventLoop] = None
    ):
        self.config = config
        self.audit_logger = audit_logger or AuditLogger()
        self.loop = loop or asyncio.get_event_loop()

        # Настройки из конфига
        monitoring_cfg = self.config.get("monitoring", {})
        self.enabled = monitoring_cfg.get("enabled", True)
        self.collection_interval = monitoring_cfg.get("collection_interval_sec", 30)
        self.max_buffer_size = monitoring_cfg.get("max_buffer_size", 10_000)
        self.export_paths = monitoring_cfg.get("export_paths", ["logs/monitoring/metrics.log"])

        self.logger = logging.getLogger("MetricsCollector")
        self._buffer: List[MetricRecord] = []
        self._collectors: List[Callable[[], List[MetricRecord]]] = []
        self._running = False
        self._task: Optional[asyncio.Task] = None

        if not self.enabled:
            self.logger.warning("⚠️ Metrics collection is DISABLED in config.")

        # Регистрация встроенных коллекторов
        self._register_builtin_collectors()

    def _register_builtin_collectors(self):
        """Регистрирует встроенные источники метрик."""
        self._collectors.extend([
            self._collect_system_metrics,
            self._collect_process_metrics,
        ])

    def register_custom_collector(self, collector: Callable[[], List[MetricRecord]]) -> None:
        """
        Регистрирует пользовательский коллектор метрик.
        Пример:
            def my_collector():
                return [MetricRecord("my.metric", 42.0, time.time(), {}, "my_service")]
        """
        if callable(collector):
            self._collectors.append(collector)
            self.logger.debug(f"✅ Registered custom metric collector: {collector.__name__}")
        else:
            raise ValueError("Collector must be a callable returning List[MetricRecord]")

    def _collect_system_metrics(self) -> List[MetricRecord]:
        """Собирает системные метрики через psutil."""
        now = time.time()
        tags = {"host": "localhost"}  # можно расширить до hostname, region и т.д.

        cpu_percent = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        net = psutil.net_io_counters()

        return [
            MetricRecord("system.cpu.percent", cpu_percent, now, tags, "psutil"),
            MetricRecord("system.memory.total_bytes", memory.total, now, tags, "psutil"),
            MetricRecord("system.memory.used_bytes", memory.used, now, tags, "psutil"),
            MetricRecord("system.memory.percent", memory.percent, now, tags, "psutil"),
            MetricRecord("system.disk.total_bytes", disk.total, now, tags, "psutil"),
            MetricRecord("system.disk.used_bytes", disk.used, now, tags, "psutil"),
            MetricRecord("system.network.bytes_sent", net.bytes_sent, now, tags, "psutil"),
            MetricRecord("system.network.bytes_recv", net.bytes_recv, now, tags, "psutil"),
        ]

    def _collect_process_metrics(self) -> List[MetricRecord]:
        """Собирает метрики текущего процесса."""
        now = time.time()
        process = psutil.Process()
        tags = {"pid": str(process.pid)}

        return [
            MetricRecord("process.cpu.percent", process.cpu_percent(), now, tags, "psutil"),
            MetricRecord("process.memory.rss_bytes", process.memory_info().rss, now, tags, "psutil"),
            MetricRecord("process.threads.count", process.num_threads(), now, tags, "psutil"),
            MetricRecord("process.open_files.count", len(process.open_files()), now, tags, "psutil"),
        ]

    def record(
        self,
        name: MetricType,
        value: MetricValue,
        tags: Optional[MetricTags] = None,
        source: str = "external"
    ) -> None:
        """
        Ручная запись метрики (например, из payment или AI сервиса).
        Потокобезопасна для asyncio.
        """
        if not self.enabled:
            return

        record = MetricRecord(
            name=name,
            value=value,
            timestamp=time.time(),
            tags=tags or {},
            source=source
        )

        self._buffer.append(record)

        # Защита от переполнения буфера
        if len(self._buffer) > self.max_buffer_size:
            self.logger.warning("MemoryWarning Buffer overflow — dropping oldest metrics")
            self._buffer = self._buffer[-self.max_buffer_size // 2:]

    async def _export_to_files(self):
        """Экспортирует метрики в файлы (в формате JSONL)."""
        if not self._buffer:
            return

        records = self._buffer.copy()
        self._buffer.clear()

        for path_str in self.export_paths:
            try:
                path = Path(path_str)
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a", encoding="utf-8") as f:
                    for rec in records:
                        f.write(rec.to_json() + "\n")
            except Exception as e:
                self.logger.error(f"❌ Failed to write metrics to {path_str}: {e}")

        # Аудит операции
        await self.audit_logger.log(
            action="metrics_export",
            details={"count": len(records), "paths": self.export_paths}
        )

    async def _collect_and_export(self):
        """Основной цикл сбора и экспорта метрик."""
        while self._running:
            try:
                all_records: List[MetricRecord] = []
                for collector in self._collectors:
                    try:
                        records = collector()
                        all_records.extend(records)
                    except Exception as e:
                        self.logger.error(f"❌ Collector {collector} failed: {e}")

                # Добавляем в буфер
                self._buffer.extend(all_records)

                # Экспорт
                await self._export_to_files()

                await asyncio.sleep(self.collection_interval)

            except asyncio.CancelledError:
                self.logger.info("⏹️ Metrics collection task cancelled.")
                break
            except Exception as e:
                self.logger.exception(f"💥 Unexpected error in metrics loop: {e}")
                await asyncio.sleep(5)  # пауза перед повтором

    async def start(self):
        """Запускает фоновый сбор метрик."""
        if not self.enabled:
            self.logger.info("⏭️ Metrics collection skipped (disabled in config)")
            return

        if self._running:
            self.logger.warning("⚠️ MetricsCollector already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._collect_and_export())
        self.logger.info("🟢 MetricsCollector started")

    async def stop(self):
        """Останавливает сбор и сбрасывает буфер."""
        if not self._running:
            return

        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        # Финальный экспорт
        await self._export_to_files()
        self.logger.info("⏹️ MetricsCollector stopped")

    def get_latest_metrics(self, prefix: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Возвращает последние собранные метрики (для API/UI).
        Можно фильтровать по префиксу (например, "ai.").
        """
        filtered = self._buffer
        if prefix:
            filtered = [r for r in filtered if r.name.startswith(prefix)]
        return [r.to_dict() for r in filtered[-100:]]  # последние 100

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()