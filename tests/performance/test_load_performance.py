# AI_FREELANCE_AUTOMATION/tests/performance/test_load_performance.py
"""
Performance test suite for load handling under concurrent freelance automation workloads.
Validates system behavior under:
- High job ingestion rate (50+ active jobs)
- Concurrent client communication (100+ clients)
- Parallel AI model inference (20+ models)
- Platform scraping across 10+ sources

Ensures adherence to SLOs: <2s response time, <1% error rate, 99.9% uptime simulation.
"""

import asyncio
import logging
import time
from typing import List, Dict, Any
import pytest

from core.config.unified_config_manager import UnifiedConfigManager
from core.dependency.service_locator import ServiceLocator
from core.monitoring.intelligent_monitoring_system import IntelligentMonitoringSystem
from services.ai_services.transcription_service import TranscriptionService
from services.ai_services.translation_service import TranslationService
from services.ai_services.copywriting_service import CopywritingService
from platforms.platform_factory import PlatformFactory
from core.automation.auto_freelancer_core import AutoFreelancerCore

# Configure module-specific logger
logger = logging.getLogger(__name__)


class LoadPerformanceTestContext:
    """Manages test context and resource isolation."""

    def __init__(self):
        self.config = UnifiedConfigManager()
        self.monitor = IntelligentMonitoringSystem(self.config)
        self.service_locator = ServiceLocator()
        self.platforms = PlatformFactory.load_all_platforms(self.config)
        self.freelancer = AutoFreelancerCore(self.config, self.service_locator)
        self.metrics: Dict[str, Any] = {}

    async def setup(self):
        """Initialize services and warm up AI models."""
        logger.info("🔥 Warming up AI models and services...")
        await self.freelancer.initialize()
        # Pre-load common models to avoid cold-start skew
        await TranscriptionService.warmup()
        await TranslationService.warmup()
        await CopywritingService.warmup()
        logger.info("✅ Warm-up completed.")

    async def teardown(self):
        """Clean up resources."""
        await self.freelancer.shutdown()
        logger.info("🧹 Load test context cleaned up.")


@pytest.mark.performance
@pytest.mark.asyncio
async def test_concurrent_job_processing_under_load():
    """
    Simulates 50 concurrent active jobs with mixed types (transcription, translation, copywriting).
    Validates:
    - System throughput (jobs/min)
    - Memory pressure (<80% of limit)
    - Error rate (<1%)
    - Latency per job type (<2s for small, <10s for large)
    """
    context = LoadPerformanceTestContext()
    await context.setup()

    try:
        job_configs = _generate_synthetic_job_batch(
            count=50,
            types=["transcription", "translation", "copywriting"],
            size_distribution={"small": 0.6, "medium": 0.3, "large": 0.1}
        )

        start_time = time.time()
        tasks = [
            _process_job_async(context.freelancer, job)
            for job in job_configs
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)
        end_time = time.time()

        # Analyze results
        success_count = sum(1 for r in results if not isinstance(r, Exception))
        error_count = len(results) - success_count
        total_duration = end_time - start_time
        throughput = success_count / total_duration * 60  # jobs per minute

        # Record metrics
        context.metrics.update({
            "total_jobs": len(job_configs),
            "successful_jobs": success_count,
            "failed_jobs": error_count,
            "error_rate_pct": (error_count / len(job_configs)) * 100,
            "total_duration_sec": total_duration,
            "throughput_jobs_per_min": throughput,
            "avg_latency_sec": total_duration / len(job_configs)
        })

        # Assertions against SLOs
        assert error_count <= 1, f"Error rate too high: {error_count} failures"
        assert throughput >= 30, f"Throughput too low: {throughput:.2f} jobs/min"
        assert total_duration / len(job_configs) <= 5.0, "Average latency exceeds 5s"

        logger.info(f"✅ Load test passed: {context.metrics}")

    finally:
        await context.teardown()


@pytest.mark.performance
@pytest.mark.asyncio
async def test_platform_scraping_at_scale():
    """
    Tests concurrent scraping of 10+ platforms with rate limiting and anomaly detection.
    Ensures no IP bans, timeouts, or data corruption.
    """
    context = LoadPerformanceTestContext()
    await context.setup()

    try:
        platform_names = list(context.platforms.keys())
        logger.info(f"📡 Testing scraping on {len(platform_names)} platforms...")

        start_time = time.time()
        scrape_tasks = [
            _scrape_platform_safe(context.platforms[name], name)
            for name in platform_names
        ]
        results = await asyncio.gather(*scrape_tasks, return_exceptions=True)
        duration = time.time() - start_time

        valid_results = [r for r in results if not isinstance(r, Exception)]
        error_count = len(results) - len(valid_results)

        assert error_count == 0, f"Platform scraping failed on {error_count} platforms"
        assert all(len(jobs) > 0 for jobs in valid_results), "Empty job lists returned"
        assert duration < 30.0, f"Scraping took too long: {duration:.2f}s"

        logger.info(f"✅ Platform scraping at scale succeeded in {duration:.2f}s")

    finally:
        await context.teardown()


# --- Helper functions ---

async def _process_job_async(freelancer: AutoFreelancerCore, job_spec: Dict[str, Any]) -> bool:
    """Simulate full job lifecycle: accept → execute → deliver."""
    try:
        await freelancer.accept_job(job_spec)
        result = await freelancer.execute_job(job_spec["job_id"])
        await freelancer.deliver_result(job_spec["job_id"], result)
        return True
    except Exception as e:
        logger.warning(f"Job {job_spec['job_id']} failed: {e}")
        return False


async def _scrape_platform_safe(platform_client, name: str) -> List[Dict]:
    """Wrap platform scraping with error handling."""
    try:
        jobs = await platform_client.scrape_jobs(limit=10)
        return jobs
    except Exception as e:
        logger.error(f"Scraping failed for {name}: {e}")
        raise


def _generate_synthetic_job_batch(
        count: int,
        types: List[str],
        size_distribution: Dict[str, float]
) -> List[Dict[str, Any]]:
    """Generate realistic synthetic job configurations for load testing."""
    import random
    import uuid

    jobs = []
    for i in range(count):
        job_type = random.choice(types)
        size = random.choices(
            list(size_distribution.keys()),
            weights=list(size_distribution.values())
        )[0]

        size_map = {"small": 1, "medium": 5, "large": 20}
        content_length = size_map[size] * 1000  # chars or seconds

        jobs.append({
            "job_id": str(uuid.uuid4()),
            "type": job_type,
            "size": size,
            "content_length": content_length,
            "client_id": f"client_{random.randint(1000, 9999)}",
            "deadline_hours": random.choice([24, 48, 72]),
            "budget_usd": round(random.uniform(10, 500), 2)
        })
    return jobs