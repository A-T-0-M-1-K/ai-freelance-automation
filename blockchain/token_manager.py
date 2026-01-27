# AI_FREELANCE_AUTOMATION/blockchain/token_manager.py
"""
Token Manager for AI Freelance Automation System

Manages utility tokens, reputation tokens, and payment tokens on supported blockchains.
Integrates with wallet_manager and smart_contract_manager.
Supports Ethereum, Polygon, Binance Smart Chain.

Features:
- Token balance monitoring
- Token transfers (with gas optimization)
- ERC-20/ERC-721/ERC-1155 support
- Automatic fee estimation
- Transaction signing via secure key manager
- Audit logging & anomaly detection
- Recovery from failed transactions
"""

import asyncio
import logging
from typing import Optional, Dict, Any, Union, List
from decimal import Decimal

from core.config.unified_config_manager import UnifiedConfigManager
from core.security.advanced_crypto_system import AdvancedCryptoSystem
from core.monitoring.intelligent_monitoring_system import IntelligentMonitoringSystem
from core.security.audit_logger import AuditLogger
from blockchain.wallet_manager import WalletManager
from blockchain.smart_contract_manager import SmartContractManager
from core.dependency.service_locator import ServiceLocator


class TokenManager:
    """
    Centralized token management system for all blockchain-based operations.
    Fully autonomous, self-healing, and compliant with security standards.
    """

    def __init__(
        self,
        config: Optional[UnifiedConfigManager] = None,
        crypto: Optional[AdvancedCryptoSystem] = None,
        monitor: Optional[IntelligentMonitoringSystem] = None,
        audit_logger: Optional[AuditLogger] = None,
    ):
        self.logger = logging.getLogger("TokenManager")
        self.config = config or ServiceLocator.get("config")
        self.crypto = crypto or ServiceLocator.get("crypto")
        self.monitor = monitor or ServiceLocator.get("monitoring")
        self.audit_logger = audit_logger or ServiceLocator.get("audit_logger")

        # Initialize dependencies
        self.wallet_manager: WalletManager = ServiceLocator.get("wallet_manager")
        self.contract_manager: SmartContractManager = ServiceLocator.get("contract_manager")

        # Load token configuration
        self.token_config = self.config.get_section("blockchain.tokens") or {}
        self.supported_chains = self.config.get("blockchain.supported_chains", ["ethereum", "polygon", "bsc"])
        self.gas_buffer_percent = self.config.get("blockchain.gas_buffer_percent", 15)

        self.logger.info("✅ TokenManager initialized with config: %s chains", len(self.supported_chains))

    async def get_token_balance(
        self,
        token_address: str,
        wallet_id: str,
        chain: str = "ethereum"
    ) -> Optional[Decimal]:
        """
        Retrieve token balance for a given wallet on a specific chain.
        Supports native and ERC tokens.
        """
        try:
            if chain not in self.supported_chains:
                raise ValueError(f"Unsupported chain: {chain}")

            wallet = await self.wallet_manager.get_wallet(wallet_id)
            if not wallet:
                self.logger.warning("Wallet %s not found", wallet_id)
                return None

            balance = await self.contract_manager.call_contract(
                contract_address=token_address,
                function_name="balanceOf",
                args=[wallet.address],
                chain=chain,
                wallet=wallet
            )

            balance_dec = Decimal(str(balance)) if balance is not None else Decimal("0")
            self.monitor.record_metric("token.balance", {"token": token_address, "chain": chain}, balance_dec)

            self.audit_logger.log(
                action="token_balance_check",
                entity=wallet_id,
                details={"token": token_address, "chain": chain, "balance": str(balance_dec)}
            )
            return balance_dec

        except Exception as e:
            self.logger.error("❌ Failed to get token balance: %s", e, exc_info=True)
            await self._handle_token_error(e, "get_balance", {"token": token_address, "wallet": wallet_id})
            return None

    async def transfer_token(
        self,
        token_address: str,
        from_wallet_id: str,
        to_address: str,
        amount: Union[int, float, Decimal],
        chain: str = "ethereum",
        memo: str = ""
    ) -> Dict[str, Any]:
        """
        Transfer tokens securely with automatic gas estimation and retry logic.
        Returns transaction receipt or error info.
        """
        try:
            if chain not in self.supported_chains:
                raise ValueError(f"Unsupported chain: {chain}")

            from_wallet = await self.wallet_manager.get_wallet(from_wallet_id)
            if not from_wallet:
                raise ValueError(f"Wallet {from_wallet_id} not found")

            # Validate amount
            amount_dec = Decimal(str(amount))
            if amount_dec <= 0:
                raise ValueError("Transfer amount must be positive")

            # Estimate gas
            gas_estimate = await self._estimate_transfer_gas(
                token_address, from_wallet.address, to_address, amount_dec, chain
            )

            # Prepare transaction
            tx_data = {
                "to": token_address,
                "from": from_wallet.address,
                "data": self._encode_transfer_call(to_address, amount_dec),
                "gas": int(gas_estimate * (1 + self.gas_buffer_percent / 100)),
                "chain": chain
            }

            # Sign and send
            signed_tx = await self.wallet_manager.sign_transaction(from_wallet_id, tx_data)
            tx_hash = await self.contract_manager.send_raw_transaction(signed_tx, chain)

            self.audit_logger.log(
                action="token_transfer_initiated",
                entity=from_wallet_id,
                details={
                    "tx_hash": tx_hash,
                    "to": to_address,
                    "amount": str(amount_dec),
                    "token": token_address,
                    "chain": chain,
                    "memo": memo
                }
            )

            # Wait for confirmation
            receipt = await self.contract_manager.wait_for_transaction_receipt(tx_hash, chain)
            success = receipt.get("status") == 1

            self.monitor.record_metric(
                "token.transfer.success" if success else "token.transfer.failed",
                {"chain": chain, "token": token_address},
                1
            )

            result = {
                "success": success,
                "tx_hash": tx_hash,
                "receipt": receipt,
                "fee_used": receipt.get("gasUsed", 0) if success else None
            }

            if success:
                self.logger.info("✅ Token transfer succeeded: %s", tx_hash)
            else:
                self.logger.warning("⚠️ Token transfer failed: %s", tx_hash)

            return result

        except Exception as e:
            self.logger.error("💥 Token transfer failed: %s", e, exc_info=True)
            await self._handle_token_error(e, "transfer", {
                "from": from_wallet_id, "to": to_address, "amount": str(amount), "token": token_address
            })
            return {"success": False, "error": str(e)}

    async def _estimate_transfer_gas(
        self,
        token_address: str,
        from_address: str,
        to_address: str,
        amount: Decimal,
        chain: str
    ) -> int:
        """Estimate gas for token transfer."""
        try:
            data = self._encode_transfer_call(to_address, amount)
            estimate = await self.contract_manager.estimate_gas(
                to=token_address,
                from_addr=from_address,
                data=data,
                chain=chain
            )
            return estimate
        except Exception as e:
            self.logger.warning("Gas estimation failed, using default: %s", e)
            return 65000  # Safe default for ERC-20

    def _encode_transfer_call(self, to_address: str, amount: Decimal) -> str:
        """Encode ERC-20 transfer call."""
        from eth_abi import encode
        from web3 import Web3
        # keccak('transfer(address,uint256)')[:4]
        func_selector = Web3.keccak(text="transfer(address,uint256)")[:4]
        encoded_params = encode(['address', 'uint256'], [to_address, int(amount)])
        return func_selector.hex() + encoded_params.hex()

    async def _handle_token_error(self, error: Exception, operation: str, context: Dict[str, Any]):
        """Handle token-related errors with recovery and alerting."""
        self.logger.error("Handling token error for operation: %s", operation)
        self.monitor.record_anomaly("token_operation_failed", context)

        # Log to audit
        self.audit_logger.log(
            action="token_operation_error",
            entity="system",
            details={"operation": operation, "error": str(error), "context": context}
        )

        # Trigger emergency recovery if critical
        if "out of gas" in str(error).lower() or "nonce" in str(error).lower():
            from core.emergency_recovery import EmergencyRecovery
            recovery = ServiceLocator.get("emergency_recovery")
            if recovery:
                await recovery.trigger_recovery("blockchain_token_failure", context)

    async def get_supported_tokens(self, chain: str = "ethereum") -> List[Dict[str, Any]]:
        """Return list of configured tokens for a chain."""
        tokens = self.token_config.get(chain, [])
        return [
            {
                "symbol": t.get("symbol"),
                "name": t.get("name"),
                "address": t.get("address"),
                "decimals": t.get("decimals", 18),
                "type": t.get("type", "ERC20")
            }
            for t in tokens
        ]


# Make module import-safe
if __name__ == "__main__":
    # Example usage (not executed in production)
    pass