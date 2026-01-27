# AI_FREELANCE_AUTOMATION/tests/integration/test_ai_services.py
"""
Integration tests for AI Services:
- TranscriptionService
- TranslationService
- CopywritingService
- EditingService
- ProofreadingService

These tests verify end-to-end functionality with mocked AI models,
configuration, logging, and error recovery as per system architecture.
"""

import os
import asyncio
import tempfile
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# Core dependencies (as per your architecture)
from core.config.unified_config_manager import UnifiedConfigManager
from core.security.advanced_crypto_system import AdvancedCryptoSystem
from core.dependency.dependency_manager import DependencyManager
from core.monitoring.intelligent_monitor import IntelligentMonitor
from core.ai_engine.model_manager import ModelManager

# AI Services under test
from services.ai.transcription_service import TranscriptionService
from services.ai.translation_service import TranslationService
from services.ai.copywriting_service import CopywritingService
from services.ai.editing_service import EditingService
from services.ai.proofreading_service import ProofreadingService


@pytest.fixture(scope="session")
def config():
    """Provide a minimal valid config for integration tests."""
    # Use in-memory config to avoid file I/O
    cfg = UnifiedConfigManager(config_source={"mode": "test"})
    cfg.set("ai.transcription.enabled", True)
    cfg.set("ai.translation.enabled", True)
    cfg.set("ai.copywriting.enabled", True)
    cfg.set("monitoring.enabled", False)  # Disable external monitoring in tests
    cfg.set("security.encryption_key", b"test_key_32_bytes_long_enough_1234")
    return cfg


@pytest.fixture(scope="session")
def crypto(config):
    """Initialize crypto system with test key."""
    return AdvancedCryptoSystem(master_key=config.get("security.encryption_key"))


@pytest.fixture
def mock_model_manager():
    """Mocked AI model manager that simulates loading and inference."""
    mock = AsyncMock(spec=ModelManager)

    # Simulate model responses
    async def mock_infer(model_name: str, input_data: dict) -> dict:
        if "transcribe" in model_name:
            return {"text": "This is a transcribed test audio."}
        elif "translate" in model_name:
            return {"translated_text": "Ceci est un texte de test traduit."}
        elif "copywrite" in model_name:
            return {"content": "Generated marketing copy tailored to your needs."}
        elif "edit" in model_name:
            return {"edited_text": "Improved and polished version of the original text."}
        elif "proofread" in model_name:
            return {"corrected_text": "Corrected grammar, punctuation, and style."}
        else:
            return {"output": "Generic AI output."}

    mock.infer = mock_infer
    mock.load_model = AsyncMock(return_value=True)
    mock.is_model_loaded = MagicMock(return_value=True)
    return mock


@pytest.fixture
def dependency_manager(config, crypto, mock_model_manager):
    """Set up DI container with mocked critical services."""
    dm = DependencyManager()
    dm.register_instance("config", config)
    dm.register_instance("crypto", crypto)
    dm.register_instance("model_manager", mock_model_manager)
    dm.register_instance("monitor", IntelligentMonitor(config))
    return dm


@pytest.mark.asyncio
async def test_transcription_service_end_to_end(dependency_manager, mock_model_manager):
    """Test full transcription pipeline: file → AI → result."""
    service = TranscriptionService(dependency_manager)

    # Create dummy audio file
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(b"FAKE_AUDIO_DATA")  # Not real audio — just for path validation
        audio_path = tmp.name

    try:
        result = await service.transcribe(
            audio_file_path=audio_path,
            language="en",
            job_id="test_job_001"
        )
        assert result["text"] == "This is a transcribed test audio."
        assert "job_id" in result
        assert result["job_id"] == "test_job_001"
    finally:
        os.unlink(audio_path)


@pytest.mark.asyncio
async def test_translation_service_end_to_end(dependency_manager):
    """Test translation between languages."""
    service = TranslationService(dependency_manager)

    result = await service.translate(
        text="This is a test.",
        source_lang="en",
        target_lang="fr",
        job_id="test_job_002"
    )

    assert result["translated_text"] == "Ceci est un texte de test traduit."
    assert result["source"] == "en"
    assert result["target"] == "fr"


@pytest.mark.asyncio
async def test_copywriting_service_end_to_end(dependency_manager):
    """Test AI-generated copy based on brief."""
    service = CopywritingService(dependency_manager)

    result = await service.generate_copy(
        brief="Write a product description for wireless headphones.",
        tone="professional",
        length="medium",
        job_id="test_job_003"
    )

    assert "wireless headphones" in result["content"].lower()
    assert len(result["content"]) > 50


@pytest.mark.asyncio
async def test_editing_and_proofreading_pipeline(dependency_manager):
    """Test chained editing + proofreading workflow."""
    editor = EditingService(dependency_manager)
    proofreader = ProofreadingService(dependency_manager)

    raw_text = "this is a badly writen sentense with erors."

    edited = await editor.improve_text(raw_text, style="formal")
    assert "badly writen" not in edited["edited_text"]

    proofread = await proofreader.correct_text(edited["edited_text"])
    assert "erors" not in proofread["corrected_text"]
    assert "sentence" in proofread["corrected_text"]  # corrected spelling


@pytest.mark.asyncio
async def test_ai_service_error_recovery(dependency_manager):
    """Simulate AI model failure and verify graceful degradation."""
    # Temporarily break the model manager
    mm = dependency_manager.resolve("model_manager")
    original_infer = mm.infer

    async def failing_infer(*args, **kwargs):
        raise RuntimeError("AI model crashed")

    mm.infer = failing_infer

    service = CopywritingService(dependency_manager)

    with pytest.raises(Exception) as exc_info:
        await service.generate_copy(
            brief="Simple test",
            tone="neutral",
            length="short",
            job_id="test_fail_001"
        )

    assert "AI model crashed" in str(exc_info.value)

    # Restore
    mm.infer = original_infer


def test_dependency_injection_consistency(dependency_manager):
    """Ensure all AI services accept the same DI contract."""
    services = [
        TranscriptionService(dependency_manager),
        TranslationService(dependency_manager),
        CopywritingService(dependency_manager),
        EditingService(dependency_manager),
        ProofreadingService(dependency_manager),
    ]

    for svc in services:
        assert hasattr(svc, 'config')
        assert hasattr(svc, 'crypto')
        assert hasattr(svc, 'model_manager')
        assert callable(getattr(svc, 'logger', None))


if __name__ == "__main__":
    # Allow direct execution for debugging
    pytest.main([__file__, "-v", "-s"])