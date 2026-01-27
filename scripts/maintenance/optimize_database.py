# AI_FREELANCE_AUTOMATION/scripts/maintenance/optimize_database.py
"""
Database optimization script for AI Freelance Automation System.
Performs vacuuming, index rebuilding, statistics updates, and cleanup of obsolete data.
Supports PostgreSQL, MongoDB, and SQLite.
Integrated with system monitoring, logging, and emergency recovery.
"""

import asyncio
import logging
import sys
from pathlib import Path
from typing import Dict, Any, Optional

# Add project root to path for imports
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.config.unified_config_manager import UnifiedConfigManager
from core.security.audit_logger import AuditLogger
from core.monitoring.intelligent_monitoring_system import IntelligentMonitoringSystem
from core.emergency_recovery import EmergencyRecovery
from services.storage.database_service import DatabaseService


class DatabaseOptimizer:
    """
    Orchestrates database maintenance and optimization tasks.
    Ensures performance, integrity, and minimal downtime.
    """

    def __init__(self):
        self.logger = logging.getLogger("DatabaseOptimizer")
        self.config_manager = UnifiedConfigManager()
        self.db_config = self.config_manager.get_section("database")
        self.monitoring = IntelligentMonitoringSystem(self.config_manager)
        self.audit_logger = AuditLogger()
        self.recovery = EmergencyRecovery({})
        self.db_service: Optional[DatabaseService] = None

    async def initialize(self) -> bool:
        """Initialize database connection and validate configuration."""
        try:
            self.logger.info("🔧 Initializing database optimizer...")
            self.db_service = DatabaseService(self.config_manager)
            await self.db_service.connect()
            self.logger.info("✅ Database connection established.")
            return True
        except Exception as e:
            self.logger.error(f"❌ Failed to initialize database optimizer: {e}", exc_info=True)
            await self.audit_logger.log_security_event(
                "DB_OPTIMIZATION_INIT_FAILURE",
                {"error": str(e)},
                severity="critical"
            )
            return False

    async def _optimize_postgresql(self) -> Dict[str, Any]:
        """Optimize PostgreSQL database."""
        results = {"vacuumed": False, "analyzed": False, "reindexed": False}
        conn = await self.db_service.get_raw_connection()

        try:
            # Vacuum + Analyze
            await conn.execute("VACUUM ANALYZE;")
            results["vacuumed"] = True
            results["analyzed"] = True
            self.logger.info("🧹 PostgreSQL: VACUUM ANALYZE completed.")

            # Reindex critical tables
            critical_tables = ["jobs", "clients", "conversations", "transactions"]
            for table in critical_tables:
                await conn.execute(f"REINDEX TABLE {table};")
            results["reindexed"] = True
            self.logger.info("🔄 PostgreSQL: Critical indexes rebuilt.")

        except Exception as e:
            self.logger.warning(f"⚠️ Partial failure during PostgreSQL optimization: {e}")
            await self.audit_logger.log_security_event(
                "DB_OPTIMIZATION_PARTIAL_FAILURE",
                {"engine": "postgresql", "error": str(e)},
                severity="warning"
            )

        return results

    async def _optimize_mongodb(self) -> Dict[str, Any]:
        """Optimize MongoDB collections."""
        results = {"compact": 0, "stats_updated": 0}
        db = self.db_service.get_raw_client()

        try:
            collections = ["jobs", "clients", "conversations", "transactions"]
            for col_name in collections:
                collection = db[col_name]
                # Compact collection (requires admin privileges in some setups)
                try:
                    await collection.command({"compact": col_name})
                    results["compact"] += 1
                except Exception:
                    # Fallback: just update stats
                    pass
                # Update statistics (for query planner)
                await collection.command({"collStats": col_name})
                results["stats_updated"] += 1

            self.logger.info(f"📊 MongoDB: Optimized {len(collections)} collections.")
        except Exception as e:
            self.logger.error(f"❌ MongoDB optimization failed: {e}", exc_info=True)

        return results

    async def _optimize_sqlite(self) -> Dict[str, Any]:
        """Optimize SQLite database."""
        results = {"vacuumed": False}
        conn = await self.db_service.get_raw_connection()

        try:
            await conn.execute("VACUUM;")
            await conn.execute("ANALYZE;")
            results["vacuumed"] = True
            self.logger.info("🧹 SQLite: VACUUM and ANALYZE completed.")
        except Exception as e:
            self.logger.error(f"❌ SQLite optimization failed: {e}", exc_info=True)

        return results

    async def run_optimization(self) -> Dict[str, Any]:
        """Run full database optimization based on configured engine."""
        engine = self.db_config.get("engine", "sqlite").lower()
        self.logger.info(f"🚀 Starting database optimization for engine: {engine}")

        start_time = asyncio.get_event_loop().time()
        result = {}

        try:
            if engine == "postgresql":
                result = await self._optimize_postgresql()
            elif engine == "mongodb":
                result = await self._optimize_mongodb()
            elif engine == "sqlite":
                result = await self._optimize_sqlite()
            else:
                raise ValueError(f"Unsupported database engine: {engine}")

            duration = asyncio.get_event_loop().time() - start_time
            self.logger.info(f"✅ Optimization completed in {duration:.2f} seconds.")

            # Log to monitoring system
            await self.monitoring.record_metric("db.optimization.duration_sec", duration)
            await self.monitoring.record_metric("db.optimization.success", 1)

            # Audit log
            await self.audit_logger.log_security_event(
                "DB_OPTIMIZATION_SUCCESS",
                {"engine": engine, "duration_sec": duration, "details": result},
                severity="info"
            )

        except Exception as e:
            self.logger.critical(f"💥 Critical failure during optimization: {e}", exc_info=True)
            await self.audit_logger.log_security_event(
                "DB_OPTIMIZATION_CRASH",
                {"engine": engine, "error": str(e)},
                severity="critical"
            )
            await self.monitoring.record_metric("db.optimization.success", 0)
            # Trigger emergency recovery if needed
            await self.recovery.handle_component_failure("database_optimizer", str(e))

        return result

    async def cleanup_old_data(self) -> int:
        """Remove obsolete records (e.g., logs older than 90 days, temp files)."""
        cutoff_days = self.config_manager.get("performance.data_retention_days", 90)
        deleted_count = await self.db_service.cleanup_old_data(cutoff_days)
        self.logger.info(f"🗑️ Cleaned up {deleted_count} obsolete records (retention: {cutoff_days} days).")
        return deleted_count

    async def close(self):
        """Gracefully close connections."""
        if self.db_service:
            await self.db_service.close()
        self.logger.info("🔌 Database optimizer shut down gracefully.")


async def main():
    """Entry point for standalone execution."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(PROJECT_ROOT / "logs" / "maintenance" / "db_optimization.log"),
            logging.StreamHandler(sys.stdout)
        ]
    )

    optimizer = DatabaseOptimizer()
    if not await optimizer.initialize():
        sys.exit(1)

    try:
        await optimizer.cleanup_old_data()
        await optimizer.run_optimization()
    finally:
        await optimizer.close()


if __name__ == "__main__":
    asyncio.run(main())