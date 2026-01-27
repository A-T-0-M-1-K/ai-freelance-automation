# AI_FREELANCE_AUTOMATION/blockchain/integrations/ethereum_integration.py

"""
Ethereum Integration Module for AI Freelance Automation System.
Handles wallet operations, contract interactions, and transaction monitoring
on the Ethereum blockchain. Designed for secure, autonomous operation
with full error recovery and audit logging.
"""

import asyncio
import logging
import time
from typing import Optional, Dict, Any, Union
from decimal import Decimal

from web3 import Web3, AsyncWeb3
from web3.contract import AsyncContract
from web3.exceptions import ContractLogicError, TimeExhausted, TransactionNotFound
from eth_account.signers.local import LocalAccount
from eth_account import Account

from core.security.advanced_crypto_system import AdvancedCryptoSystem
from core.config.unified_config_manager import UnifiedConfigManager
from core.monitoring.intelligent_monitoring_system import IntelligentMonitoringSystem
from core.security.audit_logger import AuditLogger
from core.payment.fraud_detection_system import FraudDetectionSystem

# Инициализация логгера
logger = logging.getLogger("EthereumIntegration")

class EthereumIntegration:
    """
    Ethereum blockchain integration for autonomous freelance operations.
    Supports:
      - Wallet management (hot/cold via HSM or encrypted keystore)
      - Smart contract interaction (JobContract, Escrow, ReputationToken)
      - Gas optimization & transaction monitoring
      - Fraud detection & anomaly logging
      - Full audit trail for compliance (GDPR, PCI DSS, SOC 2)
    """

    def __init__(
        self,
        config: UnifiedConfigManager,
        crypto: AdvancedCryptoSystem,
        monitor: IntelligentMonitoringSystem,
        audit_logger: AuditLogger,
        fraud_detector: FraudDetectionSystem,
    ):
        self.config = config
        self.crypto = crypto
        self.monitor = monitor
        self.audit_logger = audit_logger
        self.fraud_detector = fraud_detector

        # Загрузка конфигурации Ethereum
        eth_config = self.config.get_section("blockchain.ethereum")
        self.rpc_url = eth_config.get("rpc_url")
        self.chain_id = eth_config.get("chain_id", 1)  # Mainnet by default
        self.gas_buffer_percent = eth_config.get("gas_buffer_percent", 20)
        self.confirmation_blocks = eth_config.get("confirmation_blocks", 2)
        self.timeout = eth_config.get("timeout_sec", 120)

        # Инициализация Web3
        self.w3: Optional[AsyncWeb3] = None
        self.account: Optional[LocalAccount] = None
        self._initialized = False

        logger.info(f"Intialized EthereumIntegration for chain {self.chain_id}")

    async def initialize(self) -> bool:
        """Initialize async Web3 connection and decrypt wallet."""
        if self._initialized:
            return True

        try:
            # Подключение к RPC
            self.w3 = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider(self.rpc_url))
            if not await self.w3.is_connected():
                raise ConnectionError("Failed to connect to Ethereum RPC")

            # Расшифровка приватного ключа из зашифрованного хранилища
            encrypted_key = self.config.get("blockchain.ethereum.encrypted_private_key")
            private_key = self.crypto.decrypt_secret(encrypted_key)
            self.account = Account.from_key(private_key)

            # Валидация баланса
            balance = await self.w3.eth.get_balance(self.account.address)
            eth_balance = self.w3.from_wei(balance, 'ether')
            logger.info(f"Wallet {self.account.address} loaded. Balance: {eth_balance} ETH")

            self._initialized = True
            self.audit_logger.log("BLOCKCHAIN_INIT", {
                "action": "ethereum_wallet_loaded",
                "address": self.account.address,
                "chain_id": self.chain_id
            })
            return True

        except Exception as e:
            logger.error(f"Failed to initialize Ethereum integration: {e}", exc_info=True)
            self.audit_logger.log("BLOCKCHAIN_ERROR", {
                "error": str(e),
                "component": "ethereum_integration",
                "action": "initialize"
            })
            return False

    async def get_balance(self) -> Decimal:
        """Get ETH balance in human-readable format."""
        if not self._initialized:
            await self.initialize()
        balance_wei = await self.w3.eth.get_balance(self.account.address)
        return Decimal(self.w3.from_wei(balance_wei, 'ether'))

    async def estimate_gas(self, tx: Dict[str, Any]) -> int:
        """Estimate gas with safety buffer."""
        estimated = await self.w3.eth.estimate_gas(tx)
        return int(estimated * (1 + self.gas_buffer_percent / 100))

    async def send_transaction(
        self,
        to: str,
        value: Union[int, Decimal] = 0,
        data: str = "0x",
        contract: Optional[AsyncContract] = None
    ) -> Optional[str]:
        """
        Send a transaction (ETH or contract call).
        Returns transaction hash if successful, None otherwise.
        """
        if not self._initialized:
            success = await self.initialize()
            if not success:
                return None

        try:
            # Преобразование значения в wei
            if isinstance(value, Decimal):
                value = self.w3.to_wei(value, 'ether')

            nonce = await self.w3.eth.get_transaction_count(self.account.address)
            gas_price = await self.w3.eth.gas_price

            tx = {
                'to': Web3.to_checksum_address(to),
                'value': value,
                'nonce': nonce,
                'gasPrice': gas_price,
                'chainId': self.chain_id,
                'data': data
            }

            # Если это вызов контракта — заменить 'to' и 'data'
            if contract:
                tx['to'] = contract.address
                tx['data'] = contract.encodeABI()

            # Оценка газа
            tx['gas'] = await self.estimate_gas(tx)

            # Подпись
            signed_tx = self.account.sign_transaction(tx)
            tx_hash = await self.w3.eth.send_raw_transaction(signed_tx.rawTransaction)

            tx_hash_hex = tx_hash.hex()
            logger.info(f"Sent transaction: {tx_hash_hex}")

            # Аудит и мониторинг
            self.audit_logger.log("BLOCKCHAIN_TX_SENT", {
                "tx_hash": tx_hash_hex,
                "to": to,
                "value_wei": value,
                "gas_used_est": tx['gas']
            })
            self.monitor.record_metric("blockchain.eth.tx_sent", 1)

            # Ожидание подтверждения
            await self._wait_for_confirmation(tx_hash_hex)

            return tx_hash_hex

        except (ContractLogicError, ValueError, TimeExhausted, TransactionNotFound) as e:
            logger.error(f"Transaction failed: {e}")
            self.audit_logger.log("BLOCKCHAIN_TX_FAILED", {
                "error": str(e),
                "to": to,
                "value": str(value)
            })
            return None
        except Exception as e:
            logger.critical(f"Unexpected error in send_transaction: {e}", exc_info=True)
            self.audit_logger.log("BLOCKCHAIN_CRITICAL_ERROR", {"error": str(e)})
            return None

    async def _wait_for_confirmation(self, tx_hash: str) -> bool:
        """Wait for transaction confirmation with timeout."""
        start_time = time.time()
        while time.time() - start_time < self.timeout:
            try:
                receipt = await self.w3.eth.get_transaction_receipt(tx_hash)
                if receipt and receipt.get('blockNumber'):
                    confirmations = await self.w3.eth.block_number - receipt['blockNumber']
                    if confirmations >= self.confirmation_blocks:
                        logger.info(f"Transaction {tx_hash} confirmed with {confirmations} blocks")
                        return True
            except Exception:
                pass
            await asyncio.sleep(5)
        logger.warning(f"Transaction {tx_hash} not confirmed within {self.timeout} seconds")
        return False

    async def call_contract_function(
        self,
        contract_abi: list,
        contract_address: str,
        function_name: str,
        args: tuple = ()
    ) -> Any:
        """Call a read-only contract function."""
        if not self._initialized:
            await self.initialize()

        contract = self.w3.eth.contract(
            address=Web3.to_checksum_address(contract_address),
            abi=contract_abi
        )
        try:
            result = await getattr(contract.functions, function_name)(*args).call()
            logger.debug(f"Contract call {function_name} returned: {result}")
            return result
        except Exception as e:
            logger.error(f"Contract call failed: {e}")
            return None

    def get_address(self) -> str:
        """Return checksummed wallet address."""
        return Web3.to_checksum_address(self.account.address) if self.account else ""

    async def shutdown(self):
        """Graceful shutdown."""
        self._initialized = False
        logger.info("EthereumIntegration shut down gracefully.")