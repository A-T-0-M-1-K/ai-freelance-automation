# AI_FREELANCE_AUTOMATION/scripts/maintenance/health_check.py
"""
Health Check Script — Performs comprehensive system diagnostics.
Validates core components, services, storage, AI models, and external integrations.
Used by cron, CI/CD, or manual invocation to ensure 99.9% uptime.
"""

import os
import sys
import asyncio
import logging
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List

# Add project root to path for absolute imports
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.config.unified_config_manager import UnifiedConfigManager
from core.security.audit_logger import AuditLogger
from core.monitoring.intelligent_monitoring_system import IntelligentMonitoringSystem
from core.dependency.service_locator import ServiceLocator
from core.ai_management.intelligent_model_manager import IntelligentModelManager
from services.storage.database_service import DatabaseService
from services.storage.file_storage import FileStorage
from platforms.platform_factory import PlatformFactory


class HealthCheckResult:
    def __init__(self):
        self.timestamp: str = datetime.utcnow().isoformat() + "Z"
        self.status: str = "unknown"  # "healthy", "degraded", "critical"
        self.components: Dict[str, Dict[str, Any]] = {}
        self.recommendations: List[str] = []

    def add_component(self, name: str, status: str, details: Dict[str, Any]):
        self.components[name] = {
            "status": status,
            "details": details,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }

    def set_global_status(self):
        statuses = [comp["status"] for comp in self.components.values()]
        if "critical" in statuses:
            self.status = "critical"
        elif "degraded" in statuses:
            self.status = "degraded"
        else:
            self.status = "healthy"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "status": self.status,
            "components": self.components,
            "recommendations": self.recommendations
        }

    def save_to_file(self, output_path: Path):
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)


class SystemHealthChecker:
    def __init__(self, config: UnifiedConfigManager):
        self.config = config
        self.logger = logging.getLogger("HealthCheck")
        self.result = HealthCheckResult()
        self.audit_logger = AuditLogger()

    async def check_core_components(self):
        """Check critical internal subsystems."""
        try:
            # Dependency injection container
            locator = ServiceLocator()
            locator_status = "healthy" if locator.is_ready() else "degraded"
            self.result.add_component("service_locator", locator_status, {"ready": locator.is_ready()})

            # Config manager
            config_valid = self.config.validate_all()
            config_status = "healthy" if config_valid else "critical"
            self.result.add_component("config_manager", config_status, {"valid": config_valid})

            # Monitoring system
            monitor = IntelligentMonitoringSystem(self.config)
            metrics = await monitor.collect_metrics()
            monitor_status = "healthy" if len(metrics) > 10 else "degraded"
            self.result.add_component("monitoring", monitor_status, {"metric_count": len(metrics)})

        except Exception as e:
            self.logger.error(f"Core component check failed: {e}")
            self.result.add_component("core_components", "critical", {"error": str(e)})

    async def check_ai_models(self):
        """Validate AI model availability and performance."""
        try:
            ai_manager = IntelligentModelManager(self.config)
            model_status = await ai_manager.get_health_status()
            overall = "healthy"
            if any(m["status"] != "loaded" for m in model_status.values()):
                overall = "degraded"
            self.result.add_component("ai_models", overall, model_status)
        except Exception as e:
            self.logger.error(f"AI model check failed: {e}")
            self.result.add_component("ai_models", "critical", {"error": str(e)})

    async def check_storage(self):
        """Check database and file storage."""
        try:
            # Database
            db = DatabaseService()
            db_ok = await db.ping()
            db_status = "healthy" if db_ok else "critical"
            self.result.add_component("database", db_status, {"reachable": db_ok})

            # File storage
            fs = FileStorage(self.config.get("storage.file.root_path", "data/"))
            fs_ok = fs.is_writable()
            fs_status = "healthy" if fs_ok else "critical"
            self.result.add_component("file_storage", fs_status, {"writable": fs_ok})
        except Exception as e:
            self.logger.error(f"Storage check failed: {e}")
            self.result.add_component("storage", "critical", {"error": str(e)})

    async def check_platforms(self):
        """Check connectivity to freelance platforms."""
        try:
            platform_names = self.config.get("platforms.enabled", [])
            statuses = {}
            for name in platform_names:
                try:
                    client = PlatformFactory.create(name)
                    alive = await client.health_check()
                    statuses[name] = {"status": "online" if alive else "offline", "latency_ms": client.last_latency}
                except Exception as ex:
                    statuses[name] = {"status": "error", "error": str(ex)}
            overall = "healthy" if all(v["status"] == "online" for v in statuses.values()) else "degraded"
            self.result.add_component("platforms", overall, statuses)
        except Exception as e:
            self.logger.error(f"Platform check failed: {e}")
            self.result.add_component("platforms", "critical", {"error": str(e)})

    async def run_full_check(self) -> HealthCheckResult:
        """Execute all health checks."""
        self.logger.info("🔍 Starting full system health check...")
        await self.check_core_components()
        await self.check_ai_models()
        await self.check_storage()
        await self.check_platforms()

        self.result.set_global_status()
        self.logger.info(f"✅ Health check completed. Status: {self.result.status}")

        # Log to audit trail
        self.audit_logger.log(
            action="health_check",
            actor="system",
            details=self.result.to_dict(),
            severity="info" if self.result.status == "healthy" else "warning"
        )

        return self.result


async def main():
    # Setup minimal logging for script
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(PROJECT_ROOT / "logs" / "maintenance" / "health_check.log"),
            logging.StreamHandler(sys.stdout)
        ]
    )

    try:
        config = UnifiedConfigManager()
        checker = SystemHealthChecker(config)
        result = await checker.run_full_check()

        # Save report
        report_dir = PROJECT_ROOT / "data" / "exports" / "reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / f"health_check_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
        result.save_to_file(report_path)

        print(f"🟢 System status: {result.status}")
        print(f"📄 Report saved to: {report_path}")

        # Exit code for automation
        sys.exit(0 if result.status == "healthy" else 1)

    except Exception as e:
        logging.critical(f"💥 Health check script failed: {e}", exc_info=True)
        sys.exit(2)


if __name__ == "__main__":
    asyncio.run(main())