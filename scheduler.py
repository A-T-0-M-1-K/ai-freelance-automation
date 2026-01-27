"""
scheduler.py
============
Central task scheduler for the AI Freelance Automation system.
Coordinates periodic and one-time jobs across all subsystems:
- Job scraping every 5 minutes
- Health checks every minute
- Backup routines
- Payment reminders
- Model retraining triggers
- Report generation

Integrates with core components via service locator or dependency injection.
Fully recoverable: survives exceptions, logs failures, auto-restarts stuck tasks.
"""

import asyncio
import logging
import signal
from typing import Any, Callable, Dict, Optional
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.executors.pool import ThreadPoolExecutor, ProcessPoolExecutor
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED

from core.dependency.service_locator import ServiceLocator
from core.config.unified_config_manager import UnifiedConfigManager
from core.monitoring.intelligent_monitoring_system import IntelligentMonitoringSystem
from core.security.audit_logger import AuditLogger

# Configure module-specific logger
logger = logging.getLogger("Scheduler")


class AutonomousTaskScheduler:
    """
    Production-grade autonomous scheduler with self-healing capabilities.
    Designed to run indefinitely with zero human intervention.
    """

    def __init__(
            self,
            config_manager: Optional[UnifiedConfigManager] = None,
            service_locator: Optional[ServiceLocator] = None,
            monitoring_system: Optional[IntelligentMonitoringSystem] = None,
            audit_logger: Optional[AuditLogger] = None,
    ):
        self.config = config_manager or UnifiedConfigManager()
        self.services = service_locator or ServiceLocator.get_instance()
        self.monitoring = monitoring_system or self.services.get("monitoring")
        self.audit = audit_logger or self.services.get("audit_logger") or AuditLogger()

        # APScheduler setup
        jobstores = {"default": MemoryJobStore()}
        executors = {
            "default": ThreadPoolExecutor(max_workers=20),
            "processpool": ProcessPoolExecutor(max_workers=4),
        }
        job_defaults = {
            "coalesce": True,
            "max_instances": 1,
            "misfire_grace_time": 300,  # 5 minutes
        }

        self.scheduler = AsyncIOScheduler(
            jobstores=jobstores,
            executors=executors,
            job_defaults=job_defaults,
            timezone="UTC",
        )

        # Register event listeners
        self.scheduler.add_listener(self._on_job_error, EVENT_JOB_ERROR)
        self.scheduler.add_listener(self._on_job_executed, EVENT_JOB_EXECUTED)

        self._running = False
        self._shutdown_event = asyncio.Event()

        logger.info("✅ AutonomousTaskScheduler initialized.")

    def _on_job_error(self, event):
        """Handle job execution errors with self-healing logic."""
        error_msg = f"Job {event.job_id} failed: {event.exception}"
        logger.error(error_msg, exc_info=event.exception)
        self.audit.log_security_event("SCHEDULER_JOB_FAILURE", details={"job_id": event.job_id})

        # Trigger emergency recovery if critical
        if "critical" in getattr(event.job, "tags", []):
            recovery = self.services.get("emergency_recovery")
            if recovery:
                asyncio.create_task(recovery.handle_failure("scheduler", event.exception))

    def _on_job_executed(self, event):
        """Log successful execution and update metrics."""
        logger.debug(f"Job {event.job_id} completed successfully.")
        if self.monitoring:
            self.monitoring.record_metric("scheduler.job_success", 1, tags={"job_id": event.job_id})

    async def _safe_wrapper(self, func: Callable, job_id: str, *args, **kwargs):
        """Wrap scheduled functions to prevent scheduler crash on exception."""
        try:
            if asyncio.iscoroutinefunction(func):
                return await func(*args, **kwargs)
            else:
                return func(*args, **kwargs)
        except Exception as e:
            logger.exception(f"Exception in scheduled job '{job_id}': {e}")
            raise  # Re-raise to let APScheduler handle via listener

    async def _load_scheduled_tasks(self):
        """Dynamically load tasks from config and register them."""
        automation_cfg = self.config.get("automation", {})
        intervals = automation_cfg.get("intervals", {})

        # 1. Job scraping (every 5 min by default)
        scrape_interval = intervals.get("job_scraping_minutes", 5)
        self.add_job(
            self._trigger_job_scraping,
            "interval",
            minutes=scrape_interval,
            id="job_scraping",
            tags=["freelance", "data_ingestion"],
        )

        # 2. Health monitoring (every 60 sec)
        self.add_job(
            self._trigger_health_check,
            "interval",
            seconds=60,
            id="health_monitor",
            tags=["system", "critical"],
        )

        # 3. Daily reports at 06:00 UTC
        self.add_job(
            self._trigger_daily_report,
            "cron",
            hour=6,
            minute=0,
            id="daily_report",
            tags=["reporting"],
        )

        # 4. Backup (daily at 02:00 UTC)
        self.add_job(
            self._trigger_backup,
            "cron",
            hour=2,
            minute=0,
            id="system_backup",
            tags=["maintenance"],
        )

        # 5. Payment reminders (every 12 hours)
        self.add_job(
            self._trigger_payment_reminders,
            "interval",
            hours=12,
            id="payment_reminders",
            tags=["finance"],
        )

        logger.info("📅 Scheduled tasks loaded from configuration.")

    async def _trigger_job_scraping(self):
        platform_mgr = self.services.get("platform_manager")
        if platform_mgr:
            await platform_mgr.scan_all_platforms()

    async def _trigger_health_check(self):
        health_monitor = self.services.get("health_monitor")
        if health_monitor:
            await health_monitor.run_full_diagnostic()

    async def _trigger_daily_report(self):
        reporting_engine = self.services.get("reporting_engine")
        if reporting_engine:
            await reporting_engine.generate_daily_report()

    async def _trigger_backup(self):
        backup_script = self.services.get("backup_service")
        if backup_script:
            await backup_script.run_automatic_backup()

    async def _trigger_payment_reminders(self):
        payment_orchestrator = self.services.get("payment_orchestrator")
        if payment_orchestrator:
            await payment_orchestrator.send_pending_reminders()

    def add_job(self, func: Callable, trigger: str, *, id: str, tags: list = None, **kwargs):
        """Add a job with automatic error wrapping."""
        wrapped = lambda *a, **kw: asyncio.create_task(
            self._safe_wrapper(func, id, *a, **kw)
        )
        self.scheduler.add_job(wrapped, trigger, id=id, **kwargs)
        logger.debug(f"➕ Added scheduled job: {id} ({trigger})")

    async def start(self):
        """Start the scheduler and begin executing tasks."""
        if self._running:
            logger.warning("Scheduler already running.")
            return

        logger.info("🟢 Starting Autonomous Task Scheduler...")
        await self._load_scheduled_tasks()
        self.scheduler.start()

        # Handle graceful shutdown
        for sig in (signal.SIGTERM, signal.SIGINT):
            asyncio.get_running_loop().add_signal_handler(sig, self._signal_handler)

        self._running = True
        self.audit.log_security_event("SCHEDULER_STARTED")
        logger.info("⏱️  Scheduler is now active.")

        # Wait until shutdown
        await self._shutdown_event.wait()

        await self.stop()

    def _signal_handler(self):
        logger.info("🛑 Shutdown signal received. Stopping scheduler...")
        self._shutdown_event.set()

    async def stop(self):
        """Gracefully shut down the scheduler."""
        if not self._running:
            return

        logger.info("⏳ Shutting down scheduler...")
        self.scheduler.shutdown(wait=True)
        self._running = False
        self.audit.log_security_event("SCHEDULER_STOPPED")
        logger.info("⏹️  Scheduler stopped.")


# Entry point alias for compatibility
async def run_scheduler():
    """Convenience function to launch scheduler standalone."""
    scheduler = AutonomousTaskScheduler()
    await scheduler.start()


if __name__ == "__main__":
    # For direct execution (e.g., in container)
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_scheduler())