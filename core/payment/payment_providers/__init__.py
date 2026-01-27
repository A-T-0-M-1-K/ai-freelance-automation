# AI_FREELANCE_AUTOMATION/core/payment/payment_providers/__init__.py
"""
Payment Providers Package Initialization

This package contains integrations with external payment systems.
Each provider implements a unified interface for processing payments,
handling refunds, verifying transactions, and detecting fraud.

All providers are designed to be:
- Thread-safe
- Configurable via core/config
- Isolated from direct external dependencies (via service locator)
- Compatible with the EnhancedPaymentProcessor
- Secure by default (PCI DSS compliant patterns)

Exports standardized provider factory and registry.
"""

from typing import Dict, Type
from core.payment.payment_providers.stripe_provider import StripeProvider
from core.payment.payment_providers.paypal_provider import PayPalProvider
from core.payment.payment_providers.yoomoney_provider import YooMoneyProvider
from core.payment.payment_providers.crypto_provider import CryptoProvider

# Unified registry of available payment providers
# Used by EnhancedPaymentProcessor to dynamically select provider
PAYMENT_PROVIDER_REGISTRY: Dict[str, Type] = {
    "stripe": StripeProvider,
    "paypal": PayPalProvider,
    "yoomoney": YooMoneyProvider,
    "crypto": CryptoProvider,
}


def get_payment_provider(provider_name: str):
    """
    Factory function to retrieve a payment provider instance by name.

    Args:
        provider_name (str): Name of the provider (e.g., 'stripe', 'paypal')

    Returns:
        Instance of the requested payment provider

    Raises:
        ValueError: If provider is not registered
    """
    if provider_name not in PAYMENT_PROVIDER_REGISTRY:
        raise ValueError(f"Payment provider '{provider_name}' is not supported. "
                         f"Available: {list(PAYMENT_PROVIDER_REGISTRY.keys())}")

    provider_class = PAYMENT_PROVIDER_REGISTRY[provider_name]
    return provider_class()


# Optional: expose all providers for direct import if needed
__all__ = [
    "StripeProvider",
    "PayPalProvider",
    "YooMoneyProvider",
    "CryptoProvider",
    "get_payment_provider",
    "PAYMENT_PROVIDER_REGISTRY"
]