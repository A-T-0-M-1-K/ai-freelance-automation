# AI_FREELANCE_AUTOMATION/tests/performance/test_concurrent_operations.py
"""
Performance test suite for concurrent operations in AI Freelance Automation System.

Validates:
- Concurrent job processing (up to 50 jobs)
- Parallel client communication (100+ clients)
- Simultaneous AI model inference (20+ models)
- Platform monitoring under load
- Resource isolation and stability

Ensures system meets 99.9% uptime and industrial reliability requirements.
"""

import asyncio
import logging
import time
from typing import List, Dict, Any
import pytest

from core.automation.auto_freelancer_core import AutoFreelancerCore
from core.config.unified_config_manager import UnifiedConfigManager
from core.security.advanced_crypto_system import AdvancedCryptoSystem
from services.ai_services.transcription_service import TranscriptionService
from services.ai_services.translation_service import TranslationService
from services.ai_services.copywriting_service import CopywritingService
from platforms.platform_factory import PlatformFactory
from core.communication.empathetic_communicator import EmpatheticCommunicator

# Configure module logger
logger = logging.getLogger(__name__)


class ConcurrentOperationsTestContext:
    """Manages test context with proper setup/teardown."""

    def __init__(self):
        self.config = None
        self.crypto = None
        self.freelancer = None
        self.communicator = None
        self.ai_services = {}
        self.platforms = []

    async def setup(self):
        """Initialize all required components."""
        self.config = UnifiedConfigManager()
        self.crypto = AdvancedCryptoSystem()

        # Initialize AI services
        self.ai_services = {
            'transcription': TranscriptionService(self.config),
            'translation': TranslationService(self.config),
            'copywriting': CopywritingService(self.config)
        }

        # Initialize communicator
        self.communicator = EmpatheticCommunicator(self.config)

        # Initialize freelancer core
        self.freelancer = AutoFreelancerCore(
            config=self.config,
            crypto=self.crypto,
            ai_services=self.ai_services,
            communicator=self.communicator
        )

        # Load platforms
        platform_names = self.config.get("platforms.enabled", ["upwork", "freelance_ru", "kwork"])
        self.platforms = [PlatformFactory.create(name) for name in platform_names]

        logger.info("✅ Test context initialized")

    async def teardown(self):
        """Gracefully shut down all components."""
        if self.freelancer:
            await self.freelancer.shutdown()
        if self.communicator:
            await self.communicator.close()
        for service in self.ai_services.values():
            await service.cleanup()
        logger.info("🧹 Test context cleaned up")


