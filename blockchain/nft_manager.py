# AI_FREELANCE_AUTOMATION/blockchain/nft_manager.py
"""
NFT Manager — управляет выпуском, передачей и верификацией NFT,
связанных с выполненными заказами, репутацией фрилансера или цифровыми активами.
Интегрируется с wallet_manager и smart_contract_manager.
Поддерживает Ethereum, Polygon и другие EVM-совместимые сети.
"""

import logging
import asyncio
from typing import Dict, Any, Optional, List
from pathlib import Path

from core.config.unified_config_manager import UnifiedConfigManager
from core.security.advanced_crypto_system import AdvancedCryptoSystem
from core.monitoring.intelligent_monitoring_system import IntelligentMonitoringSystem
from blockchain.wallet_manager import WalletManager
from blockchain.smart_contract_manager import SmartContractManager
from blockchain.integrations.ethereum_integration import EthereumIntegration
from blockchain.integrations.polygon_integration import PolygonIntegration

logger = logging.getLogger("NFTManager")


class NFTMetadata:
    """Структура метаданных NFT в соответствии с ERC-721/ERC-1155."""
    def __init__(
        self,
        name: str,
        description: str,
        image_url: str,
        external_url: str,
        attributes: List[Dict[str, Any]],
        job_id: str,
        client_id: str,
        freelancer_address: str,
        timestamp: int
    ):
        self.name = name
        self.description = description
        self.image_url = image_url
        self.external_url = external_url
        self.attributes = attributes
        self.job_id = job_id
        self.client_id = client_id
        self.freelancer_address = freelancer_address
        self.timestamp = timestamp

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "image": self.image_url,
            "external_url": self.external_url,
            "attributes": self.attributes,
            "job_id": self.job_id,
            "client_id": self.client_id,
            "freelancer_address": self.freelancer_address,
            "timestamp": self.timestamp
        }


