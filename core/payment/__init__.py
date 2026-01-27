"""
Модуль платежной системы ядра приложения.
Обеспечивает корректный импорт всех компонентов платежной подсистемы,
гарантирует совместимость и предотвращает циклические зависимости.
"""

from .enhanced_payment_processor import EnhancedPaymentProcessor
from .fraud_detection_system import FraudDetectionSystem

# Поставщики платежей доступны через фабрику, а не напрямую из __init__
# Это позволяет изолировать реализацию и упростить расширение
from .payment_providers import (
    get_payment_provider,
    register_payment_provider,
    list_available_providers
)

# Публичный API модуля
__all__ = [
    "EnhancedPaymentProcessor",
    "FraudDetectionSystem",
    "get_payment_provider",
    "register_payment_provider",
    "list_available_providers",
]

# Метаданные модуля
__version__ = "1.0.0"
__author__ = "AI Freelance Automation Team"