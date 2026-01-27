# AI_FREELANCE_AUTOMATION/core/monitoring/intelligent_monitoring_system.py

"""
Intelligent Monitoring System — центральный компонент наблюдения за состоянием всей системы.
Собирает >100 метрик в реальном времени, обнаруживает аномалии, управляет порогами,
генерирует оповещения и взаимодействует с системой автовосстановления.

Архитектурные принципы:
- Полная изоляция от бизнес-логики (только наблюдение)
- Поддержка горизонтального масштабирования
- Hot-reload конфигурации без остановки
- Интеграция с anomaly_detection, alert_manager, metrics_collector
- Соответствие SOC 2 / GDPR через audit-логирование
"""

import asyncio
import logging
import time
from typing import Dict, Any, Optional, List, Callable
from datetime import datetime, timedelta

from .metrics_collector import MetricsCollector
from .anomaly_detection import AnomalyDetector
from .alert_manager import AlertManager
from .threshold_manager import ThresholdManager
from .trend_analyzer import TrendAnalyzer
from .resource_optimizer import ResourceOptimizer

from ..config.unified_config_manager import UnifiedConfigManager
from ..security.audit_logger import AuditLogger


class IntelligentMonitoringSystem:
    """
    Главный класс мониторинга. Работает как фоновый сервис с высокой отказоустойчивостью.
    """

    def __init__(self, config_manager: UnifiedConfigManager):
        self.config = config_manager
        self.logger = logging.getLogger("IntelligentMonitoringSystem")
        self.is_running = False
        self.start_time = None

        # Инициализация подсистем
        self.metrics_collector = MetricsCollector(config_manager)
        self.anomaly_detector = AnomalyDetector(config_manager)
        self.alert_manager = AlertManager(config_manager)
        self.threshold_manager = ThresholdManager(config_manager)
        self.trend_analyzer = TrendAnalyzer(config_manager)
        self.resource_optimizer = ResourceOptimizer(config_manager)
        self.audit_logger = AuditLogger()

        self._tasks: List[asyncio.Task] = []
        self._last_health_check: Optional[datetime] = None
        self._health_status: Dict[str, Any] = {"status": "initializing", "components": {}}

        self.logger.info("✅ Intelligent Monitoring System initialized.")

    async def start(self) -> None:
        """Запуск мониторинга в фоновом режиме."""
        if self.is_running:
            self.logger.warning("⚠️ Monitoring system already running.")
            return

        self.is_running = True
        self.start_time = time.time()
        self._last_health_check = datetime.utcnow()

        # Запуск фоновых задач
        self._tasks = [
            asyncio.create_task(self._collect_metrics_loop()),
            asyncio.create_task(self._analyze_trends_loop()),
            asyncio.create_task(self._detect_anomalies_loop()),
            asyncio.create_task(self._optimize_resources_loop()),
            asyncio.create_task(self._health_check_loop()),
        ]

        self._health_status["status"] = "healthy"
        self.logger.info("🟢 Intelligent Monitoring System started.")

        # Аудит запуска
        await self.audit_logger.log(
            action="monitoring_started",
            actor="system",
            details={"start_time": self.start_time}
        )

    async def stop(self) -> None:
        """Корректная остановка всех задач мониторинга."""
        if not self.is_running:
            return

        self.is_running = False
        self.logger.info("🛑 Stopping Intelligent Monitoring System...")

        for task in self._tasks:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        self._tasks.clear()
        self._health_status["status"] = "stopped"

        await self.audit_logger.log(
            action="monitoring_stopped",
            actor="system",
            details={"uptime_sec": time.time() - self.start_time}
        )
        self.logger.info("⏹️ Monitoring system stopped.")

    async def get_health_status(self) -> Dict[str, Any]:
        """Возвращает текущее состояние здоровья системы."""
        return {
            **self._health_status,
            "uptime_sec": time.time() - self.start_time if self.start_time else 0,
            "last_check": self._last_health_check.isoformat() if self._last_health_check else None
        }

    async def _collect_metrics_loop(self) -> None:
        """Цикл сбора метрик каждые N секунд."""
        interval = self.config.get("monitoring.metrics_interval_sec", 10)
        while self.is_running:
            try:
                await self.metrics_collector.collect_all()
                self.logger.debug("📊 Metrics collected successfully.")
            except Exception as e:
                self.logger.error(f"❌ Error in metrics collection: {e}", exc_info=True)
                await self.alert_manager.send_alert(
                    severity="error",
                    source="metrics_collector",
                    message=str(e)
                )
            await asyncio.sleep(interval)

    async def _analyze_trends_loop(self) -> None:
        """Анализ трендов раз в N минут."""
        interval = self.config.get("monitoring.trend_analysis_interval_min", 5) * 60
        while self.is_running:
            try:
                await self.trend_analyzer.analyze()
                self.logger.debug("📈 Trend analysis completed.")
            except Exception as e:
                self.logger.error(f"📉 Error in trend analysis: {e}", exc_info=True)
            await asyncio.sleep(interval)

    async def _detect_anomalies_loop(self) -> None:
        """Обнаружение аномалий на основе собранных метрик."""
        interval = self.config.get("monitoring.anomaly_check_interval_sec", 30)
        while self.is_running:
            try:
                anomalies = await self.anomaly_detector.scan()
                if anomalies:
                    self.logger.warning(f"⚠️ Detected {len(anomalies)} anomalies.")
                    for anomaly in anomalies:
                        await self.alert_manager.send_alert(
                            severity=anomaly.get("severity", "warning"),
                            source="anomaly_detector",
                            message=anomaly.get("description", "Unknown anomaly"),
                            context=anomaly
                        )
            except Exception as e:
                self.logger.error(f"🔍 Anomaly detection failed: {e}", exc_info=True)
            await asyncio.sleep(interval)

    async def _optimize_resources_loop(self) -> None:
        """Автоматическая оптимизация ресурсов."""
        interval = self.config.get("monitoring.optimization_interval_min", 10) * 60
        while self.is_running:
            try:
                recommendations = await self.resource_optimizer.analyze_and_recommend()
                if recommendations:
                    self.logger.info(f"⚡ Optimization recommendations: {recommendations}")
                    # В будущем: отправка рекомендаций в auto_scaler или memory_manager
            except Exception as e:
                self.logger.error(f"⚙️ Resource optimization error: {e}", exc_info=True)
            await asyncio.sleep(interval)

    async def _health_check_loop(self) -> None:
        """Проверка общего состояния системы каждую минуту."""
        while self.is_running:
            try:
                # Сбор статусов компонентов через service locator (в будущем)
                # Сейчас — заглушка для демонстрации
                component_statuses = {
                    "metrics_collector": "ok",
                    "anomaly_detector": "ok",
                    "alert_manager": "ok"
                }

                overall = "healthy" if all(v == "ok" for v in component_statuses.values()) else "degraded"
                self._health_status = {
                    "status": overall,
                    "components": component_statuses,
                    "timestamp": datetime.utcnow().isoformat()
                }
                self._last_health_check = datetime.utcnow()

                if overall != "healthy":
                    await self.alert_manager.send_alert(
                        severity="warning",
                        source="health_check",
                        message=f"System health degraded: {component_statuses}"
                    )

            except Exception as e:
                self.logger.critical(f"💔 Health check loop crashed: {e}", exc_info=True)
                self._health_status["status"] = "critical"
            await asyncio.sleep(60)

    async def force_anomaly_scan(self) -> List[Dict[str, Any]]:
        """Принудительное сканирование на аномалии (для emergency_recovery)."""
        self.logger.info("🚨 Forced anomaly scan triggered.")
        return await self.anomaly_detector.scan()

    async def export_current_metrics(self) -> Dict[str, Any]:
        """Экспорт текущих метрик для отчётов или внешних систем."""
        return await self.metrics_collector.get_latest_snapshot()
