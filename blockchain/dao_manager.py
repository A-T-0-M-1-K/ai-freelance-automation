# AI_FREELANCE_AUTOMATION/blockchain/dao_manager.py
"""
DAO Manager — управляет децентрализованной автономной организацией (DAO),
которая может регулировать поведение системы на основе голосований,
например: изменение стратегии ставок, выбор новых платформ, обновление AI-моделей.

Интегрируется с:
- wallet_manager (для подписания транзакций)
- smart_contract_manager (для взаимодействия с контрактами)
- core.monitoring (для логирования решений)
- core.config (для применения утверждённых изменений)

Поддерживает:
- Создание предложений (proposals)
- Голосование (voting)
- Исполнение решений (execution)
- Аудит всех действий
"""

import logging
import asyncio
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from datetime import datetime, timedelta

# Локальные импорты (без циклических зависимостей)
from .smart_contract_manager import SmartContractManager
from .wallet_manager import WalletManager
from ..core.config.unified_config_manager import UnifiedConfigManager
from ..core.security.audit_logger import AuditLogger
from ..core.monitoring.intelligent_monitoring_system import MetricsCollector

# Настройка логгера
logger = logging.getLogger("Blockchain.DAOManager")


@dataclass
class Proposal:
    """Предложение в DAO."""
    id: str
    title: str
    description: str
    proposer: str  # адрес кошелька
    created_at: datetime
    expires_at: datetime
    votes_for: int
    votes_against: int
    executed: bool = False
    metadata: Dict[str, Any] = None  # например: {"config_path": "automation.bid_strategy", "new_value": "aggressive"}


