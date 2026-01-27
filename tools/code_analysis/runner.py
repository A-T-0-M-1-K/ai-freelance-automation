# AI_FREELANCE_AUTOMATION/tools/code_analysis/runner.py
"""
Code Analysis Runner — executes all static analysis tools in the project.
Used by self-healing, CI/CD, and maintenance scripts to ensure code quality,
security, and maintainability.

Integrates with:
- core/monitoring/
- logs/errors/
- tools/code_analysis/security_scan.py
- tools/code_analysis/complexity_check.py
- tools/code_analysis/lint_rules.py
"""

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime

# Add project root to path for relative imports (if needed in standalone mode)
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Local imports (relative to project structure)
try:
    from tools.code_analysis.security_scan import SecurityScanner
    from tools.code_analysis.complexity_check import ComplexityAnalyzer
    from tools.code_analysis.lint_rules import Linter
except ImportError as e:
    raise ImportError(
        "Failed to import code analysis modules. "
        "Ensure you're running from project root or PYTHONPATH is set correctly."
    ) from e

# Configure module-specific logger
logger = logging.getLogger("CodeAnalysisRunner")


class CodeAnalysisRunner:
    """
    Orchestrates execution of multiple static analysis tools.
    Produces a unified report compatible with monitoring and self-repair systems.
    """

    def __init__(
        self,
        target_dirs: Optional[List[str]] = None,
        config_path: Optional[str] = None,
        enable_security: bool = True,
        enable_complexity: bool = True,
        enable_linting: bool = True,
    ):
        self.target_dirs = target_dirs or [
            "core",
            "services",
            "platforms",
            "ai",
            "tools",
            "plugins",
        ]
        self.config_path = config_path or str(PROJECT_ROOT / "tools" / "code_analysis" / "config.json")
        self.enable_security = enable_security
        self.enable_complexity = enable_complexity
        self.enable_linting = enable_linting
        self.results: Dict[str, Any] = {}
        self._load_config()

    def _load_config(self):
        """Load analysis configuration."""
        if os.path.exists(self.config_path):
            with open(self.config_path, "r", encoding="utf-8") as f:
                self.config = json.load(f)
        else:
            # Fallback defaults
            self.config = {
                "exclude_patterns": ["__pycache__", ".git", "logs", "backup", "venv", ".venv", "node_modules"],
                "max_cyclomatic_complexity": 15,
                "security_rules": ["B101", "B301", "B404"],
                "lint_rules": ["E", "W", "F"],
            }
        logger.info(f"Loaded code analysis config from {self.config_path}")

    async def run_security_scan(self) -> Dict[str, Any]:
        """Run security vulnerability scanner."""
        if not self.enable_security:
            return {"skipped": True}
        try:
            scanner = SecurityScanner(
                paths=[str(PROJECT_ROOT / d) for d in self.target_dirs],
                rules=self.config.get("security_rules", []),
                exclude=self.config.get("exclude_patterns", [])
            )
            result = await scanner.analyze()
            logger.info("✅ Security scan completed")
            return result
        except Exception as e:
            logger.error(f"❌ Security scan failed: {e}", exc_info=True)
            return {"error": str(e), "success": False}

    async def run_complexity_analysis(self) -> Dict[str, Any]:
        """Run code complexity analyzer."""
        if not self.enable_complexity:
            return {"skipped": True}
        try:
            analyzer = ComplexityAnalyzer(
                paths=[str(PROJECT_ROOT / d) for d in self.target_dirs],
                max_complexity=self.config.get("max_cyclomatic_complexity", 15),
                exclude=self.config.get("exclude_patterns", [])
            )
            result = await analyzer.analyze()
            logger.info("✅ Complexity analysis completed")
            return result
        except Exception as e:
            logger.error(f"❌ Complexity analysis failed: {e}", exc_info=True)
            return {"error": str(e), "success": False}

    async def run_linting(self) -> Dict[str, Any]:
        """Run code linter."""
        if not self.enable_linting:
            return {"skipped": True}
        try:
            linter = Linter(
                paths=[str(PROJECT_ROOT / d) for d in self.target_dirs],
                rules=self.config.get("lint_rules", ["E", "W", "F"]),
                exclude=self.config.get("exclude_patterns", [])
            )
            result = await linter.analyze()
            logger.info("✅ Linting completed")
            return result
        except Exception as e:
            logger.error(f"❌ Linting failed: {e}", exc_info=True)
            return {"error": str(e), "success": False}

    async def run_all(self) -> Dict[str, Any]:
        """Run all enabled analyzers concurrently."""
        logger.info("🔍 Starting full code analysis...")
        start_time = datetime.utcnow()

        tasks = []
        if self.enable_security:
            tasks.append(("security", self.run_security_scan()))
        if self.enable_complexity:
            tasks.append(("complexity", self.run_complexity_analysis()))
        if self.enable_linting:
            tasks.append(("linting", self.run_linting()))

        results = await asyncio.gather(*[task for _, task in tasks], return_exceptions=True)

        # Map results back to names
        self.results = {}
        for i, (name, _) in enumerate(tasks):
            if isinstance(results[i], Exception):
                self.results[name] = {"error": str(results[i]), "success": False}
                logger.error(f"💥 Analyzer '{name}' crashed: {results[i]}")
            else:
                self.results[name] = results[i]

        duration = (datetime.utcnow() - start_time).total_seconds()
        self.results["metadata"] = {
            "timestamp": start_time.isoformat() + "Z",
            "duration_seconds": duration,
            "target_dirs": self.target_dirs,
            "project_root": str(PROJECT_ROOT),
            "overall_success": all(
                r.get("success", True) and not r.get("error")
                for r in self.results.values()
                if not r.get("skipped")
            ),
        }

        logger.info(f"✅ Full code analysis finished in {duration:.2f}s")
        return self.results

    def save_report(self, output_path: Optional[str] = None) -> str:
        """Save analysis report to JSON file."""
        if not self.results:
            raise ValueError("No analysis results to save. Run run_all() first.")

        output_dir = Path(output_path or PROJECT_ROOT / "logs" / "errors")
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        report_path = output_dir / f"code_analysis_{timestamp}.json"

        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(self.results, f, indent=2, ensure_ascii=False)

        logger.info(f"📄 Report saved to {report_path}")
        return str(report_path)

    def has_critical_issues(self) -> bool:
        """Check if any analyzer reported critical issues."""
        for name, result in self.results.items():
            if result.get("skipped"):
                continue
            if result.get("error"):
                return True
            # Example: security scanner might flag high-sev issues
            if name == "security" and result.get("high_severity_count", 0) > 0:
                return True
            # Example: complexity too high
            if name == "complexity" and result.get("functions_over_threshold", 0) > 0:
                return True
            # Example: linting errors
            if name == "linting" and result.get("error_count", 0) > 0:
                return True
        return False


# Standalone execution support
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    runner = CodeAnalysisRunner()
    asyncio.run(runner.run_all())
    runner.save_report()
    if runner.has_critical_issues():
        logger.error("🚨 Critical code issues detected! Halting deployment.")
        sys.exit(1)
    else:
        logger.info("✅ No critical issues found. Code is safe to deploy.")
        sys.exit(0)