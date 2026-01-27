#!/usr/bin/env python3
"""
AI Freelance Automation — Background Task Worker
Handles long-running asynchronous tasks:
- Job processing (transcription, translation, copywriting)
- Client communication
- Payment processing
- Model inference
- Quality control & delivery

Designed for high reliability, self-healing, and horizontal scaling.
"""

import asyncio
import logging
import signal
import sys
import traceback
from typing import Optional, Dict, Any, Callable
from pathlib import Path

# Add project root to path for imports
PROJECT_ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

from core.dependency.service_locator import ServiceLocator
from core.config.unified_config_manager import UnifiedConfigManager
from core.security.audit_logger import AuditLogger
from core.monitoring.intelligent_monitoring_system import IntelligentMonitoringSystem
from core.emergency_recovery import EmergencyRecovery


class FreelanceWorker:
    """
    Autonomous background worker that processes queued tasks from the automation system.
    Runs indefinitely until shutdown signal is received.
    """

    def __init__(self):
        self.logger = logging.getLogger("FreelanceWorker")
        self.running = False
        self.shutdown_event = asyncio.Event()
        self.task_queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
        self.active_tasks: Dict[str, asyncio.Task] = {}

        # Core services (lazy-loaded via ServiceLocator)
        self.config: Optional[UnifiedConfigManager] = None
        self.audit_logger: Optional[AuditLogger] = None
        self.monitor: Optional[IntelligentMonitoringSystem] = None
        self.recovery: Optional[EmergencyRecovery] = None

        self._setup_logging()
        self._register_signal_handlers()

    def _setup_logging(self):
        """Initialize structured logging."""
        log_level = logging.INFO
        if PROJECT_ROOT.joinpath(".env").exists():
            from dotenv import load_dotenv
            load_dotenv()
            import os
            if os.getenv("DEBUG", "false").lower() == "true":
                log_level = logging.DEBUG

        logging.basicConfig(
            level=log_level,
            format="%(asctime)s [%(levelname)s] %(name)s:%(funcName)s:%(lineno)d — %(message)s",
            handlers=[
                logging.FileHandler(PROJECT_ROOT / "logs" / "app" / "worker.log"),
                logging.StreamHandler(sys.stdout)
            ]
        )

    def _register_signal_handlers(self):
        """Register graceful shutdown handlers."""
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(self._shutdown(s)))

    async def _initialize_services(self):
        """Initialize required core services via ServiceLocator."""
        try:
            self.config = ServiceLocator.get_service("config")
            self.audit_logger = ServiceLocator.get_service("audit_logger")
            self.monitor = ServiceLocator.get_service("monitoring")
            self.recovery = ServiceLocator.get_service("emergency_recovery")

            self.logger.info("✅ Core services initialized successfully.")
        except Exception as e:
            self.logger.critical(f"💥 Failed to initialize core services: {e}", exc_info=True)
            raise

    async def _shutdown(self, signal_received: signal.Signals):
        """Graceful shutdown procedure."""
        self.logger.info(f"Received exit signal {signal_received.name}...")
        self.running = False
        self.shutdown_event.set()

        # Cancel all active tasks
        for task_id, task in self.active_tasks.items():
            if not task.done():
                self.logger.info(f"Canceling task {task_id}...")
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        self.logger.info("Worker shutdown complete.")

    async def enqueue_task(self, task_spec: Dict[str, Any]):
        """
        Enqueue a new task for processing.
        Expected format:
        {
            "task_id": "uuid4",
            "type": "transcription|translation|copywriting|communication|payment|quality_check",
            "payload": { ... },
            "priority": 0-10 (higher = more urgent),
            "retry_count": 0,
            "max_retries": 3
        }
        """
        await self.task_queue.put(task_spec)
        self.logger.debug(f"Task enqueued: {task_spec['task_id']} ({task_spec['type']})")

    async def _process_task(self, task_spec: Dict[str, Any]) -> bool:
        """Process a single task based on its type."""
        task_id = task_spec["task_id"]
        task_type = task_spec["type"]
        payload = task_spec["payload"]

        self.logger.info(f"🚀 Starting task {task_id} of type '{task_type}'")

        try:
            # Route to appropriate handler
            handler: Optional[Callable] = None
            if task_type == "transcription":
                from services.ai_services.transcription_service import TranscriptionService
                handler = TranscriptionService.process
            elif task_type == "translation":
                from services.ai_services.translation_service import TranslationService
                handler = TranslationService.process
            elif task_type == "copywriting":
                from services.ai_services.copywriting_service import CopywritingService
                handler = CopywritingService.process
            elif task_type == "communication":
                from core.communication.empathetic_communicator import EmpatheticCommunicator
                handler = EmpatheticCommunicator.send_message
            elif task_type == "payment":
                from core.payment.enhanced_payment_processor import EnhancedPaymentProcessor
                handler = EnhancedPaymentProcessor.process_payment
            elif task_type == "quality_check":
                from core.automation.quality_controller import QualityController
                handler = QualityController.run_quality_check
            else:
                self.logger.error(f"Unknown task type: {task_type}")
                return False

            if handler:
                result = await handler(payload)
                self.logger.info(f"✅ Task {task_id} completed successfully.")
                return True
            else:
                return False

        except Exception as e:
            retry_count = task_spec.get("retry_count", 0)
            max_retries = task_spec.get("max_retries", 3)

            self.logger.error(
                f"❌ Task {task_id} failed (attempt {retry_count + 1}/{max_retries}): {e}",
                exc_info=True
            )

            if retry_count < max_retries:
                task_spec["retry_count"] = retry_count + 1
                await self.enqueue_task(task_spec)
                self.logger.info(f"🔁 Retrying task {task_id} (attempt {retry_count + 2})")
                return False
            else:
                self.logger.critical(f"💀 Task {task_id} permanently failed after {max_retries} retries.")
                # Trigger emergency recovery
                if self.recovery:
                    await self.recovery.handle_task_failure(task_spec, e)
                return False

    async def _worker_loop(self):
        """Main task processing loop."""
        while not self.shutdown_event.is_set():
            try:
                # Wait for task with timeout to allow periodic checks
                task_spec = await asyncio.wait_for(self.task_queue.get(), timeout=5.0)
                task_id = task_spec["task_id"]

                # Create and track task
                task = asyncio.create_task(self._process_task(task_spec))
                self.active_tasks[task_id] = task

                # Cleanup finished tasks
                finished = {tid for tid, t in self.active_tasks.items() if t.done()}
                for tid in finished:
                    try:
                        await self.active_tasks[tid]
                    except Exception:
                        pass  # Already logged in _process_task
                    del self.active_tasks[tid]

            except asyncio.TimeoutError:
                continue  # No task available, check shutdown flag
            except Exception as e:
                self.logger.error(f"Unexpected error in worker loop: {e}", exc_info=True)
                if self.recovery:
                    await self.recovery.handle_worker_exception(e)

    async def start(self):
        """Start the worker."""
        self.logger.info("🟢 Starting Freelance Worker...")
        await self._initialize_services()
        self.running = True

        # Start monitoring heartbeat
        if self.monitor:
            asyncio.create_task(self.monitor.report_worker_heartbeat("freelance_worker"))

        try:
            await self._worker_loop()
        except Exception as e:
            self.logger.critical(f"Fatal error in worker: {e}", exc_info=True)
            raise
        finally:
            self.logger.info("Worker stopped.")

    @classmethod
    async def run(cls):
        """Convenience entry point."""
        worker = cls()
        await worker.start()


# Entry point for direct execution (e.g., via Celery or systemd)
if __name__ == "__main__":
    try:
        asyncio.run(FreelanceWorker.run())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logging.critical(f"Worker crashed: {e}", exc_info=True)
        sys.exit(1)