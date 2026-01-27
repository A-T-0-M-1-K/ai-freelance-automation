#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
System Health Checker
=====================

Autonomous diagnostic script that validates the operational integrity
of all critical components in the AI Freelance Automation system.

- Checks core services (AI, payment, communication, automation)
- Validates configuration integrity
- Tests external dependencies (APIs, databases, storage)
- Reports anomalies and suggests recovery actions
- Safe to run concurrently with main application

Designed for:
- Scheduled execution (e.g., via cron or scheduler.py)
- Manual diagnostics
- Pre-deployment validation
"""

import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Any, Optional

# Add project root to path for absolute imports
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

# Local imports (aligned with project structure)
from core.config.unified_config_manager import UnifiedConfigManager
from core.security.advanced_crypto_system import AdvancedCryptoSystem
from core.monitoring.intelligent_monitoring_system import IntelligentMonitoringSystem
from core.dependency.service_locator import ServiceLocator
from core.payment.enhanced_payment_processor import EnhancedPaymentProcessor
from core.ai_management.intelligent_model_manager import IntelligentModelManager
from core.communication.empathetic_communicator import EmpatheticCommunicator
from core.automation.auto_freelancer_core import AutoFreelancerCore
from services.storage.database_service import DatabaseService
from services.storage.file_storage import FileStorage
from platforms.platform_factory import PlatformFactory

# Configure dedicated logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(PROJECT_ROOT / "logs" / "monitoring" / "health_checks.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("HealthChecker")


class SystemHealthChecker:
    """Comprehensive health validator for the entire autonomous system."""

    def __init__(self):
        self.config = None
        self.crypto = None
        self.results: Dict[str, Any] = {
            "timestamp": None,
            "status": "unknown",
            "checks": {},
            "errors": [],
            "warnings": [],
            "recovery_suggestions": []
        }
        self._initialized = False

    async def initialize(self) -> bool:
        """Initialize required subsystems safely."""
        try:
            # Load config without side effects
            self.config = UnifiedConfigManager()
            self.config.load_all()

            # Initialize crypto (non-intrusive)
            self.crypto = AdvancedCryptoSystem()
            await self.crypto.initialize()

            self._initialized = True
            logger.info("✅ Health checker initialized successfully")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to initialize health checker: {e}", exc_info=True)
            self.results["errors"].append(f"Initialization failed: {str(e)}")
            return False

    async def run_full_diagnostics(self) -> Dict[str, Any]:
        """Execute all health checks and return structured report."""
        if not self._initialized:
            raise RuntimeError("HealthChecker not initialized. Call .initialize() first.")

        start_time = time.time()
        self.results["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        logger.info("🔍 Starting full system health diagnostics...")

        # Run all checks
        await self._check_configuration()
        await self._check_security()
        await self._check_core_services()
        await self._check_external_dependencies()
        await self._check_data_integrity()
        await self._check_platform_connectivity()

        # Finalize status
        total_errors = len(self.results["errors"])
        total_warnings = len(self.results["warnings"])

        if total_errors > 0:
            self.results["status"] = "critical"
        elif total_warnings > 3:
            self.results["status"] = "degraded"
        else:
            self.results["status"] = "healthy"

        duration = time.time() - start_time
        logger.info(f"✅ Diagnostics completed in {duration:.2f}s. Status: {self.results['status']}")
        return self.results

    async def _check_configuration(self):
        """Validate configuration files and runtime settings."""
        check_name = "configuration"
        try:
            # Validate config schema
            is_valid = self.config.validate_all()
            if not is_valid:
                self.results["errors"].append("Configuration validation failed")
                self.results["checks"][check_name] = {"status": "failed", "details": "Schema mismatch"}
                return

            # Check required keys
            required_keys = ["ai", "platforms", "payment", "security"]
            missing = [k for k in required_keys if not self.config.has(k)]
            if missing:
                self.results["errors"].append(f"Missing config sections: {missing}")
                self.results["checks"][check_name] = {"status": "failed", "details": f"Missing: {missing}"}
                return

            self.results["checks"][check_name] = {"status": "ok", "details": "All configs valid"}
            logger.debug("✅ Configuration check passed")
        except Exception as e:
            msg = f"Config check error: {str(e)}"
            self.results["errors"].append(msg)
            self.results["checks"][check_name] = {"status": "error", "details": str(e)}
            logger.error(msg)

    async def _check_security(self):
        """Verify cryptographic systems and key integrity."""
        check_name = "security"
        try:
            # Test encryption round-trip
            test_data = b"health_check_test_payload"
            encrypted = await self.crypto.encrypt(test_data)
            decrypted = await self.crypto.decrypt(encrypted)
            if decrypted != test_data:
                raise ValueError("Encryption round-trip failed")

            # Check key rotation status
            key_age = await self.crypto.get_active_key_age_days()
            if key_age > 90:
                self.results["warnings"].append("Cryptographic keys overdue for rotation (>90 days)")

            self.results["checks"][check_name] = {"status": "ok", "details": f"Keys age: {key_age} days"}
            logger.debug("✅ Security check passed")
        except Exception as e:
            msg = f"Security check failed: {str(e)}"
            self.results["errors"].append(msg)
            self.results["checks"][check_name] = {"status": "error", "details": str(e)}
            logger.error(msg)

    async def _check_core_services(self):
        """Validate core autonomous components."""
        services = {
            "ai_manager": IntelligentModelManager,
            "payment": EnhancedPaymentProcessor,
            "communication": EmpatheticCommunicator,
            "automation": AutoFreelancerCore,
        }

        check_name = "core_services"
        results = {}
        healthy_count = 0

        for name, cls in services.items():
            try:
                # Attempt lightweight instantiation
                instance = cls(config=self.config, crypto=self.crypto)
                if hasattr(instance, "health_check"):
                    status = await instance.health_check()
                else:
                    status = {"status": "ok", "details": "No custom health check"}

                if status["status"] == "ok":
                    healthy_count += 1
                results[name] = status
            except Exception as e:
                results[name] = {"status": "error", "details": str(e)}
                self.results["errors"].append(f"Core service '{name}' failed: {str(e)}")

        overall_status = "ok" if healthy_count == len(services) else "degraded"
        self.results["checks"][check_name] = {"status": overall_status, "details": results}
        logger.debug(f"✅ Core services check: {healthy_count}/{len(services)} healthy")

    async def _check_external_dependencies(self):
        """Test database, file storage, and network connectivity."""
        check_name = "external_deps"
        results = {}

        # Database
        try:
            db = DatabaseService(config=self.config)
            await db.connect()
            await db.ping()
            results["database"] = {"status": "ok"}
            await db.close()
        except Exception as e:
            results["database"] = {"status": "error", "details": str(e)}
            self.results["errors"].append(f"Database unreachable: {str(e)}")

        # File storage
        try:
            fs = FileStorage(config=self.config)
            test_path = Path("temp_health_check.txt")
            fs.write(test_path, b"test")
            data = fs.read(test_path)
            fs.delete(test_path)
            if data != b"test":
                raise IOError("File storage read/write mismatch")
            results["file_storage"] = {"status": "ok"}
        except Exception as e:
            results["file_storage"] = {"status": "error", "details": str(e)}
            self.results["errors"].append(f"File storage error: {str(e)}")

        self.results["checks"][check_name] = {"status": "ok" if all(r["status"] == "ok" for r in results.values()) else "degraded", "details": results}

    async def _check_data_integrity(self):
        """Validate critical data structures and indices."""
        check_name = "data_integrity"
        issues = []

        data_root = PROJECT_ROOT / "data"
        required_dirs = ["jobs", "clients", "finances", "conversations"]
        for d in required_dirs:
            path = data_root / d
            if not path.exists():
                issues.append(f"Missing data directory: {d}")

        # Check index files
        index_files = ["jobs/jobs_index.json", "clients/clients_index.json"]
        for idx in index_files:
            path = data_root / idx
            if path.exists():
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        json.load(f)  # Valid JSON?
                except Exception as e:
                    issues.append(f"Corrupted index: {idx} ({e})")
            else:
                issues.append(f"Missing index: {idx}")

        if issues:
            self.results["errors"].extend(issues)
            self.results["checks"][check_name] = {"status": "failed", "details": issues}
        else:
            self.results["checks"][check_name] = {"status": "ok", "details": "All data structures valid"}

    async def _check_platform_connectivity(self):
        """Test connectivity to freelance platforms."""
        check_name = "platforms"
        results = {}

        try:
            platform_factory = PlatformFactory(config=self.config)
            active_platforms = self.config.get("platforms.active", [])
            for platform_name in active_platforms:
                try:
                    client = await platform_factory.get_client(platform_name)
                    if hasattr(client, "ping"):
                        await client.ping()
                    else:
                        # Fallback: check auth
                        await client.authenticate()
                    results[platform_name] = {"status": "ok"}
                except Exception as e:
                    results[platform_name] = {"status": "error", "details": str(e)}
                    self.results["warnings"].append(f"Platform '{platform_name}' connectivity issue: {str(e)}")
        except Exception as e:
            results["factory"] = {"status": "error", "details": str(e)}
            self.results["errors"].append(f"Platform factory error: {str(e)}")

        overall = "ok" if all(r["status"] == "ok" for r in results.values()) else "degraded"
        self.results["checks"][check_name] = {"status": overall, "details": results}

    def save_report(self, output_path: Optional[Path] = None) -> Path:
        """Save health report to disk."""
        if output_path is None:
            timestamp = self.results["timestamp"].replace(":", "-")
            output_path = PROJECT_ROOT / "logs" / "monitoring" / f"health_report_{timestamp}.json"

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(self.results, f, indent=2, ensure_ascii=False)

        logger.info(f"📄 Health report saved to: {output_path}")
        return output_path


async def main():
    """Entry point for script execution."""
    checker = SystemHealthChecker()
    if not await checker.initialize():
        logger.critical("💥 Initialization failed. Exiting.")
        sys.exit(1)

    report = await checker.run_full_diagnostics()
    report_path = checker.save_report()

    # Exit with code based on severity
    if report["status"] == "critical":
        logger.critical("🔴 System health: CRITICAL — Immediate attention required!")
        sys.exit(2)
    elif report["status"] == "degraded":
        logger.warning("🟡 System health: DEGRADED — Review warnings.")
        sys.exit(1)
    else:
        logger.info("🟢 System health: HEALTHY")
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())