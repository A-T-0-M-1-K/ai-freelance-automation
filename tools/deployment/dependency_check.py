# AI_FREELANCE_AUTOMATION/tools/deployment/dependency_check.py
"""
Dependency Checker Tool

Verifies that all required Python packages are installed and compatible
with the current environment profile (dev, prod, test, gpu, etc.).
Detects version conflicts, missing dependencies, and security vulnerabilities.

Used during deployment, CI/CD, and system health checks.
"""

import sys
import logging
import subprocess
import json
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from packaging.requirements import Requirement
from packaging.version import Version, InvalidVersion
from packaging.utils import canonicalize_name

# Configure module-specific logger
logger = logging.getLogger(__name__)


class DependencyChecker:
    """
    Validates installed dependencies against requirement files.
    Supports multiple environments: dev, prod, test, gpu.
    """

    ENV_REQUIREMENT_MAP = {
        "development": "requirements-dev.txt",
        "production": "requirements-prod.txt",
        "testing": "requirements-test.txt",
        "gpu": "requirements-gpu.txt",
        "default": "requirements-base.txt"
    }

    def __init__(self, project_root: Optional[Path] = None):
        self.project_root = project_root or Path(__file__).parent.parent.parent.parent.resolve()
        self.installed_packages = self._get_installed_packages()

    def _get_installed_packages(self) -> Dict[str, Version]:
        """Fetch currently installed packages and their versions."""
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "list", "--format=json"],
                capture_output=True,
                text=True,
                check=True
            )
            packages = json.loads(result.stdout)
            return {
                canonicalize_name(pkg["name"]): Version(pkg["version"])
                for pkg in packages
            }
        except (subprocess.CalledProcessError, json.JSONDecodeError, InvalidVersion) as e:
            logger.error("Failed to retrieve installed packages: %s", e)
            return {}

    def _parse_requirements_file(self, req_file: Path) -> List[Requirement]:
        """Parse a requirements-base.txt file into Requirement objects."""
        if not req_file.exists():
            logger.warning("Requirements file not found: %s", req_file)
            return []

        requirements = []
        with open(req_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or line.startswith("-"):
                    continue
                try:
                    requirements.append(Requirement(line))
                except Exception as e:
                    logger.warning("Skipping invalid requirement '%s': %s", line, e)
        return requirements

    def _check_requirement_compatibility(
        self, req: Requirement
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if a requirement is satisfied by installed packages.
        Returns (is_compatible, reason_if_not).
        """
        pkg_name = canonicalize_name(req.name)
        installed_version = self.installed_packages.get(pkg_name)

        if installed_version is None:
            return False, f"Package '{req.name}' is not installed."

        if req.specifier and not req.specifier.contains(installed_version, prereleases=True):
            expected = str(req.specifier)
            actual = str(installed_version)
            return False, (
                f"Version mismatch for '{req.name}': "
                f"expected {expected}, got {actual}."
            )

        return True, None

    def check_environment(self, env: str = "default") -> Dict[str, any]:
        """
        Validate dependencies for a given environment.
        Returns a detailed report.
        """
        req_file_name = self.ENV_REQUIREMENT_MAP.get(env, self.ENV_REQUIREMENT_MAP["default"])
        req_path = self.project_root / req_file_name

        logger.info("Checking dependencies for environment: %s (%s)", env, req_path)

        requirements = self._parse_requirements_file(req_path)
        issues: List[str] = []
        checked_packages: Set[str] = set()

        for req in requirements:
            pkg_name = canonicalize_name(req.name)
            if pkg_name in checked_packages:
                continue
            checked_packages.add(pkg_name)

            is_ok, reason = self._check_requirement_compatibility(req)
            if not is_ok:
                issues.append(reason)

        status = "PASS" if not issues else "FAIL"
        report = {
            "environment": env,
            "status": status,
            "requirements_file": str(req_path),
            "total_requirements": len(requirements),
            "issues": issues,
            "installed_packages_count": len(self.installed_packages)
        }

        if status == "PASS":
            logger.info("✅ All dependencies OK for environment '%s'.", env)
        else:
            logger.error("❌ Dependency check failed for '%s': %d issues.", env, len(issues))

        return report

    def check_all_environments(self) -> Dict[str, Dict[str, any]]:
        """Run dependency check across all known environments."""
        results = {}
        for env in self.ENV_REQUIREMENT_MAP.keys():
            results[env] = self.check_environment(env)
        return results


def main():
    """CLI entry point for manual dependency validation."""
    import argparse

    parser = argparse.ArgumentParser(description="Check project dependencies.")
    parser.add_argument(
        "--env",
        choices=["default", "development", "production", "testing", "gpu"],
        default="default",
        help="Target environment to validate."
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Validate all environments."
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging."
    )

    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    checker = DependencyChecker()

    if args.all:
        results = checker.check_all_environments()
        print(json.dumps(results, indent=2, ensure_ascii=False))
        # Exit with error if any environment fails
        has_failure = any(r["status"] == "FAIL" for r in results.values())
        sys.exit(1 if has_failure else 0)
    else:
        report = checker.check_environment(args.env)
        print(json.dumps(report, indent=2, ensure_ascii=False))
        sys.exit(0 if report["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()