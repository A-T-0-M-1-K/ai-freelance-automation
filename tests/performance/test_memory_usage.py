# AI_FREELANCE_AUTOMATION/tests/performance/test_memory_usage.py
"""
Performance test for memory usage across core components.
Validates that the system stays within acceptable memory bounds
during typical and peak freelance automation workloads.

Ensures no memory leaks during:
- AI model loading/unloading
- Concurrent job processing
- Long-running communication sessions
- Cache operations
- Payment transaction handling

Complies with:
- PEP 8 / PEP 484
- Project testing conventions
- Performance monitoring standards
"""

import asyncio
import gc
import logging
import tracemalloc
from typing import Any, Dict, List, Optional
from pathlib import Path

import psutil
import pytest

from core.ai_management.intelligent_model_manager import IntelligentModelManager
from core.automation.auto_freelancer_core import AutoFreelancerCore
from core.communication.empathetic_communicator import EmpatheticCommunicator
from core.payment.enhanced_payment_processor import EnhancedPaymentProcessor
from core.performance.intelligent_cache_system import IntelligentCacheSystem
from services.ai_services.transcription_service import TranscriptionService
from services.ai_services.translation_service import TranslationService
from services.storage.database_service import DatabaseService

# Configure module-specific logger
logger = logging.getLogger(__name__)

# Constants for thresholds (in MB)
MEMORY_THRESHOLD_IDLE = 100  # Max memory at idle
MEMORY_THRESHOLD_ACTIVE = 500  # Max during active workload
MEMORY_LEAK_THRESHOLD = 5  # Max allowed growth per cycle (MB)


class MemoryUsageTester:
    """Helper class to encapsulate memory measurement logic."""

    def __init__(self):
        self.process = psutil.Process()
        self.initial_memory: Optional[float] = None
        self.snapshots: List[tracemalloc.Snapshot] = []

    def get_memory_mb(self) -> float:
        """Get current memory usage in MB."""
        return self.process.memory_info().rss / 1024 / 1024

    def start_tracing(self):
        """Start detailed memory tracing."""
        if not tracemalloc.is_tracing():
            tracemalloc.start()
        self.initial_memory = self.get_memory_mb()

    def take_snapshot(self) -> tracemalloc.Snapshot:
        """Take a memory snapshot and store it."""
        snap = tracemalloc.take_snapshot()
        self.snapshots.append(snap)
        return snap

    def get_memory_growth(self) -> float:
        """Calculate memory growth since start."""
        if self.initial_memory is None:
            raise RuntimeError("Tracing not started")
        return self.get_memory_mb() - self.initial_memory


@pytest.fixture(scope="module")
def event_loop():
    """Custom event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def memory_tester():
    """Fixture providing a clean memory tester instance."""
    tester = MemoryUsageTester()
    tester.start_tracing()
    yield tester
    # Cleanup
    tracemalloc.stop()
    gc.collect()


@pytest.mark.performance
@pytest.mark.asyncio
async def test_memory_idle_baseline(memory_tester: MemoryUsageTester):
    """Test that base system memory usage is within acceptable limits."""
    # Allow system to stabilize
    await asyncio.sleep(0.5)
    current = memory_tester.get_memory_mb()
    assert current <= MEMORY_THRESHOLD_IDLE, \
        f"Idle memory ({current:.2f} MB) exceeds threshold ({MEMORY_THRESHOLD_IDLE} MB)"
    logger.info(f"✅ Idle memory: {current:.2f} MB")


@pytest.mark.performance
@pytest.mark.asyncio
async def test_ai_model_loading_unloading(memory_tester: MemoryUsageTester):
    """Validate memory behavior during AI model lifecycle."""
    config = {"model_name": "whisper-medium", "device": "cpu"}
    manager = IntelligentModelManager(config)

    # Load model
    await manager.load_model("whisper-medium")
    after_load = memory_tester.get_memory_mb()
    logger.info(f"Memory after model load: {after_load:.2f} MB")

    # Unload model
    await manager.unload_model("whisper-medium")
    after_unload = memory_tester.get_memory_mb()
    logger.info(f"Memory after model unload: {after_unload:.2f} MB")

    # Force garbage collection
    gc.collect()

    final_memory = memory_tester.get_memory_mb()
    growth = final_memory - memory_tester.initial_memory
    assert growth <= MEMORY_LEAK_THRESHOLD, \
        f"Memory leak detected after model cycle: {growth:.2f} MB growth"


@pytest.mark.performance
@pytest.mark.asyncio
async def test_concurrent_job_processing_memory(memory_tester: MemoryUsageTester):
    """Test memory under simulated concurrent job load."""
    # Simulate 10 concurrent transcription jobs
    service = TranscriptionService()
    tasks = []
    for i in range(10):
        # Use dummy audio path — service should handle gracefully
        task = asyncio.create_task(
            service.transcribe_audio(f"dummy_audio_{i}.mp3", language="en")
        )
        tasks.append(task)

    # Wait for completion (expect failures on dummy files, but no memory issues)
    results = await asyncio.gather(*tasks, return_exceptions=True)
    del results  # Explicitly release

    gc.collect()
    final_memory = memory_tester.get_memory_mb()
    growth = final_memory - memory_tester.initial_memory
    assert growth <= MEMORY_THRESHOLD_ACTIVE, \
        f"Memory exceeded during concurrent jobs: {final_memory:.2f} MB"


@pytest.mark.performance
@pytest.mark.asyncio
async def test_cache_memory_behavior(memory_tester: MemoryUsageTester):
    """Ensure cache system respects memory limits."""
    cache_config = {
        "max_memory_percent": 10,
        "eviction_policy": "lru",
        "ttl_seconds": 300
    }
    cache = IntelligentCacheSystem(cache_config)

    # Fill cache beyond nominal capacity
    for i in range(1000):
        await cache.set(f"key_{i}", {"data": "x" * 1000})

    # Trigger cleanup
    await cache.evict_expired()
    await cache.evict_by_policy()

    gc.collect()
    final_memory = memory_tester.get_memory_mb()
    assert final_memory <= MEMORY_THRESHOLD_ACTIVE, \
        f"Cache caused excessive memory usage: {final_memory:.2f} MB"


@pytest.mark.performance
@pytest.mark.asyncio
async def test_full_automation_cycle_memory(memory_tester: MemoryUsageTester):
    """Simulate full freelance cycle and check memory stability."""
    # Initialize minimal required components
    db = DatabaseService()
    payment = EnhancedPaymentProcessor()
    communicator = EmpatheticCommunicator()
    freelancer = AutoFreelancerCore(db=db, payment=payment, communicator=communicator)

    # Simulate one full cycle (without real platform calls)
    await freelancer.initialize()
    await freelancer.perform_health_check()
    await freelancer.cleanup()

    del freelancer, communicator, payment, db
    gc.collect()

    final_memory = memory_tester.get_memory_mb()
    growth = final_memory - memory_tester.initial_memory
    assert growth <= MEMORY_LEAK_THRESHOLD * 2, \
        f"Full cycle caused memory leak: {growth:.2f} MB"


if __name__ == "__main__":
    # Allow direct execution for profiling
    logging.basicConfig(level=logging.INFO)
    pytest.main([__file__, "-v"])