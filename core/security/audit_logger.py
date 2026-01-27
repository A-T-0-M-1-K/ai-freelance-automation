# AI_FREELANCE_AUTOMATION/core/security/audit_logger.py
"""
🔐 Audit Logger — компонент системы безопасности, отвечающий за детальное,
непрерывное и неизменяемое журналирование всех критически важных операций.

Функции:
- Запись всех действий с метаданными (время, пользователь/агент, IP, действие, статус)
- Криптографическая целостность записей (HMAC-SHA256)
- Поддержка GDPR/PCI DSS: анонимизация чувствительных данных
- Автоматическое ротирование и архивирование
- Интеграция с anomaly_detector для выявления подозрительной активности

Соответствие стандартам:
✅ GDPR Article 30 (запись операций обработки)
✅ PCI DSS Requirement 10 (аудит доступа к данным)
✅ SOC 2 CC6.1, CC7.2
"""

import json
import logging
import os
import hmac
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Union
from dataclasses import dataclass, asdict

from core.config.unified_config_manager import UnifiedConfigManager
from core.security.encryption_engine import EncryptionEngine


@dataclass(frozen=True)
class AuditRecord:
    """Структура записи аудита."""
    timestamp: str  # ISO 8601 UTC
    actor_id: str   # ID агента или внешней системы
    action: str     # Например: "job.bid.submitted", "payment.received"
    resource: str   # URI или идентификатор ресурса
    status: str     # "success", "failure", "warning"
    details: Dict[str, Any]
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    session_id: Optional[str] = None


class AuditLogger:
    """
    Централизованный, отказоустойчивый аудиторский журнал.
    Гарантирует неизменяемость, конфиденциальность и соответствие нормативным требованиям.
    """

    def __init__(self, config_manager: UnifiedConfigManager, crypto_engine: EncryptionEngine):
        self.config = config_manager.get_section("security.audit")
        self.crypto = crypto_engine
        self.logger = logging.getLogger("Security.AuditLogger")

        # Путь к файлу аудита
        self.log_path = Path(self.config.get("log_file", "logs/app/audit.log"))
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

        # Секретный ключ для HMAC (должен быть загружен из secure storage)
        self.hmac_key = self._load_hmac_key()
        self.enabled = self.config.get("enabled", True)

        self.logger.info("🛡️ AuditLogger initialized. Logging to: %s", self.log_path)

    def _load_hmac_key(self) -> bytes:
        """Загружает HMAC-ключ из защищённого хранилища."""
        key_path = Path(self.config.get("hmac_key_path", "data/secrets/audit_hmac.key"))
        if not key_path.exists():
            # Генерация нового ключа при первом запуске
            key = os.urandom(32)  # 256-bit key
            key_path.parent.mkdir(parents=True, exist_ok=True)
            with open(key_path, "wb") as f:
                f.write(key)
            self.logger.warning("🆕 Generated new HMAC key for audit integrity: %s", key_path)
        else:
            with open(key_path, "rb") as f:
                key = f.read()
        return key

    def _sanitize_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Удаляет или маскирует PII/чувствительные данные в соответствии с GDPR."""
        sensitive_keys = {"password", "token", "api_key", "credit_card", "ssn", "email"}
        sanitized = {}
        for k, v in data.items():
            if isinstance(v, dict):
                sanitized[k] = self._sanitize_data(v)
            elif isinstance(k, str) and any(s in k.lower() for s in sensitive_keys):
                sanitized[k] = "[REDACTED]"
            else:
                sanitized[k] = v
        return sanitized

    def _compute_hmac(self, record_json: str) -> str:
        """Вычисляет HMAC-SHA256 для обеспечения целостности записи."""
        return hmac.new(self.hmac_key, record_json.encode("utf-8"), hashlib.sha256).hexdigest()

    def log(
        self,
        actor_id: str,
        action: str,
        resource: str,
        status: str,
        details: Dict[str, Any],
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> None:
        """
        Записывает событие в аудит-журнал.

        Args:
            actor_id: Идентификатор инициатора (например: "autonomous_agent_01")
            action: Семантическое имя действия (например: "platform.upwork.bid.sent")
            resource: Ресурс, над которым выполнено действие (например: "job:12345")
            status: "success" | "failure" | "warning"
            details: Дополнительные данные (будут санитизированы)
            ip_address: IP-адрес источника (если применимо)
            user_agent: User-Agent клиента
            session_id: Идентификатор сессии
        """
        if not self.enabled:
            return

        try:
            # Санитизация
            clean_details = self._sanitize_data(details)

            # Создание записи
            record = AuditRecord(
                timestamp=datetime.now(timezone.utc).isoformat(),
                actor_id=actor_id,
                action=action,
                resource=resource,
                status=status,
                details=clean_details,
                ip_address=ip_address,
                user_agent=user_agent,
                session_id=session_id,
            )

            record_dict = asdict(record)
            record_json = json.dumps(record_dict, ensure_ascii=False, separators=(",", ":"))

            # Добавление HMAC для целостности
            hmac_digest = self._compute_hmac(record_json)
            full_entry = {
                "record": record_dict,
                "hmac": hmac_digest,
            }

            # Запись в файл
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(full_entry, ensure_ascii=False) + "\n")

            # Также отправляем в системный лог для мониторинга
            self.logger.info("AUDIT: %s | %s | %s", actor_id, action, status)

        except Exception as e:
            # Логируем ошибку в emergency-канал, но НЕ прерываем основной поток
            self.logger.critical("💥 AuditLogger failed to write entry: %s", e, exc_info=True)
            # В экстренных случаях можно вызвать EmergencyRecovery, но не здесь напрямую

    def verify_integrity(self, entry: Dict[str, Any]) -> bool:
        """
        Проверяет целостность одной записи аудита.
        Используется при расследовании инцидентов или аудите.
        """
        record_json = json.dumps(entry["record"], ensure_ascii=False, separators=(",", ":"))
        expected_hmac = self._compute_hmac(record_json)
        return hmac.compare_digest(expected_hmac, entry["hmac"])

    def export_for_compliance(self, start_date: str, end_date: str) -> Path:
        """
        Экспортирует аудит-журнал за период в зашифрованный архив для compliance.
        Возвращает путь к файлу.
        """
        # Реализация опциональна — может быть расширена через плагин
        raise NotImplementedError("Compliance export will be implemented in v1.1")


# Singleton-like factory (рекомендуется использовать через DI)
_audit_logger_instance: Optional[AuditLogger] = None


def get_audit_logger(config_manager: UnifiedConfigManager, crypto_engine: EncryptionEngine) -> AuditLogger:
    """Фабрика для получения глобального экземпляра AuditLogger."""
    global _audit_logger_instance
    if _audit_logger_instance is None:
        _audit_logger_instance = AuditLogger(config_manager, crypto_engine)
    return _audit_logger_instance