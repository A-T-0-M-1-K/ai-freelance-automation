"""
Сервис для создания и управления репутационными NFT
Верифицируемые сертификаты об успешных проектах
"""
import json
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime
from web3 import Web3
from web3.contract import Contract
from web3.exceptions import ContractLogicError
import ipfshttpclient

from blockchain.smart_contract_manager import SmartContractManager
from services.storage.database_service import DatabaseService

logger = logging.getLogger(__name__)


class ReputationNFT:
    """
    Репутационные NFT для верификации успешных проектов
    """

    def __init__(self, contract_manager: SmartContractManager, db_service: DatabaseService):
        self.contract_manager = contract_manager
        self.db_service = db_service
        self.nft_contract: Optional[Contract] = None
        self.contract_address: Optional[str] = None
        self.ipfs_client = None

        # Инициализация IPFS клиента
        try:
            self.ipfs_client = ipfshttpclient.connect('/ip4/127.0.0.1/tcp/5001/http')
            logger.info("IPFS клиент успешно инициализирован")
        except Exception as e:
            logger.warning(f"IPFS недоступен: {str(e)}. Используется резервное хранилище")

        logger.info("Инициализирован сервис репутационных NFT")

    async def deploy_nft_contract(self, owner_address: str) -> Dict[str, Any]:
        """
        Деплой смарт-контракта для репутационных NFT
        """
        contract_code = """
        // SPDX-License-Identifier: MIT
        pragma solidity ^0.8.0;
        
        import "@openzeppelin/contracts/token/ERC721/ERC721.sol";
        import "@openzeppelin/contracts/token/ERC721/extensions/ERC721URIStorage.sol";
        import "@openzeppelin/contracts/access/Ownable.sol";
        import "@openzeppelin/contracts/utils/Counters.sol";
        
        contract ReputationNFT is ERC721, ERC721URIStorage, Ownable {
            using Counters for Counters.Counter;
            Counters.Counter private _tokenIdCounter;
            
            struct ProjectMetadata {
                string projectName;
                string clientName;
                uint256 budget;
                uint256 completionDate;
                uint256 rating;
                string category;
                string[] skills;
                string ipfsHash;
                address freelancer;
                uint256 projectId;
            }
            
            mapping(uint256 => ProjectMetadata) public projectMetadata;
            mapping(address => uint256[]) public freelancerNFTs;
            
            event ProjectNFTMinted(
                uint256 indexed tokenId,
                address indexed freelancer,
                string projectName,
                uint256 budget,
                uint256 rating
            );
            
            event ProjectRatingUpdated(
                uint256 indexed tokenId,
                uint256 oldRating,
                uint256 newRating
            );
            
            constructor() ERC721("ReputationNFT", "REP") {}
            
            function mintNFT(
                address recipient,
                string memory tokenURI,
                string memory projectName,
                string memory clientName,
                uint256 budget,
                uint256 completionDate,
                uint256 rating,
                string memory category,
                string[] memory skills,
                string memory ipfsHash,
                uint256 projectId
            ) public onlyOwner returns (uint256) {
                require(rating >= 40, "Rating must be at least 4.0");
                require(budget > 0, "Budget must be positive");
                
                uint256 tokenId = _tokenIdCounter.current();
                _tokenIdCounter.increment();
                
                _mint(recipient, tokenId);
                _setTokenURI(tokenId, tokenURI);
                
                projectMetadata[tokenId] = ProjectMetadata({
                    projectName: projectName,
                    clientName: clientName,
                    budget: budget,
                    completionDate: completionDate,
                    rating: rating,
                    category: category,
                    skills: skills,
                    ipfsHash: ipfsHash,
                    freelancer: recipient,
                    projectId: projectId
                });
                
                freelancerNFTs[recipient].push(tokenId);
                
                emit ProjectNFTMinted(
                    tokenId,
                    recipient,
                    projectName,
                    budget,
                    rating
                );
                
                return tokenId;
            }
            
            function getProjectMetadata(uint256 tokenId) public view returns (
                string memory projectName,
                string memory clientName,
                uint256 budget,
                uint256 completionDate,
                uint256 rating,
                string memory category,
                string[] memory skills,
                string memory ipfsHash,
                address freelancer,
                uint256 projectId
            ) {
                ProjectMetadata storage meta = projectMetadata[tokenId];
                return (
                    meta.projectName,
                    meta.clientName,
                    meta.budget,
                    meta.completionDate,
                    meta.rating,
                    meta.category,
                    meta.skills,
                    meta.ipfsHash,
                    meta.freelancer,
                    meta.projectId
                );
            }
            
            function getFreelancerNFTs(address freelancer) public view returns (uint256[] memory) {
                return freelancerNFTs[freelancer];
            }
            
            function updateProjectRating(uint256 tokenId, uint256 newRating) public {
                require(ownerOf(tokenId) == msg.sender, "Not the owner");
                require(newRating >= 10 && newRating <= 50, "Rating must be between 1.0 and 5.0");
                
                uint256 oldRating = projectMetadata[tokenId].rating;
                projectMetadata[tokenId].rating = newRating;
                
                emit ProjectRatingUpdated(tokenId, oldRating, newRating);
            }
            
            function calculateReputationScore(address freelancer) public view returns (uint256) {
                uint256[] memory tokens = freelancerNFTs[freelancer];
                if (tokens.length == 0) return 0;
                
                uint256 totalRating = 0;
                uint256 totalBudget = 0;
                
                for (uint256 i = 0; i < tokens.length; i++) {
                    totalRating += projectMetadata[tokens[i]].rating;
                    totalBudget += projectMetadata[tokens[i]].budget;
                }
                
                // Взвешенная оценка: 60% рейтинг + 40% бюджет
                uint256 avgRating = totalRating / tokens.length;
                uint256 reputation = (avgRating * 60 / 100) + (totalBudget / 10000 * 40 / 100);
                
                return reputation;
            }
            
            // ERC721URIStorage overrides
            function _burn(uint256 tokenId) internal override(ERC721, ERC721URIStorage) {
                super._burn(tokenId);
            }
            
            function tokenURI(uint256 tokenId) public view override(ERC721, ERC721URIStorage) returns (string memory) {
                return super.tokenURI(tokenId);
            }
            
            function supportsInterface(bytes4 interfaceId) public view override(ERC721, ERC721URIStorage) returns (bool) {
                return super.supportsInterface(interfaceId);
            }
        }
        """

        try:
            # Компиляция и деплой контракта
            compiled_contract = self.contract_manager.compile_solidity(contract_code)
            tx_hash = self.contract_manager.w3.eth.contract(
                abi=compiled_contract['abi'],
                bytecode=compiled_contract['bytecode']
            ).constructor().transact({'from': owner_address})

            tx_receipt = self.contract_manager.w3.eth.wait_for_transaction_receipt(tx_hash)
            contract_address = tx_receipt.contractAddress

            # Создание экземпляра контракта
            self.nft_contract = self.contract_manager.w3.eth.contract(
                address=contract_address,
                abi=compiled_contract['abi']
            )
            self.contract_address = contract_address

            logger.info(f"Контракт репутационных NFT задеплоен: {contract_address}")

            # Сохранение информации о контракте в БД
            await self.db_service.execute_query(
                """
                INSERT INTO nft_contracts (address, type, deployed_at, owner_address, blockchain)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (contract_address, "ReputationNFT", datetime.now().isoformat(), owner_address, "ethereum")
            )

            return {
                "success": True,
                "contract_address": contract_address,
                "transaction_hash": tx_hash.hex(),
                "blockchain": "ethereum",
                "abi": compiled_contract['abi']
            }

        except Exception as e:
            logger.error(f"Ошибка деплоя контракта NFT: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }

    async def _fetch_project_data(self, project_id: str) -> Optional[Dict[str, Any]]:
        """Получение данных о проекте из базы"""
        query = """
            SELECT 
                p.id,
                p.title,
                p.description,
                p.category,
                p.skills,
                p.budget,
                p.currency,
                p.start_date,
                p.completion_date,
                p.status,
                p.rating,
                c.name as client_name,
                c.id as client_id
            FROM projects p
            LEFT JOIN clients c ON p.client_id = c.id
            WHERE p.id = %s AND p.status = 'completed'
        """

        try:
            results = await self.db_service.execute_query(query, (project_id,))
            if results:
                return results[0]
            return None
        except Exception as e:
            logger.error(f"Ошибка получения данных проекта {project_id}: {str(e)}")
            return None

    async def _generate_nft_metadata(self, project: Dict[str, Any], token_id: int) -> Dict[str, Any]:
        """Генерация метаданных NFT в формате ERC-721"""
        # Обработка навыков
        skills = project.get("skills", [])
        if isinstance(skills, str):
            try:
                skills = json.loads(skills)
            except:
                skills = [s.strip() for s in skills.split(',')]

        # Расчет дополнительных метрик
        completion_date = project.get("completion_date")
        if completion_date:
            completion_timestamp = int(datetime.fromisoformat(completion_date.replace('Z', '+00:00')).timestamp())
        else:
            completion_timestamp = int(datetime.now().timestamp())

        metadata = {
            "name": f"Project: {project.get('title', 'Untitled')}",
            "description": f"Verified successful project completion on AI Freelance Automation platform. "
                          f"Client: {project.get('client_name', 'Anonymous')}. "
                          f"Category: {project.get('category', 'Other')}.",
            "image": "ipfs://QmXyZ.../project_badge.png",  # Заглушка - будет заменена после загрузки в IPFS
            "external_url": f"https://freelance-automation.io/projects/{project.get('id')}",
            "attributes": [
                {
                    "trait_type": "Project Name",
                    "value": project.get('title', 'Untitled')
                },
                {
                    "trait_type": "Client",
                    "value": project.get('client_name', 'Anonymous')
                },
                {
                    "trait_type": "Category",
                    "value": project.get('category', 'Other')
                },
                {
                    "trait_type": "Budget",
                    "value": f"${project.get('budget', 0):.0f}",
                    "display_type": "number"
                },
                {
                    "trait_type": "Rating",
                    "value": project.get('rating', 0),
                    "display_type": "number"
                },
                {
                    "trait_type": "Completion Date",
                    "value": project.get('completion_date', 'N/A')
                },
                {
                    "trait_type": "Skills",
                    "value": ", ".join(skills[:5])  # Первые 5 навыков
                },
                {
                    "trait_type": "Token ID",
                    "value": token_id,
                    "display_type": "number"
                },
                {
                    "trait_type": "Verification Status",
                    "value": "Verified"
                }
            ],
            "project_id": project.get('id'),
            "freelancer_address": "",  # Будет заполнен позже
            "blockchain": "ethereum",
            "minted_at": datetime.now().isoformat()
        }

        return metadata

    async def _store_metadata_ipfs(self, metadata: Dict[str, Any]) -> str:
        """Сохранение метаданных в IPFS"""
        if self.ipfs_client:
            try:
                # Сохранение JSON метаданных
                res = self.ipfs_client.add_json(metadata)
                ipfs_hash = res['Hash']
                logger.info(f"Метаданные сохранены в IPFS: {ipfs_hash}")
                return f"ipfs://{ipfs_hash}"
            except Exception as e:
                logger.warning(f"Ошибка сохранения в IPFS: {str(e)}. Используется резервное хранилище")

        # Резервное хранилище - сохранение в локальную БД
        metadata_id = f"nft_meta_{int(datetime.now().timestamp())}_{hash(json.dumps(metadata, sort_keys=True)) % 1000000}"
        await self.db_service.save_nft_metadata(metadata_id, metadata)
        return f"https://freelance-automation.io/nft/metadata/{metadata_id}.json"

    async def mint_project_nft(self,
                              project_id: str,
                              freelancer_address: str,
                              wallet_private_key: str) -> Dict[str, Any]:
        """
        Создание NFT для завершенного проекта
        """
        if not self.nft_contract:
            # Автоматический деплой контракта при первом использовании
            deploy_result = await self.deploy_nft_contract(freelancer_address)
            if not deploy_result["success"]:
                return {
                    "success": False,
                    "error": f"Не удалось задеплоить NFT контракт: {deploy_result.get('error')}"
                }

        # Получение данных о проекте
        project = await self._fetch_project_data(project_id)

        if not project:
            return {
                "success": False,
                "error": f"Проект {project_id} не найден или не завершен"
            }

        # Валидация проекта
        if project.get("status") != "completed":
            return {
                "success": False,
                "error": "NFT можно создать только для завершенных проектов"
            }

        rating = project.get("rating", 0)
        if rating < 4.0:
            return {
                "success": False,
                "error": f"Рейтинг проекта должен быть не менее 4.0 для создания NFT (текущий: {rating})"
            }

        budget = project.get("budget", 0)
        if budget < 50:  # Минимальный бюджет $50
            return {
                "success": False,
                "error": f"Минимальный бюджет для NFT: $50 (текущий: ${budget})"
            }

        # Генерация метаданных
        metadata = await self._generate_nft_metadata(project, token_id=0)  # token_id будет известен после минта

        # Сохранение метаданных в IPFS/резервное хранилище
        metadata_uri = await self._store_metadata_ipfs(metadata)

        # Подготовка параметров для контракта
        skills = metadata["attributes"][6]["value"].split(', ')
        completion_date = int(datetime.fromisoformat(project.get("completion_date", datetime.now().isoformat()).replace('Z', '+00:00')).timestamp())

        try:
            # Создание транзакции
            tx = self.nft_contract.functions.mintNFT(
                Web3.to_checksum_address(freelancer_address),
                metadata_uri,
                project.get("title", ""),
                project.get("client_name", "Anonymous"),
                int(budget * 100),  # в центах
                completion_date,
                int(rating * 10),  # в десятых долях (4.5 -> 45)
                project.get("category", "other"),
                skills,
                metadata_uri.replace('ipfs://', ''),
                int(project_id.replace('proj_', '')) if 'proj_' in project_id else int(project_id)
            ).build_transaction({
                'from': freelancer_address,
                'nonce': self.contract_manager.w3.eth.get_transaction_count(freelancer_address),
                'gas': 500000,
                'gasPrice': self.contract_manager.w3.eth.gas_price
            })

            # Подпись транзакции
            signed_tx = self.contract_manager.w3.eth.account.sign_transaction(tx, wallet_private_key)

            # Отправка транзакции
            tx_hash = self.contract_manager.w3.eth.send_raw_transaction(signed_tx.rawTransaction)

            # Ожидание подтверждения
            tx_receipt = self.contract_manager.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

            if tx_receipt.status == 1:
                # Получение token_id из событий лога
                token_id = None
                for log in tx_receipt.logs:
                    try:
                        event = self.nft_contract.events.ProjectNFTMinted().process_log(log)
                        token_id = event['args']['tokenId']
                        break
                    except:
                        continue

                if token_id is None:
                    # Резервный метод - получение последнего токена
                    token_id = self.nft_contract.functions.tokenCounter().call() - 1

                # Обновление метаданных с реальным token_id
                metadata["attributes"].append({
                    "trait_type": "Token ID",
                    "value": token_id,
                    "display_type": "number"
                })
                metadata["token_id"] = token_id

                # Повторное сохранение метаданных с корректным token_id
                updated_uri = await self._store_metadata_ipfs(metadata)

                # Сохранение информации о NFT в БД
                await self.db_service.execute_query(
                    """
                    INSERT INTO project_nfts (
                        project_id, token_id, contract_address, freelancer_address, 
                        metadata_uri, ipfs_hash, minted_at, transaction_hash, rating, budget
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        project_id,
                        token_id,
                        self.contract_address,
                        freelancer_address,
                        updated_uri,
                        updated_uri.replace('ipfs://', ''),
                        datetime.now().isoformat(),
                        tx_hash.hex(),
                        rating,
                        budget
                    )
                )

                logger.info(f"NFT успешно создан для проекта {project_id}: token_id={token_id}")

                return {
                    "success": True,
                    "token_id": token_id,
                    "contract_address": self.contract_address,
                    "transaction_hash": tx_hash.hex(),
                    "metadata_uri": updated_uri,
                    "blockchain_explorer_url": f"https://etherscan.io/tx/{tx_hash.hex()}",
                    "opensea_url": f"https://opensea.io/assets/ethereum/{self.contract_address}/{token_id}"
                }
            else:
                return {
                    "success": False,
                    "error": "Транзакция минта не подтверждена",
                    "transaction_hash": tx_hash.hex()
                }

        except ContractLogicError as e:
            error_msg = str(e)
            if "Rating must be at least 4.0" in error_msg:
                error_msg = "Рейтинг проекта должен быть не менее 4.0"
            elif "Budget must be positive" in error_msg:
                error_msg = "Бюджет проекта должен быть положительным"

            logger.error(f"Ошибка контракта при минте NFT: {error_msg}")
            return {
                "success": False,
                "error": error_msg,
                "contract_error": str(e)
            }
        except Exception as e:
            logger.error(f"Ошибка минта NFT: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }

    async def get_freelancer_reputation(self, freelancer_address: str) -> Dict[str, Any]:
        """Получение репутации фрилансера на основе его NFT"""
        if not self.nft_contract:
            return {"error": "NFT контракт не инициализирован"}

        try:
            # Получение списка NFT фрилансера
            token_ids = self.nft_contract.functions.getFreelancerNFTs(
                Web3.to_checksum_address(freelancer_address)
            ).call()

            # Получение метаданных для каждого NFT
            projects = []
            total_rating = 0
            total_budget = 0

            for token_id in token_ids:
                try:
                    metadata = self.nft_contract.functions.getProjectMetadata(token_id).call()

                    project = {
                        "token_id": token_id,
                        "project_name": metadata[0],
                        "client_name": metadata[1],
                        "budget": metadata[2] / 100,  # конвертация из центов
                        "completion_date": datetime.fromtimestamp(metadata[3]).isoformat(),
                        "rating": metadata[4] / 10,  # конвертация из десятых долей
                        "category": metadata[5],
                        "skills": metadata[6],
                        "ipfs_hash": metadata[7],
                        "freelancer": metadata[8],
                        "project_id": metadata[9]
                    }

                    projects.append(project)
                    total_rating += project["rating"]
                    total_budget += project["budget"]

                except Exception as e:
                    logger.warning(f"Ошибка получения метаданных для token_id {token_id}: {str(e)}")
                    continue

            # Расчет репутационного скоринга
            nft_count = len(projects)
            avg_rating = total_rating / nft_count if nft_count > 0 else 0
            avg_budget = total_budget / nft_count if nft_count > 0 else 0

            # Алгоритм репутационного скоринга
            reputation_score = 0
            if nft_count > 0:
                # Базовый скоринг: 40% от рейтинга + 30% от количества проектов + 30% от бюджета
                rating_component = min(avg_rating * 20, 100)  # Максимум 100 баллов за рейтинг
                count_component = min(nft_count * 10, 100)   # Максимум 100 баллов за количество
                budget_component = min((avg_budget / 100) * 20, 100)  # Максимум 100 баллов за бюджет

                reputation_score = (
                    rating_component * 0.4 +
                    count_component * 0.3 +
                    budget_component * 0.3
                )

            # Определение уровня репутации
            if reputation_score >= 90:
                reputation_level = "Platinum"
            elif reputation_score >= 75:
                reputation_level = "Gold"
            elif reputation_score >= 60:
                reputation_level = "Silver"
            elif reputation_score >= 40:
                reputation_level = "Bronze"
            else:
                reputation_level = "Basic"

            return {
                "freelancer_address": freelancer_address,
                "reputation_score": round(reputation_score, 2),
                "reputation_level": reputation_level,
                "nft_count": nft_count,
                "average_rating": round(avg_rating, 2),
                "total_budget": round(total_budget, 2),
                "average_budget": round(avg_budget, 2),
                "projects": projects,
                "last_updated": datetime.now().isoformat()
            }

        except Exception as e:
            logger.error(f"Ошибка получения репутации: {str(e)}")
            return {
                "error": str(e),
                "freelancer_address": freelancer_address
            }

    async def trade_reputation_nft(self,
                                  token_id: int,
                                  seller_address: str,
                                  buyer_address: str,
                                  price_wei: int,
                                  seller_private_key: str) -> Dict[str, Any]:
        """
        Торговля репутационным NFT на децентрализованной бирже
        """
        if not self.nft_contract:
            return {"success": False, "error": "NFT контракт не инициализирован"}

        try:
            # Проверка владения токеном
            current_owner = self.nft_contract.functions.ownerOf(token_id).call()
            if current_owner.lower() != seller_address.lower():
                return {
                    "success": False,
                    "error": "Адрес продавца не является владельцем NFT"
                }

            # Одобрение трансфера (если требуется)
            is_approved = self.nft_contract.functions.isApprovedForAll(
                Web3.to_checksum_address(seller_address),
                Web3.to_checksum_address(buyer_address)
            ).call()

            if not is_approved:
                approve_tx = self.nft_contract.functions.setApprovalForAll(
                    Web3.to_checksum_address(buyer_address),
                    True
                ).build_transaction({
                    'from': seller_address,
                    'nonce': self.contract_manager.w3.eth.get_transaction_count(seller_address),
                    'gas': 100000,
                    'gasPrice': self.contract_manager.w3.eth.gas_price
                })

                signed_approve = self.contract_manager.w3.eth.account.sign_transaction(
                    approve_tx, seller_private_key
                )
                approve_hash = self.contract_manager.w3.eth.send_raw_transaction(
                    signed_approve.rawTransaction
                )
                self.contract_manager.w3.eth.wait_for_transaction_receipt(approve_hash)

            # Трансфер NFT
            transfer_tx = self.nft_contract.functions.safeTransferFrom(
                Web3.to_checksum_address(seller_address),
                Web3.to_checksum_address(buyer_address),
                token_id
            ).build_transaction({
                'from': seller_address,
                'nonce': self.contract_manager.w3.eth.get_transaction_count(seller_address) + 1,
                'gas': 200000,
                'gasPrice': self.contract_manager.w3.eth.gas_price
            })

            signed_transfer = self.contract_manager.w3.eth.account.sign_transaction(
                transfer_tx, seller_private_key
            )
            transfer_hash = self.contract_manager.w3.eth.send_raw_transaction(
                signed_transfer.rawTransaction
            )
            receipt = self.contract_manager.w3.eth.wait_for_transaction_receipt(transfer_hash)

            if receipt.status == 1:
                # Запись транзакции в БД
                await self.db_service.execute_query(
                    """
                    INSERT INTO nft_trades (
                        token_id, contract_address, seller_address, buyer_address,
                        price_wei, transaction_hash, traded_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        token_id,
                        self.contract_address,
                        seller_address,
                        buyer_address,
                        price_wei,
                        transfer_hash.hex(),
                        datetime.now().isoformat()
                    )
                )

                return {
                    "success": True,
                    "token_id": token_id,
                    "seller": seller_address,
                    "buyer": buyer_address,
                    "price_eth": Web3.from_wei(price_wei, 'ether'),
                    "transaction_hash": transfer_hash.hex(),
                    "blockchain_explorer_url": f"https://etherscan.io/tx/{transfer_hash.hex()}"
                }
            else:
                return {
                    "success": False,
                    "error": "Транзакция трансфера не подтверждена"
                }

        except Exception as e:
            logger.error(f"Ошибка торговли NFT: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }

    async def verify_project_nft(self, token_id: int) -> Dict[str, Any]:
        """
        Верификация подлинности проекта через NFT
        """
        if not self.nft_contract:
            return {"verified": False, "error": "NFT контракт не инициализирован"}

        try:
            # Получение метаданных из блокчейна
            metadata = self.nft_contract.functions.getProjectMetadata(token_id).call()

            # Получение URI токена
            token_uri = self.nft_contract.functions.tokenURI(token_id).call()

            # Верификация через IPFS
            ipfs_hash = metadata[7]
            is_ipfs_valid = False

            if self.ipfs_client and ipfs_hash:
                try:
                    # Загрузка метаданных из IPFS
                    ipfs_data = self.ipfs_client.cat(ipfs_hash)
                    is_ipfs_valid = True
                except:
                    pass

            return {
                "verified": True,
                "token_id": token_id,
                "contract_address": self.contract_address,
                "project_name": metadata[0],
                "client_name": metadata[1],
                "budget": metadata[2] / 100,
                "rating": metadata[4] / 10,
                "completion_date": datetime.fromtimestamp(metadata[3]).isoformat(),
                "category": metadata[5],
                "skills": metadata[6],
                "token_uri": token_uri,
                "ipfs_verified": is_ipfs_valid,
                "blockchain_verification": f"https://etherscan.io/token/{self.contract_address}?a={token_id}",
                "verification_timestamp": datetime.now().isoformat()
            }

        except Exception as e:
            logger.error(f"Ошибка верификации NFT: {str(e)}")
            return {
                "verified": False,
                "error": str(e),
                "token_id": token_id
            }