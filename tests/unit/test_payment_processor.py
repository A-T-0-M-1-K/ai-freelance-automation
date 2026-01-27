# AI_FREELANCE_AUTOMATION/tests/unit/test_payment_processor.py
"""
Unit tests for EnhancedPaymentProcessor.
Ensures correct orchestration of payment providers, fraud detection, and error recovery.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from core.payment.enhanced_payment_processor import EnhancedPaymentProcessor
from core.config.unified_config_manager import UnifiedConfigManager
from core.security.advanced_crypto_system import AdvancedCryptoSystem


class TestEnhancedPaymentProcessor:
    """Test suite for EnhancedPaymentProcessor."""

    @pytest.fixture
    def mock_config(self):
        config = MagicMock(spec=UnifiedConfigManager)
        config.get.return_value = {
            "enabled_providers": ["stripe", "paypal"],
            "fraud_detection": {"enabled": True, "threshold": 0.7},
            "retry_policy": {"max_attempts": 3, "backoff_factor": 1.5}
        }
        return config

    @pytest.fixture
    def mock_crypto(self):
        return MagicMock(spec=AdvancedCryptoSystem)

    @pytest.fixture
    def processor(self, mock_config, mock_crypto):
        with patch("core.payment.enhanced_payment_processor.PaymentProviderFactory") as mock_factory:
            # Mock provider instances
            stripe_provider = AsyncMock()
            paypal_provider = AsyncMock()
            mock_factory.create_provider.side_effect = lambda name: {
                "stripe": stripe_provider,
                "paypal": paypal_provider
            }.get(name)
            processor = EnhancedPaymentProcessor(config=mock_config, crypto=mock_crypto)
            processor._providers = {
                "stripe": stripe_provider,
                "paypal": paypal_provider
            }
            return processor

    @pytest.mark.asyncio
    async def test_process_payment_success_stripe(self, processor):
        # Arrange
        payment_data = {
            "amount": 100.0,
            "currency": "USD",
            "provider": "stripe",
            "client_id": "client_123",
            "job_id": "job_456"
        }
        processor._providers["stripe"].process_payment.return_value = {
            "status": "succeeded",
            "transaction_id": "txn_abc123",
            "fee": 2.9
        }

        # Act
        result = await processor.process_payment(payment_data)

        # Assert
        assert result["status"] == "succeeded"
        assert result["transaction_id"] == "txn_abc123"
        assert result["provider"] == "stripe"
        processor._providers["stripe"].process_payment.assert_awaited_once_with(payment_data)

    @pytest.mark.asyncio
    async def test_process_payment_fraud_detected(self, processor):
        # Arrange
        payment_data = {
            "amount": 5000.0,
            "currency": "USD",
            "provider": "paypal",
            "client_id": "client_suspicious",
            "job_id": "job_789"
        }
        with patch.object(processor._fraud_detector, "is_fraudulent", return_value=True):
            # Act & Assert
            with pytest.raises(ValueError, match="Fraud detected"):
                await processor.process_payment(payment_data)

    @pytest.mark.asyncio
    async def test_process_payment_provider_failure_fallback(self, processor):
        # Arrange
        payment_data = {
            "amount": 50.0,
            "currency": "EUR",
            "provider": "stripe",  # primary
            "client_id": "client_111",
            "job_id": "job_222"
        }
        processor._providers["stripe"].process_payment.side_effect = Exception("Stripe API down")
        processor._providers["paypal"].process_payment.return_value = {
            "status": "succeeded",
            "transaction_id": "txn_paypal_999"
        }

        # Act
        result = await processor.process_payment(payment_data)

        # Assert
        assert result["provider"] == "paypal"
        assert result["status"] == "succeeded"
        processor._providers["stripe"].process_payment.assert_awaited_once()
        processor._providers["paypal"].process_payment.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_process_payment_all_providers_fail(self, processor):
        # Arrange
        payment_data = {
            "amount": 30.0,
            "currency": "USD",
            "provider": "stripe",
            "client_id": "client_333",
            "job_id": "job_444"
        }
        processor._providers["stripe"].process_payment.side_effect = Exception("Stripe failed")
        processor._providers["paypal"].process_payment.side_effect = Exception("PayPal failed")

        # Act & Assert
        with pytest.raises(RuntimeError, match="All payment providers failed"):
            await processor.process_payment(payment_data)

    @pytest.mark.asyncio
    async def test_refund_payment_success(self, processor):
        # Arrange
        refund_data = {
            "transaction_id": "txn_abc123",
            "amount": 100.0,
            "reason": "client_request"
        }
        processor._providers["stripe"].refund_payment.return_value = {
            "status": "refunded",
            "refund_id": "ref_789"
        }

        # Act
        result = await processor.refund_payment(refund_data)

        # Assert
        assert result["status"] == "refunded"
        processor._providers["stripe"].refund_payment.assert_awaited_once_with(refund_data)

    def test_is_provider_enabled(self, processor):
        assert processor.is_provider_enabled("stripe") is True
        assert processor.is_provider_enabled("yoomoney") is False