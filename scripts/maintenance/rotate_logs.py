#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Log Rotation Script for AI Freelance Automation System

Purpose:
    Automatically rotates log files to prevent disk overflow and maintain clean logs.
    Supports size-based rotation with compression and configurable retention.

Features:
    - Rotates logs by size (default: 100 MB)
    - Compresses old logs with gzip
    - Respects retention policy (default: 30 days or 10 files per log type)
    - Safe concurrent execution (uses file locking)
    - Integrates with system config and logging settings
    - Idempotent and failure-tolerant

Dependencies:
    - Uses only stdlib + project config
    - No external dependencies to avoid conflicts

Safety:
    - Never deletes active log files
    - Preserves file permissions
    - Logs its own activity to audit trail
"""

import os
import sys
import gzip
import shutil
import logging
import argparse
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Optional
from contextlib import contextmanager

# Add project root to path for imports
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

# Local imports (must match your structure)
try:
    from core.config.unified_config_manager import UnifiedConfigManager
    from core.security.audit_logger import AuditLogger
except ImportError as e:
    print(f"❌ Critical import error: {e}", file=sys.stderr)
    sys.exit(1)


@contextmanager
def file_lock(lock_path: Path):
    """Simple file-based lock to prevent concurrent rotation."""
    if lock_path.exists():
        raise RuntimeError(f"Another rotation process is running (lock file exists: {lock_path})")
    try:
        lock_path.write_text(str(os.getpid()))
        yield
    finally:
        if lock_path.exists():
            lock_path.unlink()


class LogRotator:
    def __init__(self, config: Optional[UnifiedConfigManager] = None):
        self.config = config or UnifiedConfigManager()
        self.logger = logging.getLogger("LogRotator")
        self.audit_logger = AuditLogger()

        # Load rotation settings
        log_cfg = self.config.get("logging", {})
        self.rotation_size_mb = log_cfg.get("rotation_size_mb", 100)
        self.retention_days = log_cfg.get("retention_days", 30)
        self.max_files_per_type = log_cfg.get("max_files_per_type", 10)
        self.compress_old = log_cfg.get("compress_rotated", True)

        self.log_dir = Path(self.config.get("paths.logs", "logs")).resolve()
        self.lock_file = self.log_dir / ".rotate_lock"

        # Ensure log dir exists
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def _should_rotate(self, log_file: Path) -> bool:
        """Check if log file exceeds size threshold."""
        if not log_file.exists():
            return False
        size_bytes = log_file.stat().st_size
        return size_bytes > (self.rotation_size_mb * 1024 * 1024)

    def _rotate_file(self, log_file: Path) -> bool:
        """Rotate a single log file: rename → compress → truncate original."""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            rotated_name = f"{log_file.stem}.{timestamp}{log_file.suffix}"
            rotated_path = log_file.parent / rotated_name

            # Rename current log
            shutil.move(str(log_file), str(rotated_path))

            # Recreate empty log file with same permissions
            log_file.touch(exist_ok=True)
            if rotated_path.exists():
                shutil.copymode(rotated_path, log_file)

            # Compress if enabled
            if self.compress_old:
                gz_path = rotated_path.with_suffix(rotated_path.suffix + ".gz")
                with open(rotated_path, 'rb') as f_in:
                    with gzip.open(gz_path, 'wb') as f_out:
                        shutil.copyfileobj(f_in, f_out)
                rotated_path.unlink()  # Remove uncompressed
                rotated_path = gz_path

            self.logger.info(f"✅ Rotated log: {log_file} → {rotated_path}")
            self.audit_logger.log("LOG_ROTATION", {
                "action": "rotate",
                "original": str(log_file),
                "rotated": str(rotated_path),
                "size_mb": round(rotated_path.stat().st_size / (1024 * 1024), 2)
            })
            return True

        except Exception as e:
            self.logger.error(f"❌ Failed to rotate {log_file}: {e}")
            return False

    def _cleanup_old_logs(self, log_type_dir: Path):
        """Remove logs older than retention period or exceeding max count."""
        if not log_type_dir.is_dir():
            return

        # Collect all rotated logs (including .gz)
        rotated_logs: List[Path] = []
        for ext in [".log", ".log.gz"]:
            rotated_logs.extend(log_type_dir.glob(f"*{ext}"))
        rotated_logs = [p for p in rotated_logs if p.name != "application.log"]  # skip active

        # Sort by modification time (oldest first)
        rotated_logs.sort(key=lambda x: x.stat().st_mtime)

        # Remove by age
        cutoff = datetime.now() - timedelta(days=self.retention_days)
        for log in rotated_logs[:]:
            mtime = datetime.fromtimestamp(log.stat().st_mtime)
            if mtime < cutoff:
                try:
                    log.unlink()
                    self.logger.info(f"🧹 Deleted old log (age): {log}")
                    rotated_logs.remove(log)
                except OSError as e:
                    self.logger.warning(f"⚠️ Could not delete {log}: {e}")

        # Remove by count (keep newest N)
        if len(rotated_logs) > self.max_files_per_type:
            to_remove = rotated_logs[:-self.max_files_per_type]
            for log in to_remove:
                try:
                    log.unlink()
                    self.logger.info(f"🧹 Deleted old log (count limit): {log}")
                except OSError as e:
                    self.logger.warning(f"⚠️ Could not delete {log}: {e}")

    def rotate_all_logs(self):
        """Main entry point: rotate all log files in the system."""
        with file_lock(self.lock_file):
            self.logger.info("🔄 Starting log rotation...")

            # Discover all log subdirectories (ai/, app/, errors/, monitoring/)
            for log_subdir in self.log_dir.iterdir():
                if not log_subdir.is_dir():
                    continue

                self.logger.info(f"📂 Processing log directory: {log_subdir.name}")

                # Rotate each active log file (e.g., application.log, transcription.log)
                for log_file in log_subdir.glob("*.log"):
                    if log_file.name.startswith("."):  # skip hidden
                        continue
                    if self._should_rotate(log_file):
                        self._rotate_file(log_file)

                # Cleanup old rotated logs
                self._cleanup_old_logs(log_subdir)

            self.logger.info("✅ Log rotation completed successfully.")

    @classmethod
    def run_from_cli(cls):
        parser = argparse.ArgumentParser(description="Rotate system logs")
        parser.add_argument("--dry-run", action="store_true", help="Show what would be done")
        args = parser.parse_args()

        if args.dry_run:
            print("ℹ️ Dry run mode — no changes will be made.")
            return

        rotator = cls()
        rotator.rotate_all_logs()


if __name__ == "__main__":
    # Setup minimal logging for script itself
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(PROJECT_ROOT / "logs/app/maintenance.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout)
        ]
    )

    try:
        LogRotator.run_from_cli()
    except Exception as e:
        logging.critical(f"💥 Log rotation failed: {e}", exc_info=True)
        sys.exit(1)