# AI_FREELANCE_AUTOMATION/blockchain/smart_contract_manager.py
"""
Smart Contract Manager — управляет жизненным циклом смарт-контрактов
для автоматизации фриланс-сделок на блокчейне.

Поддерживает:
- Деплой контрактов (JobContract, Escrow, Reputation)
- Взаимодействие с уже задеплоенными контрактами
- Мониторинг событий (оплата, завершение, спор)
- Безопасную работу с приватными ключами через key_manager
- Автоматическое восстановление при ошибках сети или RPC

Интеграция: ethereum_integration.py, polygon_integration.py и др.
"""

import json
import logging
import time
from typing import Dict, Any, Optional, List, Union
from pathlib import Path

from core.dependency.service_locator import ServiceLocator
from core.config.unified_config_manager import UnifiedConfigManager
from core.security.key_manager import KeyManager
from core.monitoring.intelligent_monitoring_system import IntelligentMonitoringSystem
from core.security.audit_logger import AuditLogger

# Локальные импорты блокчейна
from blockchain.integrations.ethereum_integration import EthereumIntegration
from blockchain.integrations.polygon_integration import PolygonIntegration
from blockchain.integrations.binance_integration import BinanceIntegration


class SmartContractManager:
    """
    Централизованный менеджер смарт-контрактов для фриланс-автоматизации.
    Обеспечивает 100% автономность и отказоустойчивость.
    """

    SUPPORTED_CHAINS = {
        "ethereum": EthereumIntegration,
        "polygon": PolygonIntegration,
        "binance": BinanceIntegration,
    }

    CONTRACT_TEMPLATES = {
        "JobContract": "JobContract.sol",
        "PaymentEscrow": "PaymentEscrow.sol",
        "ReputationToken": "ReputationToken.sol",
        "DAOGovernance": "DAOGovernance.sol",
    }

    def __init__(
        self,
        config: Optional[UnifiedConfigManager] = None,
        key_manager: Optional[KeyManager] = None,
        monitoring: Optional[IntelligentMonitoringSystem] = None,
        audit_logger: Optional[AuditLogger] = None,
    ):
        self.logger = logging.getLogger("SmartContractManager")
        self.config = config or ServiceLocator.get("config")
        self.key_manager = key_manager or ServiceLocator.get("key_manager")
        self.monitoring = monitoring or ServiceLocator.get("monitoring")
        self.audit_logger = audit_logger or ServiceLocator.get("audit_logger")

        # Загрузка конфигурации блокчейна
        self.blockchain_config = self.config.get_section("blockchain") or {}
        self.contracts_dir = Path(__file__).parent / "contracts"
        self.deployed_contracts: Dict[str, Dict[str, Any]] = {}  # chain -> {name: info}

        # Инициализация клиентов по цепочкам
        self.chain_clients: Dict[str, Any] = {}
        self._initialize_chain_clients()

        self.logger.info("✅ SmartContractManager initialized.")

    def _initialize_chain_clients(self):
        """Инициализирует RPC-клиенты для поддерживаемых блокчейнов."""
        enabled_chains = self.blockchain_config.get("enabled_chains", [])
        for chain in enabled_chains:
            if chain not in self.SUPPORTED_CHAINS:
                self.logger.warning(f"⚠️ Chain '{chain}' not supported. Skipping.")
                continue

            try:
                client_class = self.SUPPORTED_CHAINS[chain]
                private_key = self.key_manager.get_blockchain_private_key(chain)
                rpc_url = self.blockchain_config.get(f"{chain}_rpc_url")
                if not rpc_url or not private_key:
                    raise ValueError(f"Missing RPC URL or private key for {chain}")

                self.chain_clients[chain] = client_class(
                    rpc_url=rpc_url,
                    private_key=private_key,
                    logger=self.logger,
                )
                self.logger.info(f"🔗 Initialized {chain} integration.")
            except Exception as e:
                self.logger.error(f"❌ Failed to initialize {chain}: {e}", exc_info=True)
                self.audit_logger.log_security_event(
                    event_type="blockchain_init_failure",
                    details={"chain": chain, "error": str(e)},
                )

    def get_contract_abi(self, contract_name: str) -> Dict[str, Any]:
        """Загружает ABI контракта из скомпилированного JSON (предполагается сборка вне проекта)."""
        abi_path = self.contracts_dir / f"{contract_name}.json"
        if not abi_path.exists():
            raise FileNotFoundError(f"ABI file not found: {abi_path}")

        with open(abi_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("abi", data)  # поддержка как чистого ABI, так и полного artifact

    def deploy_contract(
        self,
        chain: str,
        contract_name: str,
        constructor_args: Optional[List[Any]] = None,
        gas_limit: Optional[int] = None,
        max_retries: int = 3,
    ) -> Dict[str, Any]:
        """
        Деплоит смарт-контракт в указанную сеть.
        Возвращает адрес и транзакцию.
        """
        if chain not in self.chain_clients:
            raise ValueError(f"Chain '{chain}' not initialized or unsupported.")

        if contract_name not in self.CONTRACT_TEMPLATES:
            raise ValueError(f"Unknown contract: {contract_name}")

        client = self.chain_clients[chain]
        abi = self.get_contract_abi(contract_name)
        bytecode_path = self.contracts_dir / f"{contract_name}.bin"

        if not bytecode_path.exists():
            raise FileNotFoundError(f"Bytecode not found: {bytecode_path}")

        with open(bytecode_path, "r", encoding="utf-8") as f:
            bytecode = f.read().strip()

        for attempt in range(1, max_retries + 1):
            try:
                tx_hash = client.deploy_contract(
                    abi=abi,
                    bytecode=bytecode,
                    constructor_args=constructor_args or [],
                    gas_limit=gas_limit,
                )
                receipt = client.wait_for_transaction(tx_hash)
                contract_address = receipt["contractAddress"]

                # Сохраняем в памяти и логируем
                contract_info = {
                    "name": contract_name,
                    "address": contract_address,
                    "tx_hash": tx_hash,
                    "chain": chain,
                    "deployed_at": time.time(),
                    "constructor_args": constructor_args,
                }
                self.deployed_contracts.setdefault(chain, {})[contract_name] = contract_info

                self.audit_logger.log_security_event(
                    event_type="contract_deployed",
                    details=contract_info,
                )
                self.logger.info(f"✅ Deployed {contract_name} on {chain} at {contract_address}")
                return contract_info

            except Exception as e:
                self.logger.warning(
                    f"⚠️ Attempt {attempt}/{max_retries} failed for {contract_name} on {chain}: {e}"
                )
                if attempt == max_retries:
                    self.audit_logger.log_security_event(
                        event_type="contract_deployment_failed",
                        details={
                            "chain": chain,
                            "contract": contract_name,
                            "error": str(e),
                            "attempts": max_retries,
                        },
                    )
                    raise RuntimeError(f"Deployment failed after {max_retries} attempts") from e
                time.sleep(2 ** attempt)  # экспоненциальная задержка

    def call_contract_function(
        self,
        chain: str,
        contract_address: str,
        function_name: str,
        args: Optional[List[Any]] = None,
        sender: Optional[str] = None,
    ) -> Any:
        """Вызывает view/pure функцию контракта (без изменения состояния)."""
        if chain not in self.chain_clients:
            raise ValueError(f"Chain '{chain}' not available.")
        return self.chain_clients[chain].call_function(contract_address, function_name, args or [])

    def send_contract_transaction(
        self,
        chain: str,
        contract_address: str,
        function_name: str,
        args: Optional[List[Any]] = None,
        value: int = 0,
        gas_limit: Optional[int] = None,
    ) -> str:
        """Отправляет транзакцию в контракт (изменяет состояние)."""
        if chain not in self.chain_clients:
            raise ValueError(f"Chain '{chain}' not available.")
        return self.chain_clients[chain].send_transaction(
            contract_address, function_name, args or [], value=value, gas_limit=gas_limit
        )

    def listen_to_events(
        self,
        chain: str,
        contract_address: str,
        event_name: str,
        handler: callable,
        from_block: Union[int, str] = "latest",
    ):
        """Подписывается на события контракта (асинхронно через отдельный поток/воркер)."""
        if chain not in self.chain_clients:
            raise ValueError(f"Chain '{chain}' not available.")
        self.chain_clients[chain].subscribe_to_event(
            contract_address, event_name, handler, from_block
        )

    def get_deployed_contract(self, chain: str, contract_name: str) -> Optional[Dict[str, Any]]:
        """Возвращает информацию о ранее задеплоенном контракте."""
        return self.deployed_contracts.get(chain, {}).get(contract_name)

    def health_check(self) -> Dict[str, bool]:
        """Проверяет доступность всех подключенных блокчейн-клиентов."""
        status = {}
        for chain, client in self.chain_clients.items():
            try:
                client.get_block_number()
                status[chain] = True
            except Exception as e:
                self.logger.error(f"Health check failed for {chain}: {e}")
                status[chain] = False
        return status