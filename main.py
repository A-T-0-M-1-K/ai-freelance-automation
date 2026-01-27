#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI_FREELANCE_AUTOMATION — Main Entry Point
==================================================
Fully autonomous AI freelancer system.
Replaces human on freelance platforms with zero manual intervention.

Architecture:
- Single responsibility: orchestrate startup/shutdown
- Delegates all logic to core.ApplicationCore
- Enforces security, logging, and configuration standards

Author: AI Freelance Automation System
Version: 1.0.0
"""

import asyncio
import logging
import sys
import os
import signal
from pathlib import Path

# Ensure the project root is in sys.path
PROJECT_ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

# Create logs directory if not exists
LOGS_DIR = PROJECT_ROOT / "logs" / "app"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# Configure root logger BEFORE any imports
def _setup_root_logging():
    """Configure global logging with file + console output."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s.%(msecs)03d [%(levelname)-8s] %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.FileHandler(LOGS_DIR / "application.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout)
        ]
    )
    # Reduce noise from third-party libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)

_setup_root_logging()

logger = logging.getLogger("Main")

# Import core components AFTER logging is ready
try:
    from core.config.unified_config_manager import UnifiedConfigManager
    from core.security.advanced_crypto_system import AdvancedCryptoSystem
    from core.application_core import ApplicationCore
except ImportError as e:
    logger.critical(f"💥 Failed to import core modules: {e}")
    sys.exit(1)


class ApplicationLauncher:
    """
    Manages the full lifecycle of the autonomous system.
    Handles signals, graceful shutdown, and emergency recovery.
    """

    def __init__(self):
        self.app: ApplicationCore | None = None
        self.shutdown_event = asyncio.Event()
        self._setup_signal_handlers()

    def _setup_signal_handlers(self):
        """Register OS signal handlers for graceful shutdown."""
        def signal_handler(signum, frame):
            sig_name = signal.Signals(signum).name
            logger.info(f"🛑 Received signal {sig_name}. Initiating graceful shutdown...")
            if self.app:
                asyncio.create_task(self._trigger_shutdown())

        signal.signal(signal.SIGINT, signal_handler)   # Ctrl+C
        signal.signal(signal.SIGTERM, signal_handler)  # Docker/K8s stop

    async def _trigger_shutdown(self):
        """Trigger shutdown sequence."""
        if not self.shutdown_event.is_set():
            self.shutdown_event.set()
            if self.app:
                await self.app.stop()

    async def run(self):
        """Main entry point for the autonomous system."""
        logger.info("🚀 Starting AI Freelance Automation System v1.0.0")
        logger.info(f"📁 Project root: {PROJECT_ROOT}")

        try:
            # Step 1: Load configuration
            config = UnifiedConfigManager()
            logger.info("✅ Configuration loaded successfully")

            # Step 2: Initialize cryptographic system
            crypto = AdvancedCryptoSystem()
            logger.info("🔐 Cryptographic system initialized")

            # Step 3: Create and start application core
            self.app = ApplicationCore(config=config, crypto=crypto)
            await self.app.start()

            # Step 4: Wait for shutdown signal
            logger.info("🟢 System is fully operational and autonomous")
            await self.shutdown_event.wait()

        except KeyboardInterrupt:
            logger.info("⚠️  Interrupted by user (Ctrl+C)")
        except Exception as e:
            logger.exception(f"💥 Unhandled exception in main loop: {e}")
            # Emergency self-diagnosis would be triggered here in real system
            sys.exit(1)
        finally:
            logger.info("🏁 Shutting down AI Freelance Automation System...")
            if self.app and not self.shutdown_event.is_set():
                await self.app.stop()
            logger.info("✅ Shutdown complete")


def main():
    """Synchronous entry point for CLI execution."""
    try:
        launcher = ApplicationLauncher()
        asyncio.run(launcher.run())
    except Exception as e:
        logger.critical(f"💀 Fatal error during launch: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()