# AI_FREELANCE_AUTOMATION/tests/fixtures.py
"""
Фикстуры для тестирования AI Freelance Automation System.
Обеспечивают изолированную, воспроизводимую среду для всех уровней тестирования.
"""

import os
import tempfile
import json
from pathlib import Path
from typing import Any, Dict, Generator, Optional
from unittest.mock import MagicMock, AsyncMock

import pytest
from core.config.unified_config_manager import UnifiedConfigManager
from core.security.advanced_crypto_system import AdvancedCryptoSystem
from core.dependency.service_locator import ServiceLocator
from core.ai_management.intelligent_model_manager import IntelligentModelManager
from platforms.platform_factory import PlatformFactory
from services.storage.database_service import DatabaseService
from services.notification.email_service import EmailService


# ========================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ========================

def _create_temp_config() -> Dict[str, Any]:
    """Создает минимальную временную конфигурацию для тестов."""
    return {
        "system": {
            "log_level": "DEBUG",
            "temp_dir": tempfile.mkdtemp(),
            "data_dir": tempfile.mkdtemp(),
            "cache_dir": tempfile.mkdtemp()
        },
        "security": {
            "encryption_key": "test_key_32_bytes_long_enough_1234567890ab",
            "password_hash_salt": "test_salt_16b"
        },
        "ai": {
            "default_model": "gpt2-medium",
            "whisper_model": "whisper-small"
        },
        "platforms": {
            "enabled": ["upwork", "freelance_ru"]
        },
        "payment": {
            "providers": ["stripe", "paypal"]
        }
    }


def _write_temp_config(config: Dict[str, Any]) -> str:
    """Записывает временную конфигурацию в JSON-файл и возвращает путь."""
    temp_dir = Path(tempfile.mkdtemp())
    config_path = temp_dir / "test_config.json"
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
    return str(config_path)


# ========================
# ОСНОВНЫЕ ФИКСТУРЫ
# ========================

@pytest.fixture
def temp_dirs() -> Generator[Dict[str, str], None, None]:
    """Создает изолированные временные директории для тестов."""
    dirs = {
        "temp": tempfile.mkdtemp(),
        "data": tempfile.mkdtemp(),
        "cache": tempfile.mkdtemp(),
        "logs": tempfile.mkdtemp(),
        "models": tempfile.mkdtemp()
    }
    try:
        yield dirs
    finally:
        # Очистка не обязательна при использовании pytest — ОС сама уберёт /tmp,
        # но можно добавить shutil.rmtree(dir) при необходимости
        pass


@pytest.fixture
def mock_config_manager(temp_dirs: Dict[str, str]) -> UnifiedConfigManager:
    """Мок конфигурационного менеджера с изолированными путями."""
    config_dict = _create_temp_config()
    config_dict["system"].update(temp_dirs)
    config_path = _write_temp_config(config_dict)

    # Обходим реальную загрузку — используем in-memory
    config = UnifiedConfigManager(config_source=config_dict)
    return config


@pytest.fixture
def mock_crypto_system() -> AdvancedCryptoSystem:
    """Мок криптосистемы с фиксированными ключами для детерминированности."""
    crypto = AdvancedCryptoSystem()
    crypto._master_key = b"test_master_key_32_bytes_long_1234567890ab"
    crypto._salt = b"test_salt_16bytes"
    return crypto


@pytest.fixture
def mock_service_locator(
    mock_config_manager: UnifiedConfigManager,
    mock_crypto_system: AdvancedCryptoSystem
) -> ServiceLocator:
    """Инициализированный ServiceLocator с моками основных сервисов."""
    locator = ServiceLocator()
    locator.register("config", mock_config_manager)
    locator.register("crypto", mock_crypto_system)

    # Моки зависимостей
    locator.register("model_manager", AsyncMock(spec=IntelligentModelManager))
    locator.register("platform_factory", MagicMock(spec=PlatformFactory))
    locator.register("database", AsyncMock(spec=DatabaseService))
    locator.register("email_service", MagicMock(spec=EmailService))

    return locator


@pytest.fixture
def sample_job_data() -> Dict[str, Any]:
    """Пример данных заказа для тестов автоматизации."""
    return {
        "job_id": "job_12345",
        "platform": "upwork",
        "title": "Transcribe 30-min interview",
        "description": "Need accurate transcription of a business interview in English.",
        "budget": {"amount": 50.0, "currency": "USD"},
        "deadline_hours": 24,
        "skills": ["transcription", "english"],
        "client_id": "client_abc",
        "url": "https://www.upwork.com/jobs/12345"
    }


@pytest.fixture
def sample_client_data() -> Dict[str, Any]:
    """Пример данных клиента."""
    return {
        "client_id": "client_abc",
        "name": "John Doe",
        "email": "john@example.com",
        "platform": "upwork",
        "reputation_score": 4.8,
        "past_jobs": 12,
        "preferred_language": "en"
    }


@pytest.fixture
def mock_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    """Устанавливает безопасные переменные окружения для тестов."""
    monkeypatch.setenv("AI_FREELANCE_ENV", "testing")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("ENCRYPTION_KEY", "test_key_32_bytes_long_enough_1234567890ab")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("STRIPE_API_KEY", "sk_test_fake")
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "fake_client_id")


# ========================
# УТИЛИТЫ ДЛЯ ТЕСТОВ
# ========================

class TestContext:
    """Контекстный менеджер для комплексных тестовых сценариев."""
    def __init__(self, config: UnifiedConfigManager, locator: ServiceLocator):
        self.config = config
        self.locator = locator

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        # Здесь можно добавить cleanup (закрытие соединений и т.д.)
        pass


@pytest.fixture
async def test_context(
    mock_config_manager: UnifiedConfigManager,
    mock_service_locator: ServiceLocator
) -> TestContext:
    """Асинхронный контекст для end-to-end тестов."""
    return TestContext(mock_config_manager, mock_service_locator)