"""
Модуль безопасности ядра системы AI_FREELANCE_AUTOMATION.

Этот пакет предоставляет единый интерфейс для всех компонентов,
связанных с криптографией, управлением ключами, аудитом и защитой от мошенничества.
Используется для изоляции и централизации всех security-операций в соответствии с принципами
промышленной надежности и соответствия стандартам (GDPR, PCI DSS, SOC 2).

Публичный API:
- AdvancedCryptoSystem
- SecurityConfigManager
- KeyManager
- EncryptionEngine
- AuditLogger
- FraudDetector
"""

from .advanced_crypto_system import AdvancedCryptoSystem
from .security_config_manager import SecurityConfigManager
from .key_manager import KeyManager
from .encryption_engine import EncryptionEngine
from .audit_logger import AuditLogger
from .fraud_detector import FraudDetector

# Версия модуля безопасности (для внутреннего контроля совместимости)
__version__ = "1.0.0"
__author__ = "AI Freelance Automation Core Team"
__all__ = [
    "AdvancedCryptoSystem",
    "SecurityConfigManager",
    "KeyManager",
    "EncryptionEngine",
    "AuditLogger",
    "FraudDetector",
]