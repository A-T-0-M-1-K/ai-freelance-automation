# AI_FREELANCE_AUTOMATION/scripts/tools/benchmark.py
"""
Performance Benchmarking Tool for AI Freelance Automation System.

Purpose:
- Measure latency, throughput, memory usage, and accuracy of core components.
- Validate system performance against SLA thresholds (e.g., 99.9% uptime, <2s response).
- Support self-optimization by feeding metrics into the auto-scaler and model optimizer.
- Run as standalone script or as part of health monitoring / CI pipeline.

Design Principles:
- Zero side effects: does not modify production state.
- Thread-safe and async-compatible.
- Uses only standard interfaces from core/ to avoid tight coupling.
- Logs all results via audit_logger for traceability.
- Respects config-driven thresholds and resource limits.
"""

import asyncio
import time
import tracemalloc
import psutil
import logging
import json
from pathlib import Path
from typing import Dict, Any, Callable, Optional, List
from datetime import datetime

# Local imports via relative paths (safe for scripts/)
try:
    from core.config.unified_config_manager import UnifiedConfigManager
    from core.security.audit_logger import AuditLogger
    from core.monitoring.intelligent_monitor import IntelligentMonitor
except ImportError as e:
    # Fallback for isolated execution (e.g., CI)
    logging.warning(f"Core modules not available in isolated mode: {e}")
    UnifiedConfigManager = None
    AuditLogger = None
    IntelligentMonitor = None

# Configure module-specific logger
logger = logging.getLogger("BenchmarkTool")


class ComponentBenchmarkResult:
    """Immutable result container for a single benchmark run."""
    def __init__(
        self,
        component_name: str,
        duration_sec: float,
        memory_kb: float,
        cpu_percent: float,
        custom_metrics: Optional[Dict[str, Any]] = None,
        success: bool = True,
        error: Optional[str] = None
    ):
        self.component_name = component_name
        self.duration_sec = duration_sec
        self.memory_kb = memory_kb
        self.cpu_percent = cpu_percent
        self.custom_metrics = custom_metrics or {}
        self.success = success
        self.error = error
        self.timestamp = datetime.utcnow().isoformat() + "Z"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "component_name": self.component_name,
            "timestamp": self.timestamp,
            "duration_sec": self.duration_sec,
            "memory_kb": self.memory_kb,
            "cpu_percent": self.cpu_percent,
            "custom_metrics": self.custom_metrics,
            "success": self.success,
            "error": self.error
        }

    def __repr__(self):
        status = "✅" if self.success else "❌"
        return f"{status} {self.component_name}: {self.duration_sec:.3f}s | {self.memory_kb:.1f}KB"


class BenchmarkSuite:
    """
    Orchestrates benchmarking of multiple system components.
    Designed to be used by health_monitor.py or auto_scaler.py during diagnostics.
    """

    def __init__(
        self,
        config_manager: Optional[Any] = None,
        audit_logger: Optional[Any] = None
    ):
        self.config = config_manager or self._load_default_config()
        self.audit_logger = audit_logger or self._get_fallback_logger()
        self.results: List[ComponentBenchmarkResult] = []

    def _load_default_config(self) -> Dict[str, Any]:
        """Fallback config if core is unavailable."""
        return {
            "benchmark": {
                "timeout_sec": 30,
                "memory_limit_mb": 1024,
                "max_cpu_percent": 80.0,
                "output_dir": "logs/benchmarks"
            }
        }

    def _get_fallback_logger(self) -> Any:
        """Fallback audit logger."""
        class FallbackLogger:
            def log(self, level: str, message: str, **kwargs):
                logger.log(getattr(logging, level.upper(), logging.INFO), f"[AUDIT] {message}")
        return FallbackLogger()

    async def benchmark_component(
        self,
        name: str,
        func: Callable,
        *args,
        **kwargs
    ) -> ComponentBenchmarkResult:
        """
        Benchmark a single async or sync function.
        Automatically captures time, memory, and CPU.
        """
        # Start resource tracking
        process = psutil.Process()
        tracemalloc.start()
        start_time = time.time()
        start_cpu = process.cpu_percent()

        try:
            # Execute function
            if asyncio.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)

            success = True
            error_msg = None
            custom_metrics = getattr(result, 'benchmark_metrics', {}) if hasattr(result, 'benchmark_metrics') else {}

        except Exception as e:
            success = False
            error_msg = str(e)
            custom_metrics = {}
            logger.error(f"Benchmark failed for {name}: {e}", exc_info=True)

        finally:
            duration = time.time() - start_time
            current, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            end_cpu = process.cpu_percent()

        mem_kb = peak / 1024  # Convert bytes to KB
        cpu_avg = (start_cpu + end_cpu) / 2

        result_obj = ComponentBenchmarkResult(
            component_name=name,
            duration_sec=duration,
            memory_kb=mem_kb,
            cpu_percent=cpu_avg,
            custom_metrics=custom_metrics,
            success=success,
            error=error_msg
        )

        self.results.append(result_obj)
        self.audit_logger.log("INFO", "Benchmark completed", component=name, result=result_obj.to_dict())
        return result_obj

    def save_results(self, output_path: Optional[str] = None) -> Path:
        """Save all benchmark results to JSON file."""
        if not output_path:
            output_dir = Path(self.config["benchmark"]["output_dir"])
            output_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            output_path = output_dir / f"benchmark_run_{timestamp}.json"

        data = {
            "run_timestamp": datetime.utcnow().isoformat() + "Z",
            "results": [r.to_dict() for r in self.results]
        }

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        logger.info(f"📊 Benchmark results saved to: {output_path}")
        return Path(output_path)

    def check_sla_compliance(self) -> bool:
        """Check if all benchmarks meet SLA thresholds."""
        cfg = self.config["benchmark"]
        violations = []

        for res in self.results:
            if res.duration_sec > cfg.get("timeout_sec", 30):
                violations.append(f"{res.component_name}: timeout ({res.duration_sec:.2f}s)")
            if res.memory_kb > cfg.get("memory_limit_mb", 1024) * 1024:
                violations.append(f"{res.component_name}: memory exceeded")
            if res.cpu_percent > cfg.get("max_cpu_percent", 80.0):
                violations.append(f"{res.component_name}: CPU overload")

        if violations:
            logger.warning("⚠️ SLA violations detected:\n" + "\n".join(violations))
            return False
        else:
            logger.info("✅ All benchmarks within SLA limits.")
            return True


# === Standalone Execution Entry Point ===
async def _run_sample_benchmarks():
    """Example usage — can be replaced with real component calls."""
    suite = BenchmarkSuite()

    # Simulate AI inference
    async def mock_transcription():
        await asyncio.sleep(0.5)
        return type('obj', (), {'benchmark_metrics': {'accuracy': 0.98, 'tokens': 1200}})()

    # Simulate communication
    def mock_client_message():
        time.sleep(0.1)
        return {"sentiment": "positive", "response_time": 0.09}

    await suite.benchmark_component("transcription_service", mock_transcription)
    await suite.benchmark_component("intelligent_communicator", mock_client_message)

    suite.save_results()
    suite.check_sla_compliance()


if __name__ == "__main__":
    # Allow direct execution for testing
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_run_sample_benchmarks())