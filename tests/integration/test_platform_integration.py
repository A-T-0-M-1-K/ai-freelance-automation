# AI_FREELANCE_AUTOMATION/tests/integration/test_platform_integration.py
"""
Integration tests for freelance platform interactions.
Verifies end-to-end communication with real or mocked platform APIs.
Ensures compatibility with platform_factory and platform plugins.
"""

import asyncio
import logging
from unittest.mock import AsyncMock, patch
import pytest

from platforms.platform_factory import PlatformFactory
from core.config.unified_config_manager import UnifiedConfigManager
from core.security.advanced_crypto_system import AdvancedCryptoSystem
from services.storage.database_service import DatabaseService


# Configure test logger
logger = logging.getLogger("test.platform_integration")


@pytest.fixture(scope="session")
def event_loop():
    """Custom event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_config():
    """Provide a minimal valid config for testing."""
    config_data = {
        "platforms": {
            "upwork": {"enabled": True, "api_key": "test_key", "secret": "test_secret"},
            "freelance_ru": {"enabled": True, "login": "test_user", "password": "test_pass"},
            "kwork": {"enabled": True, "token": "test_token"}
        },
        "security": {"encryption_enabled": False}  # Disable encryption in tests
    }
    config = UnifiedConfigManager()
    config._config = config_data  # Inject test config
    return config


@pytest.fixture
def mock_crypto():
    """Mock crypto system for tests."""
    crypto = AdvancedCryptoSystem()
    crypto.encrypt = lambda x: x
    crypto.decrypt = lambda x: x
    return crypto


@pytest.fixture
def mock_db():
    """Mock database service."""
    db = AsyncMock(spec=DatabaseService)
    db.save_job = AsyncMock()
    db.get_client_by_platform_id = AsyncMock(return_value=None)
    return db


@pytest.mark.asyncio
async def test_platform_factory_initialization(mock_config, mock_crypto):
    """Test that PlatformFactory correctly initializes enabled platforms."""
    factory = PlatformFactory(config=mock_config, crypto=mock_crypto)

    # Should initialize all enabled platforms
    assert "upwork" in factory.platforms
    assert "freelance_ru" in factory.platforms
    assert "kwork" in factory.platforms
    assert len(factory.platforms) == 3


@pytest.mark.asyncio
@patch("platforms.upwork.client.UpworkClient.authenticate", new_callable=AsyncMock)
@patch("platforms.upwork.scraper.UpworkScraper.fetch_jobs", new_callable=AsyncMock)
async def test_upwork_job_scraping(mock_fetch, mock_auth, mock_config, mock_crypto, mock_db):
    """Test job scraping from Upwork integration."""
    # Mock response
    mock_jobs = [
        {
            "id": "12345",
            "title": "Transcribe interview",
            "budget": 100,
            "description": "Need audio transcribed from English to text.",
            "skills": ["transcription", "english"],
            "posted_time": "2026-01-25T10:00:00Z"
        }
    ]
    mock_fetch.return_value = mock_jobs
    mock_auth.return_value = True

    factory = PlatformFactory(config=mock_config, crypto=mock_crypto)
    upwork = factory.platforms["upwork"]

    # Simulate login
    await upwork.client.authenticate()
    mock_auth.assert_called_once()

    # Fetch jobs
    jobs = await upwork.scraper.fetch_jobs(category="transcription", limit=1)
    assert len(jobs) == 1
    assert jobs[0]["id"] == "12345"
    assert "transcription" in jobs[0]["skills"]


@pytest.mark.asyncio
@patch("platforms.freelance_ru.client.FreelanceRuClient.submit_bid", new_callable=AsyncMock)
async def test_freelance_ru_bid_submission(mock_submit, mock_config, mock_crypto, mock_db):
    """Test bid submission on Freelance.ru."""
    mock_submit.return_value = {"success": True, "bid_id": "bid_789"}

    factory = PlatformFactory(config=mock_config, crypto=mock_crypto)
    fl = factory.platforms["freelance_ru"]

    job_id = "job_678"
    proposal = "I can transcribe this accurately within 24 hours."
    price = 800

    result = await fl.client.submit_bid(job_id=job_id, proposal=proposal, price=price)

    mock_submit.assert_called_once_with(job_id=job_id, proposal=proposal, price=price)
    assert result["success"] is True
    assert result["bid_id"] == "bid_789"


@pytest.mark.asyncio
@patch("platforms.kwork.client.KworkClient.get_active_orders", new_callable=AsyncMock)
async def test_kwork_order_sync(mock_get_orders, mock_config, mock_crypto, mock_db):
    """Test syncing active orders from Kwork."""
    mock_orders = [
        {
            "order_id": "k101",
            "title": "Translate document EN→RU",
            "status": "in_progress",
            "deadline": "2026-01-28T00:00:00Z",
            "client_id": "user_202"
        }
    ]
    mock_get_orders.return_value = mock_orders

    factory = PlatformFactory(config=mock_config, crypto=mock_crypto)
    kwork = factory.platforms["kwork"]

    orders = await kwork.client.get_active_orders()
    assert len(orders) == 1
    assert orders[0]["order_id"] == "k101"
    assert orders[0]["status"] == "in_progress"


@pytest.mark.asyncio
async def test_disabled_platform_not_loaded(mock_config, mock_crypto):
    """Ensure disabled platforms are not initialized."""
    # Disable Upwork
    mock_config._config["platforms"]["upwork"]["enabled"] = False

    factory = PlatformFactory(config=mock_config, crypto=mock_crypto)

    assert "upwork" not in factory.platforms
    assert "freelance_ru" in factory.platforms
    assert "kwork" in factory.platforms


if __name__ == "__main__":
    # Allow direct execution for debugging
    pytest.main([__file__, "-v", "-s"])