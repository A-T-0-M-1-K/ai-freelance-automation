# tools/testing/load_test.py
"""
Load testing tool for AI Freelance Automation System.
Simulates concurrent job processing, client communication, and payment operations
to validate system stability under high load.

Features:
- Configurable concurrency levels
- Realistic workflow simulation (bid → work → deliver → pay)
- Metrics collection (latency, throughput, error rate)
- Integration with monitoring system
- Safe execution (no real payments or platform actions in test mode)
"""

import asyncio
import logging
import time
import random
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
import json

# Core dependencies
from core.dependency.service_locator import ServiceLocator
from core.config.unified_config_manager import UnifiedConfigManager
from core.monitoring.intelligent_monitoring_system import IntelligentMonitoringSystem

# Services
from services.ai_services.transcription_service import TranscriptionService
from services.ai_services.translation_service import TranslationService
from services.ai_services.copywriting_service import CopywritingService
from services.notification.email_service import EmailService

# Mock platform clients (safe for testing)
from platforms.platform_factory import PlatformFactory

# Logging setup
logger = logging.getLogger("LoadTest")


@dataclass
class LoadTestResult:
    total_jobs: int
    successful_jobs: int
    failed_jobs: int
    avg_latency_sec: float
    p95_latency_sec: float
    throughput_jobs_per_min: float
    error_rate: float
    resource_usage: Dict[str, Any]


class LoadTester:
    """
    Orchestrates realistic load testing of the autonomous freelancer system.
    """

    def __init__(self, config: Optional[UnifiedConfigManager] = None):
        self.config = config or UnifiedConfigManager()
        self.test_config = self.config.get("performance.load_test", {})
        self.monitoring = IntelligentMonitoringSystem(self.config)
        self.service_locator = ServiceLocator()
        self.results: List[Dict[str, Any]] = []

    async def _initialize_services(self) -> None:
        """Initialize required services in safe (mocked) mode."""
        logger.info("🔧 Initializing services for load test...")

        # Register mock services to avoid real external calls
        self.service_locator.register(
            "transcription", TranscriptionService(config=self.config, test_mode=True)
        )
        self.service_locator.register(
            "translation", TranslationService(config=self.config, test_mode=True)
        )
        self.service_locator.register(
            "copywriting", CopywritingService(config=self.config, test_mode=True)
        )
        self.service_locator.register(
            "email", EmailService(config=self.config, test_mode=True)
        )

        # Use mock platform clients
        self.platforms = {
            name: PlatformFactory.create_platform(name, test_mode=True)
            for name in self.test_config.get("platforms", ["upwork", "freelance_ru"])
        }

        logger.info("✅ Services initialized in test mode.")

    async def _simulate_job_lifecycle(self, job_id: str, platform_name: str) -> Dict[str, Any]:
        """
        Simulate full job lifecycle: bid → accept → execute → deliver → payment.
        Returns timing and status metrics.
        """
        start_time = time.time()
        try:
            # 1. Simulate bidding
            await asyncio.sleep(random.uniform(0.1, 0.5))  # network delay

            # 2. Accept job
            await asyncio.sleep(0.05)

            # 3. Execute work (AI service)
            task_type = random.choice(["transcription", "translation", "copywriting"])
            service = self.service_locator.get(task_type)
            if service:
                await service.process({"job_id": job_id, "test_mode": True})

            # 4. Deliver result
            await asyncio.sleep(0.1)

            # 5. Simulate payment confirmation
            await asyncio.sleep(0.05)

            latency = time.time() - start_time
            return {
                "job_id": job_id,
                "status": "success",
                "latency": latency,
                "task_type": task_type,
                "platform": platform_name,
            }

        except Exception as e:
            latency = time.time() - start_time
            logger.warning(f"Job {job_id} failed during load test: {e}")
            return {
                "job_id": job_id,
                "status": "failed",
                "latency": latency,
                "error": str(e),
                "platform": platform_name,
            }

    async def run_test(self) -> LoadTestResult:
        """
        Run full load test based on configuration.
        Returns aggregated performance metrics.
        """
        logger.info("🚀 Starting load test...")

        await self._initialize_services()

        concurrency = self.test_config.get("concurrent_jobs", 10)
        total_jobs = self.test_config.get("total_jobs", 100)
        job_ids = [f"load_test_job_{i}" for i in range(total_jobs)]
        platforms = list(self.platforms.keys())

        start_timestamp = time.time()
        tasks = []

        for i, job_id in enumerate(job_ids):
            platform = random.choice(platforms)
            task = self._simulate_job_lifecycle(job_id, platform)
            tasks.append(task)

            # Throttle to control concurrency
            if (i + 1) % concurrency == 0:
                batch_results = await asyncio.gather(*tasks[-concurrency:], return_exceptions=True)
                self.results.extend([
                    r if not isinstance(r, Exception) else {"status": "crashed", "error": str(r)}
                    for r in batch_results
                ])

        # Handle remaining tasks
        if len(tasks) % concurrency != 0:
            remaining = tasks[-(len(tasks) % concurrency):]
            if remaining:
                batch_results = await asyncio.gather(*remaining, return_exceptions=True)
                self.results.extend([
                    r if not isinstance(r, Exception) else {"status": "crashed", "error": str(r)}
                    for r in batch_results
                ])

        duration_sec = time.time() - start_timestamp
        latencies = [r["latency"] for r in self.results if r.get("status") == "success"]
        successful = sum(1 for r in self.results if r.get("status") == "success")
        failed = len(self.results) - successful

        # Calculate metrics
        avg_latency = sum(latencies) / len(latencies) if latencies else 0
        p95_latency = sorted(latencies)[int(0.95 * len(latencies)) - 1] if latencies else 0
        throughput = (successful / duration_sec) * 60  # jobs per minute
        error_rate = failed / len(self.results) if self.results else 0

        # Resource usage (mocked; in real system would pull from monitoring)
        resource_usage = self.monitoring.get_current_resource_snapshot()

        result = LoadTestResult(
            total_jobs=len(self.results),
            successful_jobs=successful,
            failed_jobs=failed,
            avg_latency_sec=avg_latency,
            p95_latency_sec=p95_latency,
            throughput_jobs_per_min=throughput,
            error_rate=error_rate,
            resource_usage=resource_usage,
        )

        logger.info(f"✅ Load test completed. Success: {successful}/{total_jobs}")
        logger.info(f"📊 Avg latency: {avg_latency:.2f}s | Throughput: {throughput:.1f} jobs/min")

        # Save results to file
        self._save_results(result)

        return result

    def _save_results(self, result: LoadTestResult) -> None:
        """Save test results to logs and data directory."""
        output_path = "data/stats/load_test_results.json"
        try:
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(asdict(result), f, indent=2, ensure_ascii=False)
            logger.info(f"💾 Load test results saved to {output_path}")
        except Exception as e:
            logger.error(f"Failed to save load test results: {e}")


# CLI entry point (optional)
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)

    try:
        tester = LoadTester()
        asyncio.run(tester.run_test())
    except KeyboardInterrupt:
        logger.info("⏹️ Load test interrupted by user.")
        sys.exit(0)
    except Exception as e:
        logger.critical(f"💥 Load test failed: {e}", exc_info=True)
        sys.exit(1)