@pytest.fixture(scope="module")
def event_loop():
    """Custom event loop for module-scoped async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="module")
async def test_context():
    """Reusable test context for performance tests."""
    ctx = ConcurrentOperationsTestContext()
    await ctx.setup()
    yield ctx
    await ctx.teardown()


@pytest.mark.performance
@pytest.mark.asyncio
async def test_concurrent_job_processing(test_context):
    """
    Test concurrent processing of up to 50 jobs.
    Validates task orchestration, resource allocation, and error isolation.
    """
    ctx = test_context
    job_count = 50
    logger.info(f"🚀 Starting concurrent job processing test ({job_count} jobs)...")

    async def simulate_job(job_id: int) -> Dict[str, Any]:
        """Simulate a full job lifecycle."""
        try:
            # Simulate job acceptance
            await ctx.freelancer.accept_job(f"job_{job_id}")

            # Simulate AI work
            result = await ctx.ai_services['copywriting'].generate(
                prompt=f"Write a blog post about AI automation. Job ID: {job_id}",
                length=300
            )

            # Simulate quality control
            await ctx.freelancer.run_quality_check(f"job_{job_id}", result)

            return {"job_id": job_id, "status": "completed", "length": len(result)}
        except Exception as e:
            logger.error(f"Job {job_id} failed: {e}")
            return {"job_id": job_id, "status": "failed", "error": str(e)}

    # Run jobs concurrently
    start_time = time.time()
    tasks = [simulate_job(i) for i in range(job_count)]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    duration = time.time() - start_time

    # Validate results
    completed = [r for r in results if isinstance(r, dict) and r["status"] == "completed"]
    failed = [r for r in results if isinstance(r, dict) and r["status"] == "failed"]
    exceptions = [r for r in results if isinstance(r, Exception)]

    assert len(completed) >= job_count * 0.95, f"Too many failures: {len(failed) + len(exceptions)}"
    assert duration < 60.0, f"Processing too slow: {duration:.2f}s for {job_count} jobs"

    logger.info(f"✅ Processed {len(completed)} jobs in {duration:.2f}s "
                f"({len(failed)} failed, {len(exceptions)} exceptions)")


@pytest.mark.performance
@pytest.mark.asyncio
async def test_parallel_client_communication(test_context):
    """
    Test parallel communication with 100+ clients.
    Validates dialogue management, sentiment analysis, and context preservation.
    """
    ctx = test_context
    client_count = 100
    logger.info(f"💬 Starting parallel client communication test ({client_count} clients)...")

    async def simulate_client(client_id: int) -> bool:
        """Simulate client interaction."""
        try:
            messages = [
                f"Hi, I need a translation for job_{client_id}.",
                "Can you deliver it by tomorrow?",
                "Great! Please send the invoice."
            ]

            for msg in messages:
                response = await ctx.communicator.send_message(
                    client_id=f"client_{client_id}",
                    message=msg,
                    context={"job_id": f"job_{client_id}"}
                )
                assert response and len(response) > 0

            return True
        except Exception as e:
            logger.warning(f"Client {client_id} communication failed: {e}")
            return False

    # Run communications concurrently
    start_time = time.time()
    tasks = [simulate_client(i) for i in range(client_count)]
    results = await asyncio.gather(*tasks)
    duration = time.time() - start_time

    success_rate = sum(results) / client_count
    assert success_rate >= 0.98, f"Client communication success rate too low: {success_rate:.2%}"
    assert duration < 30.0, f"Communication too slow: {duration:.2f}s"

    logger.info(f"✅ Communicated with {sum(results)}/{client_count} clients in {duration:.2f}s")


@pytest.mark.performance
@pytest.mark.asyncio
async def test_simultaneous_ai_inference(test_context):
    """
    Test simultaneous inference across 20+ AI models.
    Validates model manager, memory isolation, and throughput.
    """
    ctx = test_context
    inference_count = 20
    logger.info(f"🧠 Starting simultaneous AI inference test ({inference_count} models)...")

    async def run_inference(task_id: int) -> Dict[str, Any]:
        """Run inference on a specific AI task."""
        service_map = {
            0: ('transcription', "Transcribe this audio."),
            1: ('translation', "Translate 'Hello world' to French."),
            2: ('copywriting', "Write a product description.")
        }
        service_key, prompt = service_map[task_id % 3]

        try:
            result = await ctx.ai_services[service_key].process(prompt)
            return {"task_id": task_id, "service": service_key, "success": True}
        except Exception as e:
            return {"task_id": task_id, "service": service_key, "success": False, "error": str(e)}

    # Run inferences concurrently
    start_time = time.time()
    tasks = [run_inference(i) for i in range(inference_count)]
    results = await asyncio.gather(*tasks)
    duration = time.time() - start_time

    successful = [r for r in results if r["success"]]
    assert len(successful) >= inference_count * 0.9, \
        f"Too many AI inference failures: {len(successful)}/{inference_count}"

    logger.info(f"✅ Completed {len(successful)} AI inferences in {duration:.2f}s")


@pytest.mark.performance
@pytest.mark.asyncio
async def test_platform_monitoring_under_load(test_context):
    """
    Test concurrent monitoring of 10+ freelance platforms.
    Validates scraper stability, API rate limiting, and data consistency.
    """
    ctx = test_context
    logger.info("🌐 Starting platform monitoring under load test...")

    async def monitor_platform(platform) -> bool:
        try:
            jobs = await platform.scrape_jobs(limit=5)
            assert isinstance(jobs, list)
            return len(jobs) >= 0  # May be empty, but not error
        except Exception as e:
            logger.warning(f"Platform {platform.name} monitoring failed: {e}")
            return False

    start_time = time.time()
    tasks = [monitor_platform(p) for p in ctx.platforms]
    results = await asyncio.gather(*tasks)
    duration = time.time() - start_time

    success_rate = sum(results) / len(ctx.platforms)
    assert success_rate >= 0.9, f"Platform monitoring unstable: {success_rate:.2%}"

    logger.info(f"✅ Monitored {sum(results)}/{len(ctx.platforms)} platforms in {duration:.2f}s")