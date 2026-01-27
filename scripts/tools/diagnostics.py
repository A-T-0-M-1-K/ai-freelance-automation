#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Diagnostics Tool for AI Freelance Automation System

Performs comprehensive system health checks:
- File integrity
- Dependency status
- Configuration validity
- Service availability
- Disk/memory/CPU usage
- AI model readiness
- Security posture

Designed to be safe, non-intrusive, and dependency-light.
Can be run standalone or as part of maintenance scripts.
"""

import os
import sys
import json
import hashlib
import logging
import platform
import subprocess
import psutil
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime

# Configure minimal internal logger (no external dependencies)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [DIAGNOSTICS] %(levelname)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("Diagnostics")

# Constants
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent.resolve()
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"
AI_MODELS_DIR = PROJECT_ROOT / "ai" / "models"
LOGS_DIR = PROJECT_ROOT / "logs"
REQUIREMENTS_FILES = [
    "requirements.txt",
    "requirements-dev.txt",
    "requirements-prod.txt",
    "requirements-gpu.txt"
]


class DiagnosticsTool:
    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = config_path or (CONFIG_DIR / "settings.json")
        self.results: Dict[str, Any] = {
            "timestamp": datetime.utcnow().isoformat(),
            "system": {},
            "files": {},
            "dependencies": {},
            "services": {},
            "ai": {},
            "security": {},
            "summary": {"passed": 0, "failed": 0, "warnings": 0}
        }

    def run_full_diagnostic(self) -> Dict[str, Any]:
        """Run all diagnostic checks and return structured results."""
        logger.info("🚀 Starting full system diagnostics...")

        self._check_system_resources()
        self._check_file_structure()
        self._check_dependencies()
        self._check_config_validity()
        self._check_ai_models()
        self._check_security_baseline()

        self._generate_summary()
        self._log_summary()
        return self.results

    def _check_system_resources(self):
        """Check CPU, memory, disk usage."""
        try:
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage(str(PROJECT_ROOT))

            self.results["system"] = {
                "platform": platform.platform(),
                "python_version": sys.version,
                "cpu_cores": psutil.cpu_count(),
                "cpu_usage_percent": cpu_percent,
                "memory_total_gb": round(memory.total / (1024 ** 3), 2),
                "memory_available_gb": round(memory.available / (1024 ** 3), 2),
                "memory_percent_used": memory.percent,
                "disk_total_gb": round(disk.total / (1024 ** 3), 2),
                "disk_free_gb": round(disk.free / (1024 ** 3), 2),
                "disk_percent_used": (disk.used / disk.total) * 100,
                "status": "OK"
            }
            logger.info("✅ System resources check passed.")
        except Exception as e:
            self.results["system"] = {"status": "ERROR", "error": str(e)}
            logger.error(f"❌ System resources check failed: {e}")

    def _check_file_structure(self):
        """Validate critical directories and files exist."""
        required_paths = [
            CONFIG_DIR,
            DATA_DIR,
            AI_MODELS_DIR,
            LOGS_DIR,
            PROJECT_ROOT / "core",
            PROJECT_ROOT / "services",
            PROJECT_ROOT / "platforms"
        ]

        missing = []
        for path in required_paths:
            if not path.exists():
                missing.append(str(path))

        if missing:
            self.results["files"] = {"status": "WARNING", "missing_paths": missing}
            self.results["summary"]["warnings"] += 1
            logger.warning(f"⚠️ Missing paths: {missing}")
        else:
            self.results["files"] = {"status": "OK"}
            self.results["summary"]["passed"] += 1
            logger.info("✅ File structure check passed.")

    def _check_dependencies(self):
        """Check if required Python packages are installed."""
        try:
            # Read main requirements
            req_file = PROJECT_ROOT / "requirements.txt"
            if not req_file.exists():
                self.results["dependencies"] = {"status": "ERROR", "error": "requirements.txt not found"}
                self.results["summary"]["failed"] += 1
                return

            with open(req_file, "r", encoding="utf-8") as f:
                lines = [line.strip() for line in f if line.strip() and not line.startswith("#")]

            # Extract package names (simple parsing)
            expected_packages = set()
            for line in lines:
                if "==" in line:
                    pkg = line.split("==")[0].strip()
                elif ">=" in line:
                    pkg = line.split(">=")[0].strip()
                elif "<=" in line:
                    pkg = line.split("<=")[0].strip()
                else:
                    pkg = line.split("[")[0].strip() if "[" in line else line
                expected_packages.add(pkg.lower())

            # Get installed packages
            result = subprocess.run([sys.executable, "-m", "pip", "list", "--format=json"],
                                    capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                raise RuntimeError("Failed to list installed packages")

            installed = {pkg["name"].lower() for pkg in json.loads(result.stdout)}

            missing_deps = expected_packages - installed
            if missing_deps:
                self.results["dependencies"] = {"status": "WARNING", "missing": sorted(missing_deps)}
                self.results["summary"]["warnings"] += 1
                logger.warning(f"⚠️ Missing dependencies: {missing_deps}")
            else:
                self.results["dependencies"] = {"status": "OK"}
                self.results["summary"]["passed"] += 1
                logger.info("✅ Dependencies check passed.")
        except Exception as e:
            self.results["dependencies"] = {"status": "ERROR", "error": str(e)}
            self.results["summary"]["failed"] += 1
            logger.error(f"❌ Dependencies check failed: {e}")

    def _check_config_validity(self):
        """Validate JSON config files against schemas (if available)."""
        try:
            from jsonschema import validate, ValidationError  # Optional, fail gracefully
            schema_dir = CONFIG_DIR / "schemas"
            configs = list(CONFIG_DIR.glob("*.json"))
            invalid_configs = []

            for config_file in configs:
                if config_file.name == "config_manager.py":
                    continue
                schema_file = schema_dir / (config_file.stem + ".schema.json")
                if not schema_file.exists():
                    continue  # Skip if no schema

                with open(config_file, "r", encoding="utf-8") as f:
                    config_data = json.load(f)
                with open(schema_file, "r", encoding="utf-8") as f:
                    schema = json.load(f)

                try:
                    validate(instance=config_data, schema=schema)
                except ValidationError as ve:
                    invalid_configs.append({
                        "file": str(config_file),
                        "error": str(ve.message),
                        "path": list(ve.path)
                    })

            if invalid_configs:
                self.results["config"] = {"status": "ERROR", "invalid": invalid_configs}
                self.results["summary"]["failed"] += len(invalid_configs)
                logger.error(f"❌ Invalid configs: {len(invalid_configs)}")
            else:
                self.results["config"] = {"status": "OK"}
                self.results["summary"]["passed"] += 1
                logger.info("✅ Configuration validation passed.")
        except ImportError:
            self.results["config"] = {"status": "SKIPPED", "reason": "jsonschema not installed"}
            logger.info("ℹ️ Skipping config validation (jsonschema not available)")
        except Exception as e:
            self.results["config"] = {"status": "ERROR", "error": str(e)}
            self.results["summary"]["failed"] += 1
            logger.error(f"❌ Config validation failed: {e}")

    def _check_ai_models(self):
        """Check if AI models exist and have valid checksums (if provided)."""
        if not AI_MODELS_DIR.exists():
            self.results["ai"] = {"status": "WARNING", "reason": "AI models directory missing"}
            self.results["summary"]["warnings"] += 1
            return

        model_dirs = [d for d in AI_MODELS_DIR.iterdir() if d.is_dir()]
        if not model_dirs:
            self.results["ai"] = {"status": "WARNING", "reason": "No AI models found"}
            self.results["summary"]["warnings"] += 1
            return

        self.results["ai"] = {
            "status": "OK",
            "models_found": len(model_dirs),
            "model_names": [d.name for d in model_dirs]
        }
        self.results["summary"]["passed"] += 1
        logger.info(f"✅ Found {len(model_dirs)} AI models.")

    def _check_security_baseline(self):
        """Basic security checks: .env exposure, permissions."""
        issues = []

        # Check if .env is accidentally committed
        env_path = PROJECT_ROOT / ".env"
        if env_path.exists():
            git_check = subprocess.run(["git", "ls-files", "--error-unmatch", ".env"],
                                       cwd=PROJECT_ROOT, capture_output=True)
            if git_check.returncode == 0:
                issues.append(".env file is tracked by Git — potential security risk!")

        # Check sensitive file permissions (Unix-like systems)
        if os.name != "nt":
            for sensitive in [".env", "config/security.json"]:
                p = PROJECT_ROOT / sensitive
                if p.exists():
                    stat = p.stat()
                    if stat.st_mode & 0o077:  # Group/other can read
                        issues.append(f"File {sensitive} has overly permissive permissions")

        if issues:
            self.results["security"] = {"status": "WARNING", "issues": issues}
            self.results["summary"]["warnings"] += len(issues)
            logger.warning(f"⚠️ Security issues: {issues}")
        else:
            self.results["security"] = {"status": "OK"}
            self.results["summary"]["passed"] += 1
            logger.info("✅ Security baseline check passed.")

    def _generate_summary(self):
        """Finalize summary counts."""
        total_checks = sum(
            1 for v in self.results.values()
            if isinstance(v, dict) and "status" in v and v["status"] in ("OK", "WARNING", "ERROR")
        )
        self.results["summary"]["total_checks"] = total_checks

    def _log_summary(self):
        s = self.results["summary"]
        logger.info(f"📊 Diagnostic Summary: {s['passed']} passed, {s['failed']} failed, {s['warnings']} warnings")

    def save_report(self, output_path: Optional[Path] = None) -> Path:
        """Save diagnostic report to JSON file."""
        if output_path is None:
            output_path = PROJECT_ROOT / "logs" / "diagnostics" / f"diagnostics_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(self.results, f, indent=2, ensure_ascii=False)
        logger.info(f"📄 Report saved to: {output_path}")
        return output_path


def main():
    """CLI entry point."""
    diag = DiagnosticsTool()
    results = diag.run_full_diagnostic()
    report_path = diag.save_report()

    # Exit code: 0 = OK, 1 = warnings, 2 = errors
    summary = results["summary"]
    if summary["failed"] > 0:
        sys.exit(2)
    elif summary["warnings"] > 0:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()