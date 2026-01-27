# AI_FREELANCE_AUTOMATION/tests/conftest.py
"""
Central test configuration for pytest.
Provides reusable fixtures, mocks, and setup/teardown logic for all test types:
- unit
- integration
- e2e
- performance

Ensures:
- Isolation between tests
- Clean state before/after each test
- Secure handling of configs and secrets
- Compatibility with core architecture (DI, config, logging, etc.)
"""

import os
import sys
import tempfile
import shutil
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock
from typing import Generator, Any, Dict

import pytest
import yaml
import jsonschema

# Add project root to Python path for absolute imports
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Import core components used in testing
from core.config.unified_config_manager import UnifiedConfigManager
from core.security.advanced_crypto_system import AdvancedCryptoSystem
from core.dependency.service_locator import ServiceLocator
from core.dependency.dependency_manager import DependencyManager


@pytest.fixture(scope="session")
def project_root() -> Path:
    """Return the absolute path to the project root."""
    return PROJECT_ROOT


@pytest.fixture(scope="session")
def test_data_dir(project_root: Path) -> Path:
    """Path to test-specific data directory."""
    return project_root / "tests" / "data"


@pytest.fixture(scope="function")
def temp_dir() -> Generator[Path, None, None]:
    """Create a temporary directory for each test. Automatically cleaned up."""
    tmp = Path(tempfile.mkdtemp(prefix="ai_freelance_test_"))
    yield tmp
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture(scope="session")
def mock_env_vars() -> Dict[str, str]:
    """Mock environment variables for secure testing."""
    return {
        "APP_ENV": "test",
        "LOG_LEVEL": "DEBUG",
        "ENCRYPTION_KEY": "test_key_32_bytes_long_enough_1234",  # 32 bytes for AES-256
        "DATABASE_URL": "sqlite+aiosqlite:///:memory:",
        "STORAGE_PATH": "/tmp/test_storage",
    }


@pytest.fixture(autouse=True, scope="session")
def setup_test_environment(mock_env_vars: Dict[str, str]) -> None:
    """Set environment variables before any test runs."""
    original_env = {k: os.environ.get(k) for k in mock_env_vars}
    os.environ.update(mock_env_vars)
    yield
    # Restore original environment
    for key, value in original_env.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


@pytest.fixture(scope="function")
def config_manager(temp_dir: Path) -> UnifiedConfigManager:
    """Provide a clean, isolated config manager for each test."""
    # Override config paths to use temp dir
    config_paths = {
        "config_dir": str(temp_dir / "config"),
        "data_dir": str(temp_dir / "data"),
        "log_dir": str(temp_dir / "logs"),
        "ai_model_dir": str(temp_dir / "ai/models"),
    }
    os.makedirs(config_paths["config_dir"], exist_ok=True)
    os.makedirs(config_paths["data_dir"], exist_ok=True)
    os.makedirs(config_paths["log_dir"], exist_ok=True)
    os.makedirs(config_paths["ai_model_dir"], exist_ok=True)

    # Create minimal valid config
    base_config = {
        "app": {"name": "AI_FREELANCE_AUTOMATION", "version": "0.1.0"},
        "security": {"encryption_enabled": False},  # Disable crypto in tests unless needed
        "logging": {"level": "DEBUG", "file": str(temp_dir / "logs" / "test.log")},
        "paths": config_paths,
    }
    config_file = Path(config_paths["config_dir"]) / "settings.json"
    with open(config_file, "w") as f:
        json.dump(base_config, f)

    return UnifiedConfigManager(config_dir=config_paths["config_dir"])


@pytest.fixture(scope="function")
def crypto_system() -> AdvancedCryptoSystem:
    """Provide a real (but test-safe) crypto system."""
    return AdvancedCryptoSystem(use_mock_keys=True)


@pytest.fixture(scope="function")
def dependency_manager() -> DependencyManager:
    """Fresh dependency container per test."""
    return DependencyManager()


@pytest.fixture(scope="function")
def service_locator(
    config_manager: UnifiedConfigManager,
    crypto_system: AdvancedCryptoSystem,
    dependency_manager: DependencyManager,
) -> ServiceLocator:
    """Fully initialized service locator for integration tests."""
    locator = ServiceLocator()
    locator.register("config", config_manager)
    locator.register("crypto", crypto_system)
    locator.register("dependencies", dependency_manager)
    return locator


@pytest.fixture
def mock_platform_client() -> AsyncMock:
    """Generic mock for freelance platform clients (Upwork, Kwork, etc.)."""
    client = AsyncMock()
    client.login = AsyncMock(return_value=True)
    client.fetch_jobs = AsyncMock(return_value=[])
    client.submit_bid = AsyncMock(return_value=True)
    client.send_message = AsyncMock(return_value=True)
    return client


@pytest.fixture
def mock_payment_processor() -> AsyncMock:
    """Mock for payment processing."""
    processor = AsyncMock()
    processor.process_payment = AsyncMock(return_value={"status": "success", "tx_id": "test_tx"})
    processor.validate_payment = AsyncMock(return_value=True)
    return processor


# Global test hooks

def pytest_configure(config):
    """Pytest configuration hook."""
    # Register custom markers
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )
    config.addinivalue_line(
        "markers", "integration: marks tests as integration (require external services)"
    )
    config.addinivalue_line(
        "markers", "e2e: marks tests as end-to-end (full workflow)"
    )
    config.addinivalue_line(
        "markers", "performance: marks tests as performance/benchmark"
    )


def pytest_runtest_setup(item):
    """Skip tests based on markers and environment."""
    if "integration" in item.keywords and os.getenv("SKIP_INTEGRATION_TESTS", "0") == "1":
        pytest.skip("Skipping integration tests (SKIP_INTEGRATION_TESTS=1)")
    if "e2e" in item.keywords and os.getenv("SKIP_E2E_TESTS", "0") == "1":
        pytest.skip("Skipping E2E tests (SKIP_E2E_TESTS=1)")


# Optional: Add asyncio support if needed
def pytest_collection_modifyitems(config, items):
    """Automatically mark async tests if using pytest-asyncio."""
    for item in items:
        if "asyncio" in item.keywords:
            item.add_marker(pytest.mark.asyncio)