# AI_FREELANCE_AUTOMATION/tests/integration/test_automation_flow.py
"""
Integration test for the full autonomous freelance workflow:
1. Job discovery → 2. Decision → 3. Bid → 4. Communication →
5. Task execution → 6. Quality control → 7. Delivery → 8. Payment

This test simulates a realistic end-to-end scenario using mocked platforms
and real internal components to validate system cohesion and autonomy.
"""

import asyncio
import json
import logging
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

# Core components under test
from core.automation.auto_freelancer_core import AutoFreelancerCore
from core.config.unified_config_manager import UnifiedConfigManager
from core.security.advanced_crypto_system import AdvancedCryptoSystem
from core.dependency.service_locator import ServiceLocator
from core.dependency.dependency_manager import DependencyManager

# Services
from services.ai_services.transcription_service import TranscriptionService
from services.ai_services.translation_service import TranslationService
from services.notification.email_service import EmailService

# Platform mock
from platforms.platform_factory import PlatformFactory

# Test utilities
from tests.fixtures import load_test_config, create_mock_platform_client

# Configure logging for test visibility
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


@pytest.fixture(scope="function")
def temp_data_dir():
    """Create a temporary data directory for isolated test runs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture(scope="function")
def test_config(temp_data_dir):
    """Load and adapt config for testing environment."""
    config = load_test_config()
    config.set("data.root", str(temp_data_dir))
    config.set("logs.dir", str(temp_data_dir / "logs"))
    config.set("ai.models.cache_dir", str(temp_data_dir / "ai_models"))
    return config


@pytest.fixture(scope="function")
def crypto_system():
    """Provide a lightweight crypto system for testing."""
    return AdvancedCryptoSystem(use_hardware_security_module=False)


@pytest.fixture(scope="function")
def dependency_container(test_config, crypto_system):
    """Initialize DI container with minimal real + mocked dependencies."""
    dm = DependencyManager()

    # Real core components
    dm.register_singleton("config", lambda: test_config)
    dm.register_singleton("crypto", lambda: crypto_system)

    # Mock external services
    email_mock = AsyncMock(spec=EmailService)
    dm.register_singleton("email_service", lambda: email_mock)

    # Real AI services (but models won't be loaded in test mode)
    dm.register_singleton("transcription_service", lambda c: TranscriptionService(c["config"]))
    dm.register_singleton("translation_service", lambda c: TranslationService(c["config"]))

    # Mock platform factory
    platform_mock = AsyncMock()
    platform_mock.get_client.return_value = create_mock_platform_client()
    dm.register_singleton("platform_factory", lambda: platform_mock)

    return dm


@pytest.mark.asyncio
async def test_full_automation_workflow(dependency_container, temp_data_dir):
    """
    End-to-end test of autonomous freelance cycle:
    - Finds a job on a mocked platform
    - Analyzes and accepts it
    - Communicates with client
    - Executes transcription task
    - Delivers result
    - Processes payment confirmation
    """
    # Arrange
    logger.info("🧪 Starting full automation workflow test...")

    # Initialize service locator with container
    ServiceLocator.initialize(dependency_container)

    # Create freelancer core
    freelancer = AutoFreelancerCore(
        config=dependency_container.resolve("config"),
        crypto=dependency_container.resolve("crypto")
    )

    # Prepare mock job data
    mock_job = {
        "job_id": "job_12345",
        "title": "Transcribe 10-min interview",
        "description": "Need accurate English transcription of audio interview.",
        "budget": 50.0,
        "currency": "USD",
        "deadline_hours": 24,
        "platform": "upwork",
        "client_id": "client_987",
        "audio_url": "https://example.com/audio.mp3"
    }

    # Mock platform responses
    platform_client = dependency_container.resolve("platform_factory").get_client("upwork")
    platform_client.fetch_jobs = AsyncMock(return_value=[mock_job])
    platform_client.submit_bid = AsyncMock(return_value=True)
    platform_client.send_message = AsyncMock(return_value=True)
    platform_client.deliver_work = AsyncMock(return_value=True)
    platform_client.confirm_payment = AsyncMock(return_value=True)

    # Mock file download
    with patch("services.storage.file_storage.FileStorage.download_file") as mock_download:
        mock_download.return_value = b"fake_audio_data"

        # Act
        await freelancer.start()
        await asyncio.sleep(0.1)  # Allow async init

        # Trigger job processing cycle
        success = await freelancer.process_next_job()

        # Stop cleanly
        await freelancer.stop()

    # Assert
    assert success is True, "Freelancer should have completed the job successfully"

    # Verify interactions
    platform_client.fetch_jobs.assert_called_once()
    platform_client.submit_bid.assert_called_once_with(
        job_id="job_12345",
        proposal=pytest.any_string_containing("I can transcribe this accurately"),
        price=45.0  # Expected optimized bid
    )
    platform_client.send_message.assert_called()
    platform_client.deliver_work.assert_called_once()
    platform_client.confirm_payment.assert_called_once()

    # Verify deliverables saved
    job_dir = temp_data_dir / "jobs" / "job_12345"
    assert job_dir.exists(), "Job directory should be created"
    assert (job_dir / "deliverables" / "transcript.txt").exists(), "Transcript should be saved"

    # Verify logs generated
    log_file = temp_data_dir / "logs" / "app" / "application.log"
    assert log_file.exists(), "Application log should exist"

    logger.info("✅ Full automation workflow test passed!")


# Helper matcher for partial string matching in mocks
class AnyStringContaining:
    def __init__(self, substring):
        self.substring = substring

    def __eq__(self, other):
        return isinstance(other, str) and self.substring in other

    def __repr__(self):
        return f"<AnyStringContaining({self.substring!r})>"


# Add to pytest namespace for easy use
pytest.any_string_containing = AnyStringContaining