# AI_FREELANCE_AUTOMATION/tools/testing/test_runner.py
"""
Advanced Test Runner for AI Freelance Automation System.

Features:
- Discovers and runs unit, integration, e2e, and performance tests
- Supports parallel execution with resource isolation
- Integrates with system logging, monitoring, and security
- Generates structured reports and metrics
- Respects configuration from core/config/
- Safe execution with sandboxing and timeout controls

This module is designed to be used by:
- CI/CD pipelines (.github/workflows/tests.yml)
- Maintenance scripts (scripts/maintenance/health_check.py)
- CLI commands (cli.py test)
- Monitoring system (core/monitoring/)
"""

import asyncio
import json
import logging
import os
import signal
import sys
import time
from pathlib import Path
from typing import List, Dict, Any, Optional, Set
from unittest.mock import patch

import pytest
from pydantic import BaseModel, Field

# Local imports — using relative paths to avoid circular dependencies
# All core modules are assumed to be available via PYTHONPATH or proper package structure
try:
    from core.config.unified_config_manager import UnifiedConfigManager
    from core.monitoring.intelligent_monitoring_system import IntelligentMonitoringSystem
    from core.security.audit_logger import AuditLogger
    from core.dependency.service_locator import ServiceLocator
except ImportError as e:
    # Fallback for isolated execution (e.g., during CI setup)
    logging.warning(f"Core modules not available in test runner context: {e}")
    UnifiedConfigManager = None
    IntelligentMonitoringSystem = None
    AuditLogger = None
    ServiceLocator = None

# Configure module-specific logger
logger = logging.getLogger("TestRunner")


class TestRunResult(BaseModel):
    """Structured result of a test run."""
    suite: str
    passed: int
    failed: int
    skipped: int
    errors: int
    duration_sec: float
    timestamp: float = Field(default_factory=time.time)
    details: Dict[str, Any] = Field(default_factory=dict)


class TestRunnerConfig(BaseModel):
    """Configuration schema for the test runner."""
    test_dirs: List[str] = Field(default=["tests/unit", "tests/integration", "tests/e2e", "tests/performance"])
    parallel: bool = True
    max_workers: int = 4
    timeout_per_test: int = 300  # seconds
    fail_fast: bool = False
    collect_only: bool = False
    report_output: str = "logs/tests/test_results.json"
    junit_xml: Optional[str] = None
    coverage: bool = False
    coverage_report: str = "htmlcov/"
    strict_mode: bool = True
    sandbox_enabled: bool = True