class DAOManager:
    """
    Управляет жизненным циклом DAO-предложений и автоматическим исполнением решений.
    Работает асинхронно и безопасно.
    """

    def __init__(
        self,
        contract_manager: SmartContractManager,
        wallet_manager: WalletManager,
        config_manager: UnifiedConfigManager,
        audit_logger: AuditLogger,
        metrics_collector: MetricsCollector,
        dao_contract_address: str,
        min_quorum: float = 0.51,  # минимум 51% голосов
        proposal_duration_hours: int = 72,  # предложения живут 3 дня
    ):
        self.contract_manager = contract_manager
        self.wallet_manager = wallet_manager
        self.config_manager = config_manager
        self.audit_logger = audit_logger
        self.metrics = metrics_collector

        self.dao_address = dao_contract_address
        self.min_quorum = min_quorum
        self.proposal_duration = timedelta(hours=proposal_duration_hours)

        self._proposals: Dict[str, Proposal] = {}
        self._running = False
        self._background_task: Optional[asyncio.Task] = None

        logger.info("Intialized DAO Manager for contract %s", self.dao_address)

    async def start(self):
        """Запускает фоновый мониторинг предложений."""
        if self._running:
            return
        self._running = True
        self._background_task = asyncio.create_task(self._monitor_proposals())
        logger.info("DAO Manager background monitoring started")

    async def stop(self):
        """Останавливает мониторинг."""
        self._running = False
        if self._background_task:
            self._background_task.cancel()
            try:
                await self._background_task
            except asyncio.CancelledError:
                pass
        logger.info("DAO Manager stopped")

    async def create_proposal(
        self,
        title: str,
        description: str,
        metadata: Dict[str, Any],
        proposer_address: Optional[str] = None
    ) -> str:
        """
        Создаёт новое предложение в блокчейне.
        Возвращает ID предложения.
        """
        if not proposer_address:
            proposer_address = self.wallet_manager.get_default_address()

        proposal_id = f"prop_{int(datetime.utcnow().timestamp())}_{hash(title) % 10000:04d}"
        expires_at = datetime.utcnow() + self.proposal_duration

        proposal = Proposal(
            id=proposal_id,
            title=title,
            description=description,
            proposer=proposer_address,
            created_at=datetime.utcnow(),
            expires_at=expires_at,
            votes_for=0,
            votes_against=0,
            metadata=metadata
        )

        # Отправляем транзакцию в блокчейн
        try:
            tx_hash = await self.contract_manager.call_contract(
                contract_address=self.dao_address,
                method="createProposal",
                args=[title, description, str(metadata), expires_at.isoformat()],
                from_address=proposer_address,
                sign_with=self.wallet_manager.sign_transaction
            )
            logger.info("NewProposal created: %s (tx: %s)", proposal_id, tx_hash)
            await self.audit_logger.log(
                action="dao_proposal_created",
                actor=proposer_address,
                details={"proposal_id": proposal_id, "tx_hash": tx_hash}
            )
            self._proposals[proposal_id] = proposal
            self.metrics.increment("dao.proposals.created")
            return proposal_id
        except Exception as e:
            logger.error("Failed to create DAO proposal: %s", e)
            self.metrics.increment("dao.proposals.failed")
            raise

    async def vote_on_proposal(self, proposal_id: str, support: bool) -> str:
        """Голосует за/против предложения от имени текущего кошелька."""
        if proposal_id not in self._proposals:
            raise ValueError(f"Proposal {proposal_id} not found")

        address = self.wallet_manager.get_default_address()
        try:
            tx_hash = await self.contract_manager.call_contract(
                contract_address=self.dao_address,
                method="vote",
                args=[proposal_id, support],
                from_address=address,
                sign_with=self.wallet_manager.sign_transaction
            )
            logger.info("Voted on proposal %s: %s (tx: %s)", proposal_id, support, tx_hash)
            await self.audit_logger.log(
                action="dao_vote_cast",
                actor=address,
                details={"proposal_id": proposal_id, "support": support, "tx_hash": tx_hash}
            )
            self.metrics.increment("dao.votes.cast")
            return tx_hash
        except Exception as e:
            logger.error("Failed to vote on proposal %s: %s", proposal_id, e)
            raise

    async def _monitor_proposals(self):
        """Фоновая задача: проверяет истёкшие предложения и исполняет их при успехе."""
        while self._running:
            try:
                now = datetime.utcnow()
                for prop_id, prop in list(self._proposals.items()):
                    if prop.executed:
                        continue
                    if now >= prop.expires_at:
                        total_votes = prop.votes_for + prop.votes_against
                        if total_votes == 0:
                            logger.warning("Proposal %s expired with no votes", prop_id)
                            continue

                        approval_rate = prop.votes_for / total_votes
                        if approval_rate >= self.min_quorum:
                            await self._execute_proposal(prop)
                        else:
                            logger.info("Proposal %s rejected (%.2f%% approval)", prop_id, approval_rate * 100)
                            self.metrics.increment("dao.proposals.rejected")

                # Обновляем данные из блокчейна (в реальности — через события или RPC)
                await self._sync_proposals_from_chain()

                await asyncio.sleep(60)  # проверка каждую минуту
            except Exception as e:
                logger.exception("Error in DAO monitoring loop: %s", e)
                await asyncio.sleep(30)

    async def _sync_proposals_from_chain(self):
        """Синхронизирует состояние предложений с блокчейном (упрощённо)."""
        # В реальной системе здесь будет вызов view-функций контракта
        # или прослушивание событий через Web3.py
        pass

    async def _execute_proposal(self, proposal: Proposal):
        """Исполняет утверждённое предложение."""
        try:
            logger.info("Executing approved DAO proposal: %s", proposal.id)
            await self.audit_logger.log(
                action="dao_proposal_executing",
                actor="system",
                details={"proposal_id": proposal.id, "metadata": proposal.metadata}
            )

            # Пример: применение нового значения в конфигурации
            if proposal.metadata and "config_path" in proposal.metadata:
                config_path = proposal.metadata["config_path"]
                new_value = proposal.metadata["new_value"]
                self.config_manager.set_nested(config_path, new_value)
                logger.info("Applied config change from DAO: %s = %s", config_path, new_value)

            # Другие типы действий можно расширить через плагины или матчинг по типу

            proposal.executed = True
            self.metrics.increment("dao.proposals.executed")
            await self.audit_logger.log(
                action="dao_proposal_executed",
                actor="system",
                details={"proposal_id": proposal.id}
            )

        except Exception as e:
            logger.error("Failed to execute DAO proposal %s: %s", proposal.id, e)
            await self.audit_logger.log(
                action="dao_proposal_execution_failed",
                actor="system",
                details={"proposal_id": proposal.id, "error": str(e)}
            )
            self.metrics.increment("dao.proposals.execution_failed")

    def get_proposal(self, proposal_id: str) -> Optional[Proposal]:
        return self._proposals.get(proposal_id)

    def list_active_proposals(self) -> List[Proposal]:
        now = datetime.utcnow()
        return [
            p for p in self._proposals.values()
            if not p.executed and now < p.expires_at
        ]