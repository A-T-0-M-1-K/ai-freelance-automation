# AI_FREELANCE_AUTOMATION/scripts/deployment/scale_resources.py
"""
Автоматическое масштабирование вычислительных ресурсов на основе метрик нагрузки.
Интегрируется с monitoring, config и performance подсистемами.
Поддерживает вертикальное и горизонтальное масштабирование.
"""

import asyncio
import logging
import json
from typing import Dict, Any, Optional
from pathlib import Path

# Импорты из ядра (через service locator или напрямую — в скриптах допустимо)
from core.config.unified_config_manager import UnifiedConfigManager
from core.monitoring.intelligent_monitoring_system import IntelligentMonitoringSystem
from core.performance.intelligent_cache_system import IntelligentCacheSystem
from core.security.audit_logger import AuditLogger

# Локальные импорты
from scripts.deployment.deployment_utils import DeploymentUtils


class ResourceScaler:
    """
    Класс для автоматического масштабирования ресурсов системы.
    Работает как standalone-скрипт или как часть планировщика задач.
    """

    def __init__(self, config_path: Optional[str] = None):
        self.logger = logging.getLogger("ResourceScaler")
        self.config_manager = UnifiedConfigManager(config_path)
        self.monitoring = IntelligentMonitoringSystem(self.config_manager)
        self.cache_system = IntelligentCacheSystem(self.config_manager)
        self.audit_logger = AuditLogger()
        self.utils = DeploymentUtils()

        # Загрузка конфигурации масштабирования
        self.scaling_config = self.config_manager.get_section("scaling") or {}
        self.enabled = self.scaling_config.get("enabled", True)
        self.mode = self.scaling_config.get("mode", "auto")  # auto, manual, disabled
        self.thresholds = self.scaling_config.get("thresholds", {
            "cpu_high": 80,
            "memory_high": 85,
            "disk_io_high": 75,
            "active_jobs_high": 40,
            "concurrent_clients_high": 90
        })

        self.logger.info("Intialized ResourceScaler with mode: %s", self.mode)

    async def _get_current_load_metrics(self) -> Dict[str, float]:
        """Получает актуальные метрики нагрузки из системы мониторинга."""
        metrics = await self.monitoring.collect_metrics([
            "system.cpu_usage",
            "system.memory_usage",
            "system.disk_io",
            "business.active_jobs",
            "business.concurrent_clients"
        ])
        return {
            "cpu": metrics.get("system.cpu_usage", 0.0),
            "memory": metrics.get("system.memory_usage", 0.0),
            "disk_io": metrics.get("system.disk_io", 0.0),
            "active_jobs": metrics.get("business.active_jobs", 0.0),
            "concurrent_clients": metrics.get("business.concurrent_clients", 0.0)
        }

    async def _should_scale_up(self, metrics: Dict[str, float]) -> bool:
        """Определяет, нужно ли увеличить ресурсы."""
        if metrics["cpu"] > self.thresholds["cpu_high"]:
            self.logger.warning("CPU usage %.2f%% exceeds threshold", metrics["cpu"])
            return True
        if metrics["memory"] > self.thresholds["memory_high"]:
            self.logger.warning("Memory usage %.2f%% exceeds threshold", metrics["memory"])
            return True
        if metrics["active_jobs"] > self.thresholds["active_jobs_high"]:
            self.logger.info("Active jobs (%d) exceed threshold", int(metrics["active_jobs"]))
            return True
        return False

    async def _should_scale_down(self, metrics: Dict[str, float]) -> bool:
        """Определяет, можно ли уменьшить ресурсы (для экономии)."""
        low_threshold = {k: v * 0.4 for k, v in self.thresholds.items()}
        return all(
            metrics.get(key, 0) < low_threshold.get(f"{key}_high", 30)
            for key in ["cpu", "memory", "active_jobs"]
        )

    async def _scale_vertical(self, direction: str) -> bool:
        """Вертикальное масштабирование (увеличение CPU/RAM на текущем хосте)."""
        try:
            self.logger.info("🔄 Performing vertical scaling: %s", direction)
            success = await self.utils.adjust_local_resources(direction)
            if success:
                self.audit_logger.log("scaling.vertical", {
                    "action": "vertical_scale",
                    "direction": direction,
                    "status": "success"
                })
                self.logger.info("✅ Vertical scaling %s completed", direction)
            else:
                self.logger.error("❌ Vertical scaling %s failed", direction)
            return success
        except Exception as e:
            self.logger.exception("💥 Error during vertical scaling: %s", e)
            self.audit_logger.log("scaling.vertical.error", {"error": str(e)})
            return False

    async def _scale_horizontal(self, direction: str) -> bool:
        """Горизонтальное масштабирование (запуск/остановка дополнительных нод)."""
        try:
            self.logger.info("🔄 Performing horizontal scaling: %s", direction)
            success = await self.utils.manage_worker_nodes(direction)
            if success:
                self.audit_logger.log("scaling.horizontal", {
                    "action": "horizontal_scale",
                    "direction": direction,
                    "status": "success"
                })
                self.logger.info("✅ Horizontal scaling %s completed", direction)
            else:
                self.logger.error("❌ Horizontal scaling %s failed", direction)
            return success
        except Exception as e:
            self.logger.exception("💥 Error during horizontal scaling: %s", e)
            self.audit_logger.log("scaling.horizontal.error", {"error": str(e)})
            return False

    async def _optimize_cache_before_scaling(self):
        """Оптимизирует кэш перед масштабированием для снижения нагрузки."""
        self.logger.info("🧹 Optimizing cache before scaling...")
        await self.cache_system.evict_low_priority()
        await self.cache_system.preload_predicted()

    async def scale_resources(self) -> Dict[str, Any]:
        """
        Основной метод масштабирования.
        Возвращает отчет о выполнении.
        """
        if not self.enabled or self.mode == "disabled":
            self.logger.info("⚠️ Resource scaling is disabled")
            return {"status": "disabled"}

        self.logger.info("🔍 Analyzing system load for scaling decision...")
        metrics = await self._get_current_load_metrics()
        self.logger.debug("Current metrics: %s", json.dumps(metrics, indent=2))

        report = {
            "metrics": metrics,
            "actions": [],
            "status": "no_action"
        }

        if await self._should_scale_up(metrics):
            await self._optimize_cache_before_scaling()
            # Сначала пробуем горизонтальное масштабирование (более надежно)
            if await self._scale_horizontal("up"):
                report["actions"].append("horizontal_up")
                report["status"] = "scaled_up"
            elif await self._scale_vertical("up"):
                report["actions"].append("vertical_up")
                report["status"] = "scaled_up"
            else:
                report["status"] = "scaling_failed"
                self.logger.critical("🔥 All scaling attempts failed!")

        elif await self._should_scale_down(metrics) and self.mode == "auto":
            if await self._scale_horizontal("down"):
                report["actions"].append("horizontal_down")
                report["status"] = "scaled_down"
            # Вертикальное уменьшение рискованно — пропускаем

        self.logger.info("📊 Scaling cycle completed. Status: %s", report["status"])
        return report

    async def run_once(self) -> Dict[str, Any]:
        """Запуск однократного цикла масштабирования."""
        return await self.scale_resources()


# === Точка входа для CLI ===
if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Scale system resources based on load")
    parser.add_argument("--config", type=str, help="Path to config file", default=None)
    parser.add_argument("--log-level", type=str, default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler("logs/deployment/scale_resources.log"),
            logging.StreamHandler(sys.stdout)
        ]
    )

    scaler = ResourceScaler(config_path=args.config)
    result = asyncio.run(scaler.run_once())

    print(json.dumps(result, indent=2, ensure_ascii=False))
    sys.exit(0 if result["status"] in ("scaled_up", "scaled_down", "no_action", "disabled") else 1)