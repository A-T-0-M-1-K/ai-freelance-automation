# tests/unit/test_model_manager.py
"""
Unit tests for IntelligentModelManager in core/ai_management/intelligent_model_manager.py.
Ensures model loading, unloading, memory monitoring, and error recovery work correctly.
"""

import os
import tempfile
import shutil
from unittest.mock import Mock, patch, MagicMock
import pytest

from core.ai_management.intelligent_model_manager import IntelligentModelManager
from core.config.unified_config_manager import UnifiedConfigManager


@pytest.fixture
def mock_config():
    """Provide a minimal valid config for testing."""
    config = Mock(spec=UnifiedConfigManager)
    config.get.return_value = {
        "model_paths": {
            "whisper": "ai/models/whisper-medium",
            "translation": "ai/models/nllb-200",
            "textgen": "ai/models/gpt2-medium"
        },
        "memory_limits": {
            "max_models_loaded": 3,
            "model_cache_ttl_seconds": 3600
        }
    }
    return config


@pytest.fixture
def temp_model_dir():
    """Create a temporary directory simulating AI models folder."""
    temp_dir = tempfile.mkdtemp()
    os.makedirs(os.path.join(temp_dir, "whisper-medium"), exist_ok=True)
    os.makedirs(os.path.join(temp_dir, "nllb-200"), exist_ok=True)
    os.makedirs(os.path.join(temp_dir, "gpt2-medium"), exist_ok=True)
    yield temp_dir
    shutil.rmtree(temp_dir)


@patch("core.ai_management.intelligent_model_manager.ModelRegistry")
@patch("core.ai_management.intelligent_model_manager.MemoryMonitor")
def test_model_manager_initialization(MockMemoryMonitor, MockModelRegistry, mock_config):
    """Test that IntelligentModelManager initializes correctly."""
    manager = IntelligentModelManager(config=mock_config)

    assert manager is not None
    assert manager._loaded_models == {}
    assert manager._model_usage == {}
    MockModelRegistry.assert_called_once()
    MockMemoryMonitor.assert_called_once()


@patch("core.ai_management.intelligent_model_manager.ModelRegistry")
@patch("core.ai_management.intelligent_model_manager.MemoryMonitor")
def test_load_valid_model(MockMemoryMonitor, MockModelRegistry, mock_config, temp_model_dir):
    """Test successful loading of a known model."""
    # Adjust config to use temp dir
    mock_config.get.return_value["model_paths"]["whisper"] = os.path.join(temp_model_dir, "whisper-medium")

    manager = IntelligentModelManager(config=mock_config)

    # Mock registry to return a fake model object
    mock_model = MagicMock()
    MockModelRegistry.return_value.load_model.return_value = mock_model

    model = manager.load_model("whisper")

    assert model == mock_model
    assert "whisper" in manager._loaded_models
    assert manager._model_usage["whisper"] > 0
    MockModelRegistry.return_value.load_model.assert_called_with(
        "whisper", os.path.join(temp_model_dir, "whisper-medium")
    )


@patch("core.ai_management.intelligent_model_manager.ModelRegistry")
@patch("core.ai_management.intelligent_model_manager.MemoryMonitor")
def test_load_unknown_model(MockMemoryMonitor, MockModelRegistry, mock_config):
    """Test that loading an unknown model raises ValueError."""
    manager = IntelligentModelManager(config=mock_config)

    with pytest.raises(ValueError, match="Unknown model type: nonexistent"):
        manager.load_model("nonexistent")


@patch("core.ai_management.intelligent_model_manager.ModelRegistry")
@patch("core.ai_management.intelligent_model_manager.MemoryMonitor")
def test_unload_model(MockMemoryMonitor, MockModelRegistry, mock_config, temp_model_dir):
    """Test unloading a loaded model."""
    mock_config.get.return_value["model_paths"]["textgen"] = os.path.join(temp_model_dir, "gpt2-medium")
    manager = IntelligentModelManager(config=mock_config)

    mock_model = MagicMock()
    MockModelRegistry.return_value.load_model.return_value = mock_model

    manager.load_model("textgen")
    assert "textgen" in manager._loaded_models

    manager.unload_model("textgen")
    assert "textgen" not in manager._loaded_models
    mock_model.cleanup.assert_called_once()  # assumes model has cleanup()


@patch("core.ai_management.intelligent_model_manager.ModelRegistry")
@patch("core.ai_management.intelligent_model_manager.MemoryMonitor")
def test_auto_eviction_on_memory_limit(MockMemoryMonitor, MockModelRegistry, mock_config, temp_model_dir):
    """Test that oldest model is evicted when max_models_loaded is exceeded."""
    paths = mock_config.get.return_value["model_paths"]
    paths["whisper"] = os.path.join(temp_model_dir, "whisper-medium")
    paths["translation"] = os.path.join(temp_model_dir, "nllb-200")
    paths["textgen"] = os.path.join(temp_model_dir, "gpt2-medium")

    # Set limit to 2 models
    mock_config.get.return_value["memory_limits"]["max_models_loaded"] = 2

    manager = IntelligentModelManager(config=mock_config)
    mock_model = MagicMock()
    MockModelRegistry.return_value.load_model.return_value = mock_model

    # Load 2 models
    manager.load_model("whisper")
    manager.load_model("translation")

    assert len(manager._loaded_models) == 2

    # Load third → should evict whisper (oldest)
    manager.load_model("textgen")

    assert len(manager._loaded_models) == 2
    assert "whisper" not in manager._loaded_models
    assert "translation" in manager._loaded_models
    assert "textgen" in manager._loaded_models


@patch("core.ai_management.intelligent_model_manager.ModelRegistry")
@patch("core.ai_management.intelligent_model_manager.MemoryMonitor")
def test_get_model_reuses_loaded(MockMemoryMonitor, MockModelRegistry, mock_config, temp_model_dir):
    """Test that get_model returns already loaded instance."""
    mock_config.get.return_value["model_paths"]["whisper"] = os.path.join(temp_model_dir, "whisper-medium")
    manager = IntelligentModelManager(config=mock_config)

    mock_model = MagicMock()
    MockModelRegistry.return_value.load_model.return_value = mock_model

    model1 = manager.get_model("whisper")
    model2 = manager.get_model("whisper")

    assert model1 is model2  # same instance
    MockModelRegistry.return_value.load_model.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])