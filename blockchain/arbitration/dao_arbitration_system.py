"""
Децентрализованная система арбитража на базе DAO
Разрешение споров через голосование сообщества вместо централизованной поддержки
"""
import json
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from web3 import Web3
from web3.contract import Contract

from blockchain.smart_contract_manager import SmartContractManager
from blockchain.dao_manager import DAOManager
from services.storage.database_service import DatabaseService

logger = logging.getLogger(__name__)


class DAOArbitrationSystem:
    """
    Система децентрализованного арбитража через DAO
    """

    def __init__(self, contract_manager: SmartContractManager, dao_manager: DAOManager, db_service: DatabaseService):
        self.contract_manager = contract_manager
        self.dao_manager = dao_manager
        self.db_service = db_service
        self.arbitration_contract: Optional[Contract] = None
        self.disputes: Dict[str, Dict[str, Any]] = {}

        logger.info("Инициализирована система децентрализованного арбитража")

    async def deploy_arbitration_contract(self, owner_address: str) -> Dict[str, Any]:
        """
        Деплой смарт-контракта для децентрализованного арбитража
        """
        contract_code = """
        // SPDX-License-Identifier: MIT
        pragma solidity ^0.8.0;

        contract DAOArbitration {
            address public owner;
            uint256 public disputeCounter;
            uint256 public minStakeAmount; // Минимальный стейк для участия в арбитраже
            uint256 public votingPeriod;   // Период голосования в секундах
            uint256 public quorumPercentage; // Минимальный кворум (%)

            struct Dispute {
                uint256 id;
                address freelancer;
                address client;
                uint256 amount;
                string description;
                string evidenceHash;
                uint256 startTime;
                uint256 endTime;
                uint256 votesForFreelancer;
                uint256 votesForClient;
                uint256 totalVotes;
                address[] voters;
                mapping(address => bool) hasVoted;
                bool resolved;
                address winner;
                uint256 resolutionTime;
            }

            mapping(uint256 => Dispute) public disputes;
            mapping(address => uint256[]) public userDisputes;

            event DisputeCreated(
                uint256 indexed disputeId,
                address indexed freelancer,
                address indexed client,
                uint256 amount
            );

            event VoteCast(
                uint256 indexed disputeId,
                address indexed voter,
                bool votedForFreelancer
            );

            event DisputeResolved(
                uint256 indexed disputeId,
                address winner,
                uint256 amount
            );

            modifier onlyOwner() {
                require(msg.sender == owner, "Not the owner");
                _;
            }

            constructor(uint256 _minStakeAmount, uint256 _votingPeriod, uint256 _quorumPercentage) {
                owner = msg.sender;
                minStakeAmount = _minStakeAmount;
                votingPeriod = _votingPeriod;
                quorumPercentage = _quorumPercentage;
                disputeCounter = 0;
            }

            function createDispute(
                address _freelancer,
                address _client,
                uint256 _amount,
                string memory _description,
                string memory _evidenceHash
            ) public returns (uint256) {
                require(_amount > 0, "Amount must be positive");
                require(bytes(_description).length > 0, "Description required");

                uint256 disputeId = disputeCounter;
                disputeCounter++;

                disputes[disputeId] = Dispute({
                    id: disputeId,
                    freelancer: _freelancer,
                    client: _client,
                    amount: _amount,
                    description: _description,
                    evidenceHash: _evidenceHash,
                    startTime: block.timestamp,
                    endTime: block.timestamp + votingPeriod,
                    votesForFreelancer: 0,
                    votesForClient: 0,
                    totalVotes: 0,
                    voters: new address[](0),
                    resolved: false,
                    winner: address(0),
                    resolutionTime: 0
                });

                userDisputes[_freelancer].push(disputeId);
                userDisputes[_client].push(disputeId);

                emit DisputeCreated(disputeId, _freelancer, _client, _amount);

                return disputeId;
            }

            function castVote(uint256 _disputeId, bool _voteForFreelancer) public {
                Dispute storage dispute = disputes[_disputeId];

                require(!dispute.resolved, "Dispute already resolved");
                require(block.timestamp < dispute.endTime, "Voting period ended");
                require(!dispute.hasVoted[msg.sender], "Already voted");
                require(_hasSufficientStake(msg.sender), "Insufficient stake");

                if (_voteForFreelancer) {
                    dispute.votesForFreelancer += _getVotingPower(msg.sender);
                } else {
                    dispute.votesForClient += _getVotingPower(msg.sender);
                }

                dispute.totalVotes += _getVotingPower(msg.sender);
                dispute.hasVoted[msg.sender] = true;

                // Добавление голосующего в список
                dispute.voters.push(msg.sender);

                emit VoteCast(_disputeId, msg.sender, _voteForFreelancer);
            }

            function resolveDispute(uint256 _disputeId) public {
                Dispute storage dispute = disputes[_disputeId];

                require(!dispute.resolved, "Dispute already resolved");
                require(block.timestamp >= dispute.endTime, "Voting period not ended");

                // Проверка кворума
                uint256 quorumRequired = (dispute.amount * quorumPercentage) / 10000; // quorumPercentage в базисных пунктах
                require(dispute.totalVotes >= quorumRequired, "Quorum not reached");

                // Определение победителя
                if (dispute.votesForFreelancer > dispute.votesForClient) {
                    dispute.winner = dispute.freelancer;
                } else if (dispute.votesForClient > dispute.votesForFreelancer) {
                    dispute.winner = dispute.client;
                } else {
                    // Ничья - возврат средств обоим
                    dispute.winner = address(0);
                }

                dispute.resolved = true;
                dispute.resolutionTime = block.timestamp;

                emit DisputeResolved(_disputeId, dispute.winner, dispute.amount);
            }

            function getDispute(uint256 _disputeId) public view returns (
                uint256 id,
                address freelancer,
                address client,
                uint256 amount,
                string memory description,
                string memory evidenceHash,
                uint256 startTime,
                uint256 endTime,
                uint256 votesForFreelancer,
                uint256 votesForClient,
                uint256 totalVotes,
                bool resolved,
                address winner,
                uint256 resolutionTime
            ) {
                Dispute storage dispute = disputes[_disputeId];
                return (
                    dispute.id,
                    dispute.freelancer,
                    dispute.client,
                    dispute.amount,
                    dispute.description,
                    dispute.evidenceHash,
                    dispute.startTime,
                    dispute.endTime,
                    dispute.votesForFreelancer,
                    dispute.votesForClient,
                    dispute.totalVotes,
                    dispute.resolved,
                    dispute.winner,
                    dispute.resolutionTime
                );
            }

            function getUserDisputes(address _user) public view returns (uint256[] memory) {
                return userDisputes[_user];
            }

            function _hasSufficientStake(address _user) internal view returns (bool) {
                // В реальной реализации проверка стейка в токене репутации
                return true; // Заглушка
            }

            function _getVotingPower(address _user) internal view returns (uint256) {
                // В реальной реализации голосовая сила пропорциональна стейку
                return 1; // Заглушка - 1 голос на участника
            }

            function updateSettings(uint256 _minStakeAmount, uint256 _votingPeriod, uint256 _quorumPercentage) public onlyOwner {
                minStakeAmount = _minStakeAmount;
                votingPeriod = _votingPeriod;
                quorumPercentage = _quorumPercentage;
            }
        }
        """

        try:
            compiled_contract = self.contract_manager.compile_solidity(contract_code)

            # Деплой с параметрами по умолчанию
            tx_hash = self.contract_manager.w3.eth.contract(
                abi=compiled_contract['abi'],
                bytecode=compiled_contract['bytecode']
            ).constructor(
                1000000000000000000,  # 1 ETH минимальный стейк
                604800,  # 7 дней период голосования
                1000  # 10% кворум (в базисных пунктах)
            ).transact({'from': owner_address})

            tx_receipt = self.contract_manager.w3.eth.wait_for_transaction_receipt(tx_hash)
            contract_address = tx_receipt.contractAddress

            self.arbitration_contract = self.contract_manager.w3.eth.contract(
                address=contract_address,
                abi=compiled_contract['abi']
            )

            logger.info(f"Контракт арбитража задеплоен: {contract_address}")

            return {
                "success": True,
                "contract_address": contract_address,
                "transaction_hash": tx_hash.hex(),
                "abi": compiled_contract['abi']
            }

        except Exception as e:
            logger.error(f"Ошибка деплоя контракта арбитража: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }

    async def create_dispute(self,
                             job_id: str,
                             freelancer_address: str,
                             client_address: str,
                             amount: float,
                             description: str,
                             evidence_files: List[str],
                             creator_address: str,
                             private_key: str) -> Dict[str, Any]:
        """
        Создание спора для разрешения через DAO арбитраж
        """
        if not self.arbitration_contract:
            deploy_result = await self.deploy_arbitration_contract(creator_address)
            if not deploy_result["success"]:
                return {
                    "success": False,
                    "error": f"Не удалось задеплоить контракт арбитража: {deploy_result.get('error')}"
                }

        # Валидация данных
        if amount <= 0:
            return {"success": False, "error": "Сумма спора должна быть положительной"}

        if len(description) < 20:
            return {"success": False, "error": "Описание спора должно содержать минимум 20 символов"}

        # Сохранение доказательств в IPFS
        evidence_hash = await self._store_evidence_ipfs(evidence_files, job_id)

        try:
            # Создание спора в блокчейне
            tx = self.arbitration_contract.functions.createDispute(
                Web3.to_checksum_address(freelancer_address),
                Web3.to_checksum_address(client_address),
                int(amount * 10 ** 18),  # Конвертация в wei
                description,
                evidence_hash
            ).build_transaction({
                'from': creator_address,
                'nonce': self.contract_manager.w3.eth.get_transaction_count(creator_address),
                'gas': 500000,
                'gasPrice': self.contract_manager.w3.eth.gas_price
            })

            signed_tx = self.contract_manager.w3.eth.account.sign_transaction(tx, private_key)
            tx_hash = self.contract_manager.w3.eth.send_raw_transaction(signed_tx.rawTransaction)
            receipt = self.contract_manager.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

            if receipt.status == 1:
                # Получение dispute_id из логов
                dispute_id = None
                for log in receipt.logs:
                    try:
                        event = self.arbitration_contract.events.DisputeCreated().process_log(log)
                        dispute_id = event['args']['disputeId']
                        break
                    except:
                        continue

                if dispute_id is None:
                    dispute_id = self.arbitration_contract.functions.disputeCounter().call() - 1

                # Сохранение информации о споре в БД
                dispute_data = {
                    "dispute_id": dispute_id,
                    "job_id": job_id,
                    "freelancer_address": freelancer_address,
                    "client_address": client_address,
                    "amount": amount,
                    "currency": "ETH",
                    "description": description,
                    "evidence_hash": evidence_hash,
                    "evidence_files": evidence_files,
                    "created_at": datetime.now().isoformat(),
                    "status": "active",
                    "voting_end_time": (datetime.now() + timedelta(days=7)).isoformat(),
                    "transaction_hash": tx_hash.hex()
                }

                await self.db_service.save_dispute(dispute_data)
                self.disputes[str(dispute_id)] = dispute_data

                logger.info(f"Спор #{dispute_id} успешно создан для заказа {job_id}")

                return {
                    "success": True,
                    "dispute_id": dispute_id,
                    "job_id": job_id,
                    "transaction_hash": tx_hash.hex(),
                    "voting_ends_at": dispute_data["voting_end_time"],
                    "blockchain_explorer_url": f"https://etherscan.io/tx/{tx_hash.hex()}",
                    "evidence_url": f"https://ipfs.io/ipfs/{evidence_hash}" if evidence_hash.startswith('Qm') else None
                }
            else:
                return {
                    "success": False,
                    "error": "Транзакция создания спора не подтверждена"
                }

        except Exception as e:
            logger.error(f"Ошибка создания спора: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }

    async def _store_evidence_ipfs(self, evidence_files: List[str], job_id: str) -> str:
        """Сохранение доказательств спора в IPFS"""
        try:
            import ipfshttpclient
            client = ipfshttpclient.connect('/ip4/127.0.0.1/tcp/5001/http')

            # Создание манифеста доказательств
            evidence_manifest = {
                "job_id": job_id,
                "timestamp": datetime.now().isoformat(),
                "files": []
            }

            for file_path in evidence_files:
                if file_path.startswith('data/'):
                    # Загрузка файла в IPFS
                    res = client.add(file_path)
                    evidence_manifest["files"].append({
                        "name": file_path.split('/')[-1],
                        "ipfs_hash": res['Hash'],
                        "size": res['Size']
                    })

            # Сохранение манифеста
            manifest_res = client.add_json(evidence_manifest)
            return manifest_res['Hash']

        except Exception as e:
            logger.warning(f"Ошибка сохранения в IPFS: {str(e)}. Используется хэш локальных файлов")
            # Резервный метод - хэширование локальных файлов
            import hashlib
            hash_obj = hashlib.sha256()
            for file_path in evidence_files:
                if os.path.exists(file_path):
                    with open(file_path, 'rb') as f:
                        hash_obj.update(f.read())
            return hash_obj.hexdigest()[:32]

    async def cast_vote(self,
                        dispute_id: int,
                        voter_address: str,
                        vote_for_freelancer: bool,
                        private_key: str) -> Dict[str, Any]:
        """
        Голосование в споре
        """
        if not self.arbitration_contract:
            return {"success": False, "error": "Контракт арбитража не инициализирован"}

        # Проверка права голоса (стейк в токене репутации)
        has_stake = await self._check_voter_stake(voter_address)
        if not has_stake:
            return {
                "success": False,
                "error": "Для голосования требуется минимальный стейк в токене репутации"
            }

        try:
            tx = self.arbitration_contract.functions.castVote(
                dispute_id,
                vote_for_freelancer
            ).build_transaction({
                'from': voter_address,
                'nonce': self.contract_manager.w3.eth.get_transaction_count(voter_address),
                'gas': 200000,
                'gasPrice': self.contract_manager.w3.eth.gas_price
            })

            signed_tx = self.contract_manager.w3.eth.account.sign_transaction(tx, private_key)
            tx_hash = self.contract_manager.w3.eth.send_raw_transaction(signed_tx.rawTransaction)
            receipt = self.contract_manager.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

            if receipt.status == 1:
                # Сохранение голоса в БД
                await self.db_service.save_vote({
                    "dispute_id": dispute_id,
                    "voter_address": voter_address,
                    "vote_for_freelancer": vote_for_freelancer,
                    "voting_power": 1,  # В реальной системе зависит от стейка
                    "timestamp": datetime.now().isoformat(),
                    "transaction_hash": tx_hash.hex()
                })

                logger.info(f"Голос успешно отдан в споре #{dispute_id} от {voter_address}")

                return {
                    "success": True,
                    "dispute_id": dispute_id,
                    "voter": voter_address,
                    "vote": "freelancer" if vote_for_freelancer else "client",
                    "transaction_hash": tx_hash.hex()
                }
            else:
                return {
                    "success": False,
                    "error": "Транзакция голосования не подтверждена"
                }

        except Exception as e:
            logger.error(f"Ошибка голосования: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }

    async def _check_voter_stake(self, address: str) -> bool:
        """Проверка минимального стейка для права голоса"""
        # В реальной системе проверка баланса токена репутации
        # Здесь заглушка - все адреса имеют право голоса
        return True

    async def resolve_dispute(self, dispute_id: int, resolver_address: str, private_key: str) -> Dict[str, Any]:
        """
        Разрешение спора по истечении периода голосования
        """
        if not self.arbitration_contract:
            return {"success": False, "error": "Контракт арбитража не инициализирован"}

        try:
            # Проверка, что период голосования завершен
            dispute = self.arbitration_contract.functions.getDispute(dispute_id).call()
            is_resolved = dispute[11]  # resolved flag
            end_time = dispute[7]  # endTime

            if is_resolved:
                return {
                    "success": False,
                    "error": "Спор уже разрешен"
                }

            if datetime.now().timestamp() < end_time:
                time_left = end_time - datetime.now().timestamp()
                return {
                    "success": False,
                    "error": f"Период голосования еще не завершен. Осталось {int(time_left / 3600)} часов"
                }

            # Разрешение спора
            tx = self.arbitration_contract.functions.resolveDispute(dispute_id).build_transaction({
                'from': resolver_address,
                'nonce': self.contract_manager.w3.eth.get_transaction_count(resolver_address),
                'gas': 300000,
                'gasPrice': self.contract_manager.w3.eth.gas_price
            })

            signed_tx = self.contract_manager.w3.eth.account.sign_transaction(tx, private_key)
            tx_hash = self.contract_manager.w3.eth.send_raw_transaction(signed_tx.rawTransaction)
            receipt = self.contract_manager.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

            if receipt.status == 1:
                # Получение результатов
                updated_dispute = self.arbitration_contract.functions.getDispute(dispute_id).call()
                winner = updated_dispute[12]  # winner address
                amount = Web3.from_wei(updated_dispute[3], 'ether')  # amount

                # Обновление статуса в БД
                await self.db_service.update_dispute_status(
                    dispute_id,
                    status="resolved",
                    winner=winner,
                    resolution_time=datetime.now().isoformat(),
                    transaction_hash=tx_hash.hex()
                )

                logger.info(f"Спор #{dispute_id} разрешен. Победитель: {winner}, сумма: {amount} ETH")

                return {
                    "success": True,
                    "dispute_id": dispute_id,
                    "winner": winner,
                    "amount_eth": float(amount),
                    "transaction_hash": tx_hash.hex(),
                    "resolution_time": datetime.now().isoformat()
                }
            else:
                return {
                    "success": False,
                    "error": "Транзакция разрешения спора не подтверждена"
                }

        except Exception as e:
            logger.error(f"Ошибка разрешения спора: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }

    async def get_dispute_details(self, dispute_id: int) -> Dict[str, Any]:
        """Получение деталей спора"""
        if not self.arbitration_contract:
            return {"error": "Контракт арбитража не инициализирован"}

        try:
            dispute = self.arbitration_contract.functions.getDispute(dispute_id).call()

            return {
                "dispute_id": dispute[0],
                "freelancer": dispute[1],
                "client": dispute[2],
                "amount_eth": float(Web3.from_wei(dispute[3], 'ether')),
                "description": dispute[4],
                "evidence_hash": dispute[5],
                "start_time": datetime.fromtimestamp(dispute[6]).isoformat(),
                "end_time": datetime.fromtimestamp(dispute[7]).isoformat(),
                "votes_for_freelancer": dispute[8],
                "votes_for_client": dispute[9],
                "total_votes": dispute[10],
                "resolved": dispute[11],
                "winner": dispute[12],
                "resolution_time": datetime.fromtimestamp(dispute[13]).isoformat() if dispute[13] > 0 else None,
                "voting_active": datetime.now().timestamp() < dispute[7] and not dispute[11],
                "time_remaining": max(0, dispute[7] - int(datetime.now().timestamp())),
                "blockchain_url": f"https://etherscan.io/address/{self.arbitration_contract.address}#readContract"
            }

        except Exception as e:
            logger.error(f"Ошибка получения деталей спора: {str(e)}")
            return {
                "error": str(e),
                "dispute_id": dispute_id
            }

    async def get_user_disputes(self, user_address: str) -> List[Dict[str, Any]]:
        """Получение списка споров пользователя"""
        if not self.arbitration_contract:
            return []

        try:
            dispute_ids = self.arbitration_contract.functions.getUserDisputes(
                Web3.to_checksum_address(user_address)
            ).call()

            disputes = []
            for dispute_id in dispute_ids:
                dispute_details = await self.get_dispute_details(dispute_id)
                disputes.append(dispute_details)

            return disputes

        except Exception as e:
            logger.error(f"Ошибка получения споров пользователя: {str(e)}")
            return []