class NFTManager:
    """
    Управляет жизненным циклом NFT:
    - Генерация метаданных на основе завершенного заказа
    - Загрузка метаданных в IPFS или Arweave
    - Монетизация через смарт-контракт
    - Передача клиенту
    - Верификация подлинности
    """

    SUPPORTED_CHAINS = {"ethereum", "polygon"}

    def __init__(
        self,
        config: UnifiedConfigManager,
        crypto: AdvancedCryptoSystem,
        monitoring: IntelligentMonitoringSystem,
        wallet_manager: WalletManager,
        contract_manager: SmartContractManager
    ):
        self.config = config
        self.crypto = crypto
        self.monitoring = monitoring
        self.wallet_manager = wallet_manager
        self.contract_manager = contract_manager

        self._ipfs_gateway = self.config.get("blockchain.ipfs_gateway", "https://ipfs.io/ipfs/")
        self._metadata_storage = self.config.get("blockchain.metadata_storage", "ipfs")
        self._default_chain = self.config.get("blockchain.default_chain", "polygon")

        # Инициализация интеграций
        self._integrations: Dict[str, Any] = {}
        if "ethereum" in self.SUPPORTED_CHAINS:
            self._integrations["ethereum"] = EthereumIntegration(config, crypto)
        if "polygon" in self.SUPPORTED_CHAINS:
            self._integrations["polygon"] = PolygonIntegration(config, crypto)

        logger.info("✅ NFTManager initialized")

    async def generate_nft_metadata(
        self,
        job_id: str,
        client_id: str,
        deliverable_hash: str,
        job_type: str,
        price_usd: float,
        completion_date: int
    ) -> NFTMetadata:
        """Генерирует стандартные метаданные NFT для завершенного заказа."""
        try:
            attributes = [
                {"trait_type": "Job Type", "value": job_type},
                {"trait_type": "Price (USD)", "value": price_usd},
                {"trait_type": "Completion Date", "value": completion_date},
                {"trait_type": "Deliverable Hash", "value": deliverable_hash[:16]},
                {"trait_type": "Chain", "value": self._default_chain.upper()}
            ]

            metadata = NFTMetadata(
                name=f"Freelance Work #{job_id}",
                description=f"Verified delivery of freelance work for client {client_id}. "
                            f"Type: {job_type}. Completed on {completion_date}.",
                image_url="https://ai-freelance.app/nft/default_freelance_art.png",
                external_url=f"https://ai-freelance.app/jobs/{job_id}",
                attributes=attributes,
                job_id=job_id,
                client_id=client_id,
                freelancer_address=await self.wallet_manager.get_primary_address(),
                timestamp=completion_date
            )
            logger.debug(f"NFT metadata generated for job {job_id}")
            return metadata
        except Exception as e:
            logger.error(f"❌ Failed to generate NFT metadata for job {job_id}: {e}", exc_info=True)
            raise

    async def store_metadata(self, metadata: NFTMetadata) -> str:
        """Сохраняет метаданные в распределенное хранилище (IPFS по умолчанию)."""
        if self._metadata_storage != "ipfs":
            raise NotImplementedError("Only IPFS storage is supported at this time.")

        # Сериализуем метаданные в JSON
        import json
        metadata_json = json.dumps(metadata.to_dict(), indent=2, ensure_ascii=False)

        # Сохраняем временно
        temp_path = Path("data/temp") / f"nft_metadata_{metadata.job_id}.json"
        temp_path.parent.mkdir(parents=True, exist_ok=True)
        with open(temp_path, "w", encoding="utf-8") as f:
            f.write(metadata_json)

        # Загружаем в IPFS через интеграцию (пример через внешний вызов)
        # В реальной системе здесь будет вызов к pinata, nft.storage или локальному IPFS-ноду
        cid = await self._mock_ipfs_upload(temp_path)
        ipfs_url = f"{self._ipfs_gateway}{cid}"

        logger.info(f"📁 NFT metadata stored at {ipfs_url}")
        return ipfs_url

    async def _mock_ipfs_upload(self, file_path: Path) -> str:
        """Мок-загрузка в IPFS. Заменить на реальную интеграцию."""
        # В продакшене: вызов API Pinata/NFT.Storage/IPFS Cluster
        import hashlib
        with open(file_path, "rb") as f:
            digest = hashlib.sha256(f.read()).hexdigest()
        # CIDv0-like mock
        return f"Qm{digest[:58]}"

    async def mint_nft(
        self,
        job_id: str,
        client_wallet: str,
        metadata_uri: str,
        chain: str = None
    ) -> Dict[str, Any]:
        """Выпускает NFT через смарт-контракт и передает клиенту."""
        chain = chain or self._default_chain
        if chain not in self.SUPPORTED_CHAINS:
            raise ValueError(f"Unsupported chain: {chain}")

        try:
            contract = await self.contract_manager.get_contract("NFT", chain)
            tx_hash = await contract.functions.mintTo(
                client_wallet,
                metadata_uri
            ).transact({
                'from': await self.wallet_manager.get_primary_address(),
                'gas': 300000,
                'gasPrice': await self._get_gas_price(chain)
            })

            receipt = await self._wait_for_transaction(chain, tx_hash)
            token_id = self._extract_token_id(receipt)

            result = {
                "tx_hash": tx_hash.hex(),
                "token_id": token_id,
                "chain": chain,
                "owner": client_wallet,
                "metadata_uri": metadata_uri,
                "status": "minted"
            }

            logger.info(f"🎨 NFT minted for job {job_id} → Token ID: {token_id} on {chain}")
            await self.monitoring.log_metric("nft_minted", 1, tags={"chain": chain, "job_id": job_id})
            return result

        except Exception as e:
            logger.error(f"💥 NFT minting failed for job {job_id}: {e}", exc_info=True)
            await self.monitoring.log_metric("nft_mint_failed", 1, tags={"job_id": job_id})
            raise

    async def _get_gas_price(self, chain: str) -> int:
        integration = self._integrations.get(chain)
        if not integration:
            raise RuntimeError(f"No integration for chain {chain}")
        return await integration.get_gas_price()

    async def _wait_for_transaction(self, chain: str, tx_hash: bytes, timeout: int = 120):
        integration = self._integrations.get(chain)
        return await integration.wait_for_transaction_receipt(tx_hash, timeout=timeout)

    def _extract_token_id(self, receipt) -> int:
        # Пример извлечения из логов (зависит от ABI контракта)
        for log in receipt.get("logs", []):
            if len(log.get("topics", [])) > 1:
                # ERC-721 Transfer event: topic[3] = tokenId
                return int(log["topics"][3].hex(), 16)
        raise RuntimeError("Token ID not found in transaction receipt")

    async def verify_nft_ownership(
        self,
        token_id: int,
        expected_owner: str,
        chain: str = None
    ) -> bool:
        """Проверяет, принадлежит ли NFT указанному владельцу."""
        chain = chain or self._default_chain
        contract = await self.contract_manager.get_contract("NFT", chain)
        owner = await contract.functions.ownerOf(token_id).call()
        return owner.lower() == expected_owner.lower()

    async def get_nft_metadata_uri(self, token_id: int, chain: str = None) -> str:
        """Возвращает URI метаданных NFT."""
        chain = chain or self._default_chain
        contract = await self.contract_manager.get_contract("NFT", chain)
        return await contract.functions.tokenURI(token_id).call()


# Экспорт для DI
__all__ = ["NFTManager", "NFTMetadata"]