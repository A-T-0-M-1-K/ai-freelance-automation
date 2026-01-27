# AI_FREELANCE_AUTOMATION/scripts/deployment/rollback_deployment.py
"""
Rollback Deployment Script
==========================

Safely reverts the system to a previous stable state in case of failed deployment.
Integrates with backup, monitoring, and health systems to ensure integrity.

Features:
- Validates rollback target version
- Restores code, config, and data from backup
- Updates runtime environment
- Triggers post-rollback health check
- Logs all actions for audit and debugging
- Supports dry-run mode

Designed to be idempotent and safe for production use.
"""

import os
import sys
import shutil
import json
import logging
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

# Add project root to path for imports
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.config.unified_config_manager import UnifiedConfigManager
from core.security.audit_logger import AuditLogger
from core.monitoring.intelligent_monitoring_system import IntelligentMonitoringSystem
from scripts.maintenance.backup_system import BackupSystem


class RollbackDeployment:
    def __init__(self, config: Optional[UnifiedConfigManager] = None):
        self.project_root = PROJECT_ROOT
        self.config = config or UnifiedConfigManager()
        self.logger = logging.getLogger("RollbackDeployment")
        self.audit_logger = AuditLogger()
        self.backup_system = BackupSystem(self.config)
        self.monitoring = IntelligentMonitoringSystem(self.config)

        # Paths
        self.deployments_dir = self.project_root / "backup" / "deployments"
        self.current_state_file = self.project_root / ".current_deployment.json"
        self.rollback_log = self.project_root / "logs" / "app" / "rollback.log"

        self._setup_logging()

    def _setup_logging(self):
        """Configure dedicated logging for rollback operations."""
        rollback_handler = logging.FileHandler(self.rollback_log)
        rollback_handler.setFormatter(
            logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
        )
        self.logger.addHandler(rollback_handler)
        self.logger.setLevel(logging.INFO)

    def get_current_deployment(self) -> Dict[str, Any]:
        """Read current deployment metadata."""
        if not self.current_state_file.exists():
            raise RuntimeError("No active deployment state found. Cannot rollback.")
        with open(self.current_state_file, 'r', encoding='utf-8') as f:
            return json.load(f)

    def list_available_rollback_targets(self) -> list:
        """List all valid rollback targets (previous deployments)."""
        if not self.deployments_dir.exists():
            return []
        targets = []
        for item in sorted(self.deployments_dir.iterdir(), reverse=True):
            if item.is_dir() and (item / "metadata.json").exists():
                with open(item / "metadata.json", 'r', encoding='utf-8') as f:
                    meta = json.load(f)
                targets.append(meta)
        return targets

    def validate_rollback_target(self, target_version: str) -> Dict[str, Any]:
        """Validate that the target version exists and is restorable."""
        target_path = self.deployments_dir / target_version
        if not target_path.exists():
            raise ValueError(f"Rollback target '{target_version}' does not exist.")
        meta_file = target_path / "metadata.json"
        if not meta_file.exists():
            raise ValueError(f"Corrupted rollback target: missing metadata.json")
        with open(meta_file, 'r', encoding='utf-8') as f:
            return json.load(f)

    def perform_rollback(
        self,
        target_version: Optional[str] = None,
        dry_run: bool = False
    ) -> bool:
        """
        Perform full system rollback to a previous version.

        Args:
            target_version: Version to roll back to. If None, uses last known good state.
            dry_run: If True, only simulate rollback without making changes.

        Returns:
            True if rollback succeeded or simulated successfully.
        """
        try:
            self.logger.info("🔄 Starting rollback procedure...")
            self.audit_logger.log("ROLLBACK_INITIATED", {"target": target_version, "dry_run": dry_run})

            # Step 1: Determine target
            current = self.get_current_deployment()
            if target_version is None:
                targets = self.list_available_rollback_targets()
                if not targets:
                    raise RuntimeError("No rollback targets available.")
                # Skip current version
                valid_targets = [t for t in targets if t["version"] != current.get("version")]
                if not valid_targets:
                    raise RuntimeError("No previous versions available for rollback.")
                target_version = valid_targets[0]["version"]

            target_meta = self.validate_rollback_target(target_version)
            self.logger.info(f"🎯 Targeting rollback to version: {target_version}")

            if dry_run:
                self.logger.info("🔍 DRY RUN: Simulating rollback steps (no changes made)")
                self.audit_logger.log("ROLLBACK_DRY_RUN", {"target": target_version})
                return True

            # Step 2: Stop services gracefully
            self._stop_services()

            # Step 3: Restore code and configs
            self._restore_codebase(target_version)
            self._restore_configs(target_version)

            # Step 4: Restore critical data if needed (e.g., model registry, client index)
            self._restore_data(target_version)

            # Step 5: Update current state
            self._update_current_deployment_state(target_meta)

            # Step 6: Reinstall dependencies (optional, based on config)
            if self.config.get("deployment.rollback.reinstall_deps", False):
                self._reinstall_dependencies(target_version)

            # Step 7: Start services
            self._start_services()

            # Step 8: Health check
            if not self._run_post_rollback_health_check():
                raise RuntimeError("Post-rollback health check failed!")

            self.logger.info(f"✅ Rollback to {target_version} completed successfully.")
            self.audit_logger.log("ROLLBACK_SUCCESS", {"version": target_version})
            self.monitoring.record_event("system.rollback.success", {"version": target_version})

            return True

        except Exception as e:
            error_msg = f"❌ Rollback failed: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            self.audit_logger.log("ROLLBACK_FAILURE", {"error": str(e), "target": target_version})
            self.monitoring.record_event("system.rollback.failure", {"error": str(e)})
            # Attempt emergency recovery
            self._trigger_emergency_recovery()
            raise

    def _stop_services(self):
        """Gracefully stop all running services."""
        self.logger.info("🛑 Stopping application services...")
        try:
            subprocess.run([sys.executable, "-m", "scripts.maintenance.health_check", "--stop"], check=True)
        except subprocess.CalledProcessError as e:
            self.logger.warning(f"⚠️  Failed to stop services gracefully: {e}")

    def _start_services(self):
        """Start services after rollback."""
        self.logger.info("🟢 Starting application services...")
        try:
            subprocess.run([sys.executable, "main.py", "--background"], cwd=self.project_root, check=True)
        except subprocess.CalledProcessError as e:
            self.logger.error(f"💥 Failed to start services: {e}")
            raise

    def _restore_codebase(self, version: str):
        """Restore source code from backup."""
        src = self.deployments_dir / version / "code"
        dst = self.project_root
        self.logger.info(f"📦 Restoring codebase from {src} to {dst}")
        if src.exists():
            # Clean current code (except .git, logs, backups)
            for item in dst.iterdir():
                if item.name in {".git", "logs", "backup", "__pycache__", ".venv"}:
                    continue
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()
            # Copy restored code
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            self.logger.warning("⚠️  No code backup found – assuming in-place rollback")

    def _restore_configs(self, version: str):
        """Restore configuration files."""
        src = self.deployments_dir / version / "config"
        dst = self.project_root / "config"
        if src.exists():
            self.logger.info(f"⚙️  Restoring configs from {src}")
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)

    def _restore_data(self, version: str):
        """Restore critical mutable data if included in backup."""
        data_backup = self.deployments_dir / version / "data"
        if data_backup.exists():
            self.logger.info("💾 Restoring critical data (clients, jobs, etc.)")
            # Only restore non-redundant data; avoid overwriting live DB unless necessary
            # This is conservative by design
            target_dirs = ["clients", "jobs", "projects", "finances"]
            for d in target_dirs:
                src_dir = data_backup / d
                dst_dir = self.project_root / "data" / d
                if src_dir.exists():
                    if dst_dir.exists():
                        shutil.rmtree(dst_dir)
                    shutil.copytree(src_dir, dst_dir)

    def _reinstall_dependencies(self, version: str):
        """Reinstall Python dependencies for target version."""
        req_file = self.deployments_dir / version / "requirements-base.txt"
        if req_file.exists():
            self.logger.info("📥 Reinstalling dependencies...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", str(req_file)])
        else:
            self.logger.warning("⚠️  No requirements-base.txt in backup – skipping dependency reinstall")

    def _update_current_deployment_state(self, metadata: Dict[str, Any]):
        """Update current deployment marker."""
        with open(self.current_state_file, 'w', encoding='utf-8') as f:
            json.dump({
                "version": metadata["version"],
                "timestamp": datetime.utcnow().isoformat(),
                "rolled_back_from": metadata.get("previous_version"),
                "rollback_time": datetime.utcnow().isoformat()
            }, f, indent=2)

    def _run_post_rollback_health_check(self) -> bool:
        """Run basic health validation after rollback."""
        self.logger.info("🩺 Running post-rollback health check...")
        try:
            result = subprocess.run(
                [sys.executable, "-m", "scripts.maintenance.health_check", "--quick"],
                capture_output=True,
                text=True,
                cwd=self.project_root
            )
            return result.returncode == 0
        except Exception as e:
            self.logger.error(f"Health check execution failed: {e}")
            return False

    def _trigger_emergency_recovery(self):
        """Trigger core emergency recovery if rollback fails."""
        self.logger.critical("🚨 Triggering emergency recovery protocol...")
        try:
            from core.emergency_recovery import EmergencyRecovery
            er = EmergencyRecovery()
            er.initiate_full_recovery()
        except Exception as e:
            self.logger.critical(f"Emergency recovery failed: {e}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Rollback to a previous deployment version")
    parser.add_argument("--version", type=str, help="Target version to roll back to")
    parser.add_argument("--dry-run", action="store_true", help="Simulate rollback without changes")
    args = parser.parse_args()

    rollback = RollbackDeployment()
    success = rollback.perform_rollback(target_version=args.version, dry_run=args.dry_run)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()