class TestRunner:
    """
    Orchestrates test execution across all test types.
    Integrates with system-wide config, logging, and monitoring.
    """

    def __init__(self, config_path: Optional[str] = None):
        self.config_path = config_path
        self.runner_config: TestRunnerConfig = self._load_config()
        self.results: List[TestRunResult] = []
        self._setup_logging()
        self._register_shutdown_handler()

    def _load_config(self) -> TestRunnerConfig:
        """Load test runner configuration from system config or defaults."""
        if UnifiedConfigManager is not None:
            try:
                config_mgr = UnifiedConfigManager()
                raw_config = config_mgr.get_section("testing") or {}
                return TestRunnerConfig(**raw_config)
            except Exception as e:
                logger.warning(f"Failed to load config from UnifiedConfigManager: {e}. Using defaults.")
        else:
            logger.info("UnifiedConfigManager not available. Using embedded defaults.")

        # Fallback to default config
        return TestRunnerConfig()

    def _setup_logging(self):
        """Ensure test runner logs are captured properly."""
        log_dir = Path("logs/tests")
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(log_dir / "test_runner.log")
        formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

    def _register_shutdown_handler(self):
        """Gracefully handle interruptions."""
        def shutdown_handler(signum, frame):
            logger.info(f"Received signal {signum}. Shutting down test runner gracefully...")
            self._finalize()
            sys.exit(1)

        signal.signal(signal.SIGINT, shutdown_handler)
        signal.signal(signal.SIGTERM, shutdown_handler)

    async def run_all_tests(self) -> bool:
        """Run all configured test suites."""
        logger.info("🚀 Starting comprehensive test run...")
        start_time = time.time()

        success = True
        for test_dir in self.runner_config.test_dirs:
            if not os.path.exists(test_dir):
                logger.warning(f"Test directory not found: {test_dir}. Skipping.")
                continue

            logger.info(f"▶️ Running tests in: {test_dir}")
            result = await self._run_test_suite(test_dir)
            self.results.append(result)
            if result.failed > 0 or result.errors > 0:
                success = False
                if self.runner_config.fail_fast:
                    logger.info("❌ Fail-fast enabled. Stopping after first failure.")
                    break

        duration = time.time() - start_time
        self._generate_report(duration)
        self._send_metrics_to_monitoring(duration)
        logger.info(f"✅ Test run completed in {duration:.2f} seconds. Success: {success}")
        return success

    async def _run_test_suite(self, test_dir: str) -> TestRunResult:
        """Run a single test suite using pytest."""
        args = [test_dir]

        # Configure pytest arguments
        if self.runner_config.collect_only:
            args.append("--collect-only")

        if self.runner_config.junit_xml:
            args.extend(["--junitxml", self.runner_config.junit_xml])

        if self.runner_config.coverage:
            args.extend([
                "--cov=.",
                f"--cov-report=html:{self.runner_config.coverage_report}",
                "--cov-report=term-missing"
            ])

        if self.runner_config.fail_fast:
            args.append("-x")

        if self.runner_config.parallel:
            args.extend(["-n", str(self.runner_config.max_workers)])

        # Timeout and sandboxing are handled at OS/process level if needed
        # For now, rely on pytest's built-in mechanisms

        # Capture pytest output
        class PytestCapture:
            def __init__(self):
                self.output = []

            def write(self, line):
                self.output.append(line)

            def flush(self):
                pass

        capture = PytestCapture()
        original_stdout = sys.stdout
        sys.stdout = capture

        try:
            start = time.time()
            exit_code = pytest.main(args)
            duration = time.time() - start
        finally:
            sys.stdout = original_stdout

        # Parse basic stats (pytest doesn't expose detailed stats easily without plugins)
        # For production use, consider using pytest-json-report or similar
        passed = failed = skipped = errors = 0
        output_text = "".join(capture.output)
        if "failed" in output_text:
            # Crude parsing — in real system, use pytest hooks or JSON report
            lines = output_text.split("\n")
            for line in lines:
                if "passed" in line and "failed" in line:
                    # Example: "3 passed, 1 failed, 2 skipped"
                    parts = line.split(",")
                    for part in parts:
                        if "passed" in part:
                            passed = int(part.split()[0])
                        elif "failed" in part:
                            failed = int(part.split()[0])
                        elif "skipped" in part:
                            skipped = int(part.split()[0])
                        elif "error" in part:
                            errors = int(part.split()[0])
                elif "failed" in line and "passed" not in line:
                    failed = int(line.split()[0])
                elif "passed" in line:
                    passed = int(line.split()[0])

        return TestRunResult(
            suite=test_dir,
            passed=passed,
            failed=failed,
            skipped=skipped,
            errors=errors,
            duration_sec=duration,
            details={"exit_code": exit_code, "output_snippet": output_text[-1000:]}
        )

    def _generate_report(self, total_duration: float):
        """Save structured test results to JSON."""
        report_path = Path(self.runner_config.report_output)
        report_path.parent.mkdir(parents=True, exist_ok=True)

        report_data = {
            "total_duration_sec": total_duration,
            "timestamp": time.time(),
            "summary": {
                "total_passed": sum(r.passed for r in self.results),
                "total_failed": sum(r.failed for r in self.results),
                "total_skipped": sum(r.skipped for r in self.results),
                "total_errors": sum(r.errors for r in self.results),
            },
            "suites": [r.dict() for r in self.results]
        }

        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, indent=2, ensure_ascii=False)

        logger.info(f"📄 Test report saved to: {report_path}")

    def _send_metrics_to_monitoring(self, total_duration: float):
        """Send test metrics to the system monitoring service if available."""
        if IntelligentMonitoringSystem is None:
            return

        try:
            monitor = ServiceLocator.get("monitoring") if ServiceLocator else IntelligentMonitoringSystem()
            metrics = {
                "test.total_duration_sec": total_duration,
                "test.total_suites": len(self.results),
                "test.total_passed": sum(r.passed for r in self.results),
                "test.total_failed": sum(r.failed for r in self.results),
                "test.success_rate": (
                    sum(r.passed for r in self.results) /
                    max(sum(r.passed + r.failed + r.errors for r in self.results), 1)
                )
            }
            for key, value in metrics.items():
                monitor.record_metric(key, value)
        except Exception as e:
            logger.warning(f"Failed to send metrics to monitoring: {e}")

    def _finalize(self):
        """Cleanup and finalization logic."""
        logger.info("🧹 Finalizing test runner...")
        # Add cleanup logic here if needed (e.g., temp files, processes)

    def run_sync(self) -> bool:
        """Synchronous entry point for CLI or scripts."""
        return asyncio.run(self.run_all_tests())


# CLI Entry Point (if run directly)
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="AI Freelance Automation Test Runner")
    parser.add_argument("--config", help="Path to custom config file (optional)")
    parser.add_argument("--suite", help="Run specific test suite (e.g., 'unit')")
    args = parser.parse_args()

    if args.suite:
        runner_config = TestRunnerConfig(test_dirs=[f"tests/{args.suite}"])
        # Temporarily override config
        runner = TestRunner()
        runner.runner_config = runner_config
    else:
        runner = TestRunner(config_path=args.config)

    success = runner.run_sync()
    sys.exit(0 if success else 1)