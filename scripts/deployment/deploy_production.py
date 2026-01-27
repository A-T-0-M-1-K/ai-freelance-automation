#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Production Deployment Script for AI Freelance Automation System

This script handles the full deployment lifecycle for production environments:
- Validates system readiness
- Backs up current state
- Pulls latest code/config
- Applies database migrations
- Builds and restarts services
- Verifies health post-deployment
- Rolls back automatically on failure

Designed to be idempotent, safe, and compliant with enterprise deployment standards.
"""

import os
import sys
import json
import logging
import subprocess
import shutil
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any

# Add project root to path for imports
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

from core.config.unified_config_manager import UnifiedConfigManager
from core.security.audit_logger import AuditLogger
from scripts.maintenance.backup_system import backup_system
from scripts.maintenance.health_check import run_health_check
from scripts.deployment.rollback_deployment import rollback_to_previous_version


class ProductionDeployer:
    def __init__(self):
        self.project_root = PROJECT_ROOT
        self.deploy_dir = self.project_root / "scripts" / "deployment"
        self.backup_dir = self.project_root / "backup" / "automatic"
        self.logs_dir = self.project_root / "logs" / "app"
        self.timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        self.rollback_marker = self.project_root / ".rollback_pending"

        # Setup logging
        self._setup_logging()
        self.logger = logging.getLogger("DeployProduction")
        self.audit_logger = AuditLogger()

        # Load config
        try:
            self.config = UnifiedConfigManager()
            self.deploy_config = self.config.get("deploy", {})
        except Exception as e:
            self.logger.critical(f"❌ Failed to load configuration: {e}")
            sys.exit(1)

    def _setup_logging(self):
        """Configure logging for deployment process."""
        log_file = self.logs_dir / "deployment.log"
        log_file.parent.mkdir(parents=True, exist_ok=True)

        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            handlers=[
                logging.FileHandler(log_file),
                logging.StreamHandler(sys.stdout)
            ]
        )

    def _run_command(self, cmd: list, cwd: Optional[Path] = None, timeout: int = 300) -> subprocess.CompletedProcess:
        """Execute shell command safely with timeout and logging."""
        self.logger.debug(f"Running: {' '.join(cmd)}")
        try:
            result = subprocess.run(
                cmd,
                cwd=cwd or self.project_root,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False
            )
            if result.returncode != 0:
                self.logger.warning(f"Command failed (code {result.returncode}): {result.stderr.strip()}")
            return result
        except subprocess.TimeoutExpired:
            self.logger.error(f"Command timed out after {timeout}s: {' '.join(cmd)}")
            raise

    def _check_prerequisites(self) -> bool:
        """Verify system is ready for production deployment."""
        self.logger.info("🔍 Checking deployment prerequisites...")

        # Check Git status
        git_status = self._run_command(["git", "status", "--porcelain"])
        if git_status.stdout.strip():
            self.logger.error("❌ Working directory is not clean. Commit or stash changes first.")
            return False

        # Check Docker & Compose
        for tool in ["docker", "docker-compose"]:
            if shutil.which(tool) is None:
                self.logger.error(f"❌ Required tool '{tool}' not found in PATH")
                return False

        # Check disk space (>5GB free)
        total, used, free = shutil.disk_usage(self.project_root)
        if free < 5 * 1024**3:
            self.logger.error("❌ Insufficient disk space (<5GB)")
            return False

        # Check config validity
        if not self.config.is_valid():
            self.logger.error("❌ Configuration validation failed")
            return False

        self.logger.info("✅ All prerequisites satisfied")
        return True

    def _create_rollback_point(self):
        """Create a rollback marker and backup before deployment."""
        self.logger.info("🛡️ Creating rollback point...")
        self.rollback_marker.write_text(self.timestamp)
        backup_system(backup_type="incremental", reason="pre-deployment")

    def _pull_latest_changes(self):
        """Fetch and apply latest production code."""
        self.logger.info("🔄 Pulling latest changes from production branch...")
        self._run_command(["git", "fetch", "origin"])
        self._run_command(["git", "checkout", "production"])
        self._run_command(["git", "pull", "origin", "production"])

    def _apply_migrations(self):
        """Run database and system migrations."""
        self.logger.info("🗃️ Applying database migrations...")
        migration_script = self.project_root / "migrations" / "migration_manager.py"
        if migration_script.exists():
            self._run_command([sys.executable, str(migration_script), "--apply", "--env=production"])

    def _build_and_restart_services(self):
        """Rebuild containers and restart production services."""
        self.logger.info("🐳 Rebuilding and restarting services...")
        compose_file = self.project_root / "docker-compose.prod.yml"
        if not compose_file.exists():
            compose_file = self.project_mount / "docker-compose.yml"

        self._run_command(["docker-compose", "-f", str(compose_file), "down"])
        self._run_command(["docker-compose", "-f", str(compose_file), "up", "-d", "--build"])

    def _verify_post_deploy_health(self) -> bool:
        """Run comprehensive health check after deployment."""
        self.logger.info("🩺 Running post-deployment health verification...")
        health_result = run_health_check(full_check=True)
        if not health_result.get("healthy", False):
            self.logger.error("❌ Post-deployment health check failed")
            return False
        self.logger.info("✅ System health verified")
        return True

    def _cleanup_rollback_marker(self):
        """Remove rollback marker on successful deployment."""
        if self.rollback_marker.exists():
            self.rollback_marker.unlink()

    def deploy(self) -> bool:
        """
        Execute full production deployment sequence.
        Returns True on success, False on failure (with auto-rollback).
        """
        self.logger.info("🚀 Starting production deployment...")
        self.audit_logger.log("DEPLOYMENT_START", {"user": "system", "env": "production"})

        try:
            if not self._check_prerequisites():
                return False

            self._create_rollback_point()
            self._pull_latest_changes()
            self._apply_migrations()
            self._build_and_restart_services()

            if not self._verify_post_deploy_health():
                raise RuntimeError("Post-deployment verification failed")

            self._cleanup_rollback_marker()
            self.audit_logger.log("DEPLOYMENT_SUCCESS", {"timestamp": self.timestamp})
            self.logger.info("🎉 Production deployment completed successfully!")
            return True

        except Exception as e:
            self.logger.critical(f"💥 Deployment failed: {e}", exc_info=True)
            self.audit_logger.log("DEPLOYMENT_FAILURE", {"error": str(e)})

            # Auto-rollback
            self.logger.info("🔄 Initiating automatic rollback...")
            try:
                rollback_to_previous_version()
                self.logger.info("✅ Rollback completed")
            except Exception as rb_e:
                self.logger.critical(f"🔥 Rollback also failed: {rb_e}", exc_info=True)

            return False


def main():
    """Entry point for production deployment."""
    deployer = ProductionDeployer()
    success = deployer.deploy()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()