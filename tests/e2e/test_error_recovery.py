# AI_FREELANCE_AUTOMATION/tests/e2e/test_error_recovery.py
"""
End-to-End тест: проверка механизма самовосстановления при критических ошибках.

Тестирует:
- Автоматическое обнаружение сбоя компонента
- Инициацию аварийного восстановления
- Восстановление состояния системы без потери данных
- Продолжение выполнения заказа после сбоя
- Корректную работу audit_logger и anomaly_detector

Сценарий:
1. Запуск полной системы (через test fixture)
2. Искусственное вызывание сбоя в одном из критических сервисов (например, payment processor)
3. Проверка, что EmergencyRecovery активируется
4. Проверка, что система возвращается к рабочему состоянию
5. Проверка, что текущие заказы не теряются и завершаются корректно
"""

import asyncio
import logging
import pytest
from unittest.mock import patch, AsyncMock

from core.dependency.service_locator import ServiceLocator
from core.config.unified_config_manager import UnifiedConfigManager
from core.security.advanced_crypto_system import AdvancedCryptoSystem
from core.monitoring.intelligent_monitoring_system import IntelligentMonitoringSystem
from core.automation.auto_freelancer_core import AutoFreelancerCore
from core.emergency_recovery import EmergencyRecovery  # Предполагается, что он в core/
from services.ai_services.transcription_service import TranscriptionService
from platforms.upwork.client import UpworkClient

# Настройка логгера для теста
logger = logging.getLogger(__name__)


@pytest.fixture(scope="session")
async def running_system():
    """
    Запускает минимальную, но полностью функциональную систему для E2E-тестов.
    Использует реальные компоненты, но с mock-платформами и sandbox-платежами.
    """
    config = UnifiedConfigManager(profile="testing")
    crypto = AdvancedCryptoSystem()
    monitoring = IntelligentMonitoringSystem(config)

    # Инициализация ядра
    system = AutoFreelancerCore(
        config=config,
        crypto=crypto,
        monitoring=monitoring
    )
    await system.start()

    yield system

    # Очистка
    await system.stop()


@pytest.mark.asyncio
async def test_emergency_recovery_after_payment_processor_crash(running_system):
    """
    Тестирует восстановление после аварийного завершения PaymentProcessor.
    """
    system = running_system

    # Создаем фиктивный заказ на транскрибацию
    job_id = "job_test_001"
    client_id = "client_test_001"
    await system.job_manager.create_job(
        job_id=job_id,
        client_id=client_id,
        job_type="transcription",
        source_url="https://example.com/audio.mp3",
        deadline_minutes=10
    )

    # Подменяем метод платежного процессора, чтобы он падал
    original_process = system.payment_processor.process_payment
    crash_count = 0

    async def crashing_payment_processor(*args, **kwargs):
        nonlocal crash_count
        crash_count += 1
        if crash_count <= 2:
            raise RuntimeError("Simulated payment service crash")
        return await original_process(*args, **kwargs)

    system.payment_processor.process_payment = crashing_payment_processor

    # Запускаем выполнение заказа
    task = asyncio.create_task(system.execute_job(job_id))

    # Ждём, пока задача либо завершится, либо упадёт
    try:
        await asyncio.wait_for(task, timeout=30.0)
    except asyncio.TimeoutError:
        pytest.fail("Job execution timed out — recovery may have failed")

    # Проверки
    assert crash_count >= 2, "Payment crash was not triggered"
    assert system.health_monitor.is_healthy(), "System is not healthy after recovery"
    assert await system.job_manager.get_job_status(job_id) == "completed", "Job was not completed"
    assert await system.payment_orchestrator.was_payment_received(job_id), "Payment was not received"

    # Проверяем, что лог аудита содержит запись о восстановлении
    audit_logs = system.audit_logger.get_logs(from_event="emergency_recovery")
    assert len(audit_logs) > 0, "No audit log for emergency recovery"


@pytest.mark.asyncio
async def test_recovery_preserves_conversation_context(running_system):
    """
    Убеждаемся, что после сбоя контекст диалога с клиентом не теряется.
    """
    system = running_system
    client_id = "client_ctx_001"
    job_id = "job_ctx_001"

    # Имитируем диалог
    await system.communicator.send_message(client_id, "Hello! I'll handle your translation.")
    await system.communicator.receive_message(client_id, "Great! Please use British English.")

    # Сохраняем контекст до сбоя
    pre_crash_context = await system.communicator.get_conversation_context(client_id)

    # Имитируем сбой в DialogueManager
    with patch.object(system.communicator.dialogue_manager, 'load_context', side_effect=Exception("DB timeout")):
        # Пытаемся продолжить общение — должно вызвать восстановление
        try:
            await system.communicator.send_message(client_id, "Understood. Starting now.")
        except Exception:
            pass  # Ожидаемо

    # Ждём завершения восстановления
    await asyncio.sleep(2)

    # Проверяем, что контекст восстановлен
    post_crash_context = await system.communicator.get_conversation_context(client_id)
    assert post_crash_context == pre_crash_context, "Conversation context was lost during recovery"


def test_anomaly_detection_triggers_recovery():
    """
    Проверяет, что AnomalyDetector корректно сигнализирует о проблеме,
    и EmergencyRecovery реагирует.
    """
    config = UnifiedConfigManager(profile="testing")
    monitoring = IntelligentMonitoringSystem(config)
    recovery = EmergencyRecovery(monitoring=monitoring)

    # Имитируем аномалию
    monitoring.metrics_collector.record("payment_failures", 100)
    monitoring.anomaly_detector.check_for_anomalies()

    # Должен быть создан инцидент
    incidents = recovery.incident_registry.get_active_incidents()
    assert len(incidents) > 0, "Anomaly did not trigger incident creation"

    # Запускаем восстановление
    asyncio.run(recovery.initiate_recovery(incidents[0]))

    # Проверяем, что статус восстановления успешен
    assert recovery.recovery_history[-1]["status"] == "success", "Recovery failed"


if __name__ == "__main__":
    # Позволяет запустить тест вручную: python -m tests.e2e.test_error_recovery
    pytest.main([__file__, "-v", "-s"])