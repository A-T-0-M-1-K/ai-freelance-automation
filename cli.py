# cli.py
"""
CLI Interface for AI Freelance Automation System
Provides command-line control over autonomous operations, configuration, monitoring, and diagnostics.
Designed for developers, sysadmins, and advanced users.
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional, Dict, Any

# Add project root to path for absolute imports
PROJECT_ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

# Core imports (aligned with project structure)
from core.config.unified_config_manager import UnifiedConfigManager
from core.security.advanced_crypto_system import AdvancedCryptoSystem
from core.dependency.service_locator import ServiceLocator
from core.monitoring.intelligent_monitoring_system import IntelligentMonitoringSystem
from core.automation.auto_freelancer_core import AutoFreelancerCore
from scripts.maintenance.health_check import run_health_check
from scripts.deployment.update_system import update_system
from scripts.maintenance.backup_system import create_backup
from scripts.monitoring.generate_reports import generate_daily_report


class CLIApplication:
    """Main CLI application controller."""

    def __init__(self):
        self.parser = argparse.ArgumentParser(
            prog="ai-freelance",
            description="AI Freelance Automation — Fully autonomous freelancer system",
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog="""
Examples:
  ai-freelance start                     # Start autonomous operation
  ai-freelance status --detailed         # Show detailed system status
  ai-freelance config set ai.model gpt4  # Update configuration
  ai-freelance backup create             # Create manual backup
  ai-freelance report daily              # Generate daily performance report
            """
        )
        self._setup_arguments()
        self.args: Optional[argparse.Namespace] = None
        self.logger = logging.getLogger("CLI")

    def _setup_arguments(self):
        """Configure CLI argument parser."""
        subparsers = self.parser.add_subparsers(dest="command", help="Available commands")

        # === START ===
        start_parser = subparsers.add_parser("start", help="Start autonomous operation")
        start_parser.add_argument("--profile", default="default", help="Configuration profile (default: default)")
        start_parser.add_argument("--no-ui", action="store_true", help="Run without UI")
        start_parser.add_argument("--debug", action="store_true", help="Enable debug logging")

        # === STATUS ===
        status_parser = subparsers.add_parser("status", help="Show system status")
        status_parser.add_argument("--detailed", action="store_true", help="Show detailed metrics")
        status_parser.add_argument("--json", action="store_true", help="Output in JSON format")

        # === CONFIG ===
        config_parser = subparsers.add_parser("config", help="Manage configuration")
        config_sub = config_parser.add_subparsers(dest="config_action")

        # config get
        get_parser = config_sub.add_parser("get", help="Get config value")
        get_parser.add_argument("key", help="Configuration key (e.g., 'ai.model', 'platforms.upwork.enabled')")

        # config set
        set_parser = config_sub.add_parser("set", help="Set config value")
        set_parser.add_argument("key", help="Configuration key")
        set_parser.add_argument("value", help="New value (JSON-parsable)")

        # === BACKUP ===
        backup_parser = subparsers.add_parser("backup", help="Manage backups")
        backup_sub = backup_parser.add_subparsers(dest="backup_action")
        backup_sub.add_parser("create", help="Create manual backup")
        backup_sub.add_parser("list", help="List available backups")
        restore_parser = backup_sub.add_parser("restore", help="Restore from backup")
        restore_parser.add_argument("timestamp", help="Backup timestamp or 'latest'")

        # === REPORT ===
        report_parser = subparsers.add_parser("report", help="Generate reports")
        report_parser.add_argument("type", choices=["daily", "weekly", "monthly", "performance"], help="Report type")
        report_parser.add_argument("--output", default=None, help="Output file path")

        # === UPDATE ===
        update_parser = subparsers.add_parser("update", help="Update system")
        update_parser.add_argument("--force", action="store_true", help="Force update even if up-to-date")

        # === HEALTH ===
        health_parser = subparsers.add_parser("health", help="Run health check")
        health_parser.add_argument("--fix", action="store_true", help="Attempt automatic fixes")

        # === STOP ===
        subparsers.add_parser("stop", help="Gracefully stop autonomous operation")

    def _setup_logging(self, debug: bool = False):
        """Initialize logging based on CLI args."""
        log_level = logging.DEBUG if debug else logging.INFO
        logging.basicConfig(
            level=log_level,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            handlers=[
                logging.FileHandler(PROJECT_ROOT / "logs" / "app" / "cli.log"),
                logging.StreamHandler(sys.stdout)
            ]
        )

    async def _load_core_services(self) -> Dict[str, Any]:
        """Initialize and return core services needed for CLI operations."""
        try:
            config = UnifiedConfigManager()
            crypto = AdvancedCryptoSystem()

            # Register core services in locator
            locator = ServiceLocator.get_instance()
            locator.register("config", config)
            locator.register("crypto", crypto)
            locator.register("monitoring", IntelligentMonitoringSystem(config))

            return {
                "config": config,
                "crypto": crypto,
                "locator": locator
            }
        except Exception as e:
            self.logger.error(f"Failed to initialize core services: {e}")
            raise

    async def _run_start(self):
        """Start autonomous operation."""
        self._setup_logging(self.args.debug)
        self.logger.info("🚀 Starting AI Freelance Automation...")

        services = await self._load_core_services()
        config = services["config"]

        # Apply profile if specified
        if self.args.profile != "default":
            config.load_profile(self.args.profile)

        # Initialize and start core
        freelancer = AutoFreelancerCore(
            config=config,
            crypto=services["crypto"],
            service_locator=services["locator"]
        )
        await freelancer.start_autonomous_mode()

    async def _run_status(self):
        """Display system status."""
        try:
            services = await self._load_core_services()
            monitor = services["locator"].get("monitoring")
            status = await monitor.get_system_status(detailed=self.args.detailed)

            if self.args.json:
                print(json.dumps(status, indent=2, default=str))
            else:
                self._print_status_human_readable(status)
        except Exception as e:
            self.logger.error(f"Failed to retrieve status: {e}")
            sys.exit(1)

    def _print_status_human_readable(self, status: Dict):
        """Print status in human-readable format."""
        print("🟢 AI Freelance Automation — System Status")
        print(f"Uptime: {status.get('uptime', 'N/A')}")
        print(f"Active Jobs: {status.get('active_jobs', 0)}")
        print(f"CPU Load: {status.get('cpu_load', 'N/A')}%")
        print(f"Memory Usage: {status.get('memory_usage', 'N/A')} MB")
        print(f"Health: {'✅ Healthy' if status.get('healthy', False) else '⚠️  Issues detected'}")

        if self.args.detailed:
            print("\n--- Detailed Metrics ---")
            for key, value in status.items():
                if key not in ("uptime", "active_jobs", "cpu_load", "memory_usage", "healthy"):
                    print(f"{key}: {value}")

    async def _run_config(self):
        """Handle configuration commands."""
        services = await self._load_core_services()
        config = services["config"]

        if self.args.config_action == "get":
            value = config.get(self.args.key)
            print(json.dumps(value, indent=2) if isinstance(value, (dict, list)) else value)
        elif self.args.config_action == "set":
            try:
                value = json.loads(self.args.value)
            except json.JSONDecodeError:
                value = self.args.value  # Treat as string
            config.set(self.args.key, value)
            config.save()
            print(f"✅ Configuration updated: {self.args.key} = {value}")

    async def _run_backup(self):
        """Handle backup commands."""
        if self.args.backup_action == "create":
            backup_path = await create_backup(manual=True)
            print(f"✅ Backup created: {backup_path}")
        elif self.args.backup_action == "list":
            backup_dir = PROJECT_ROOT / "backup" / "manual"
            backups = sorted(backup_dir.glob("*_full"), reverse=True)
            for b in backups[:10]:
                print(b.name)
        elif self.args.backup_action == "restore":
            # Note: Full restore logic would require stopping system first
            print("⚠️  Restore functionality requires system shutdown. Use 'ai-freelance stop' first.")
            sys.exit(1)

    async def _run_report(self):
        """Generate reports."""
        report_func = {
            "daily": generate_daily_report,
            "weekly": lambda: generate_daily_report(period="weekly"),
            "monthly": lambda: generate_daily_report(period="monthly"),
            "performance": lambda: generate_daily_report(report_type="performance")
        }[self.args.type]

        output_path = await report_func()
        if self.args.output:
            os.rename(output_path, self.args.output)
            output_path = self.args.output
        print(f"✅ Report generated: {output_path}")

    async def _run_update(self):
        """Update system."""
        await update_system(force=self.args.force)
        print("✅ System updated successfully.")

    async def _run_health(self):
        """Run health check."""
        issues = await run_health_check(attempt_fix=self.args.fix)
        if not issues:
            print("✅ System is healthy.")
        else:
            print("⚠️  Issues detected:")
            for issue in issues:
                print(f"  - {issue}")
            if self.args.fix:
                print("🔧 Attempted automatic fixes.")

    async def _run_stop(self):
        """Gracefully stop the system."""
        print("🛑 Stopping AI Freelance Automation...")
        # In a real system, this would send signal to main process
        # For now, we just exit
        sys.exit(0)

    async def run(self):
        """Parse arguments and execute command."""
        self.args = self.parser.parse_args()

        if not self.args.command:
            self.parser.print_help()
            return

        command_map = {
            "start": self._run_start,
            "status": self._run_status,
            "config": self._run_config,
            "backup": self._run_backup,
            "report": self._run_report,
            "update": self._run_update,
            "health": self._run_health,
            "stop": self._run_stop,
        }

        handler = command_map.get(self.args.command)
        if not handler:
            self.logger.error(f"Unknown command: {self.args.command}")
            sys.exit(1)

        try:
            await handler()
        except KeyboardInterrupt:
            print("\n🛑 Operation cancelled by user.")
            sys.exit(0)
        except Exception as e:
            self.logger.exception(f"Command failed: {e}")
            sys.exit(1)


def main():
    """Entry point for CLI."""
    app = CLIApplication()
    asyncio.run(app.run())


if __name__ == "__main__":
    main()