"""
Система токенизации будущих доходов фрилансера
Продажа долей будущих доходов через смарт-контракты
"""
import json
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from web3 import Web3
from web3.contract import Contract

from blockchain.smart_contract_manager import SmartContractManager
from blockchain.token_manager import TokenManager
from services.storage.database_service import DatabaseService

logger = logging.getLogger(__name__)


class IncomeTokenizationSystem:
    """
    Система токенизации доходов для привлечения инвестиций
    """

    def __init__(self, contract_manager: SmartContractManager, token_manager: TokenManager,
                 db_service: DatabaseService):
        self.contract_manager = contract_manager
        self.token_manager = token_manager
        self.db_service = db_service
        self.tokenization_contract: Optional[Contract] = None
        self.income_streams: Dict[str, Dict[str, Any]] = {}

        logger.info("Инициализирована система токенизации доходов")

    async def deploy_tokenization_contract(self, owner_address: str) -> Dict[str, Any]:
        """
        Деплой смарт-контракта для токенизации доходов
        """
        contract_code = """
        // SPDX-License-Identifier: MIT
        pragma solidity ^0.8.0;

        import "@openzeppelin/contracts/token/ERC20/ERC20.sol";
        import "@openzeppelin/contracts/access/Ownable.sol";
        import "@openzeppelin/contracts/security/ReentrancyGuard.sol";

        contract IncomeToken is ERC20, Ownable, ReentrancyGuard {
            address public incomeSource;    // Адрес, генерирующий доход
            uint256 public totalIncomeShare; // Общая доля дохода для токенов (в базисных пунктах, 10000 = 100%)
            uint256 public tokenizationPeriod; // Период токенизации в секундах
            uint256 public startTime;
            uint256 public endTime;
            bool public isActive;

            mapping(address => uint256) public investorShares;
            uint256 public totalInvested;
            uint256 public totalDistributed;

            event IncomeDeposited(address indexed depositor, uint256 amount, uint256 timestamp);
            event IncomeDistributed(address indexed investor, uint256 tokens, uint256 amount, uint256 timestamp);
            event TokensPurchased(address indexed buyer, uint256 amount, uint256 tokenAmount, uint256 timestamp);
            event TokenizationEnded(uint256 totalDistributed, uint256 remainingBalance);

            constructor(
                string memory name,
                string memory symbol,
                address _incomeSource,
                uint256 _totalIncomeShare,
                uint256 _tokenizationPeriod
            ) ERC20(name, symbol) {
                require(_totalIncomeShare <= 10000, "Income share cannot exceed 100%");
                require(_tokenizationPeriod > 0, "Period must be positive");

                incomeSource = _incomeSource;
                totalIncomeShare = _totalIncomeShare;
                tokenizationPeriod = _tokenizationPeriod;
                startTime = block.timestamp;
                endTime = startTime + _tokenizationPeriod;
                isActive = true;
            }

            function purchaseTokens() public payable nonReentrant {
                require(isActive, "Tokenization ended");
                require(block.timestamp < endTime, "Tokenization period ended");
                require(msg.value > 0, "Must send ETH");

                // Расчет количества токенов (простая модель: 1 ETH = 100 токенов)
                uint256 tokensToMint = msg.value * 100;

                // Минтинг токенов
                _mint(msg.sender, tokensToMint);

                // Запись доли инвестора
                investorShares[msg.sender] += tokensToMint;
                totalInvested += msg.value;

                emit TokensPurchased(msg.sender, msg.value, tokensToMint, block.timestamp);
            }

            function depositIncome() public payable nonReentrant {
                require(msg.sender == incomeSource, "Only income source can deposit");
                require(msg.value > 0, "Must deposit positive amount");
                require(isActive || block.timestamp < endTime + 30 days, "Too late to deposit");

                uint256 incomeToDistribute = (msg.value * totalIncomeShare) / 10000;
                uint256 remaining = msg.value - incomeToDistribute;

                totalDistributed += incomeToDistribute;

                emit IncomeDeposited(msg.sender, msg.value, block.timestamp);

                // Автоматическая дистрибуция пропорционально долям
                _distributeIncome(incomeToDistribute);
            }

            function _distributeIncome(uint256 amount) internal {
                uint256 totalSupply = totalSupply();
                if (totalSupply == 0) return;

                // Дистрибуция пропорционально балансам токенов
                for (uint256 i = 0; i < investorShares.length; i++) {
                    address investor = investorAddresses[i];
                    uint256 share = (balanceOf(investor) * amount) / totalSupply;

                    if (share > 0) {
                        payable(investor).transfer(share);
                        emit IncomeDistributed(investor, balanceOf(investor), share, block.timestamp);
                    }
                }
            }

            function endTokenization() public onlyOwner {
                require(isActive, "Already ended");
                require(block.timestamp >= endTime, "Tokenization period not ended");

                isActive = false;

                // Возврат оставшихся средств владельцу
                uint256 remainingBalance = address(this).balance;
                if (remainingBalance > 0) {
                    payable(owner()).transfer(remainingBalance);
                }

                emit TokenizationEnded(totalDistributed, remainingBalance);
            }

            function getInvestorShare(address investor) public view returns (uint256) {
                uint256 totalSupply = totalSupply();
                if (totalSupply == 0) return 0;

                return (balanceOf(investor) * 10000) / totalSupply; // Доля в базисных пунктах
            }

            function getProjectedReturns(address investor, uint256 estimatedIncome) public view returns (uint256) {
                uint256 share = getInvestorShare(investor);
                uint256 incomeToDistribute = (estimatedIncome * totalIncomeShare) / 10000;
                return (incomeToDistribute * share) / 10000;
            }

            // Запрет трансфера после окончания периода (опционально)
            function _beforeTokenTransfer(address from, address to, uint256 amount) 
                internal override 
            {
                super._beforeTokenTransfer(from, to, amount);

                // Можно добавить ограничения на трансфер
            }

            // Отказ от получения ETH напрямую (только через depositIncome)
            receive() external payable {
                revert("Use depositIncome() to deposit income");
            }
        }
        """

        try:
            compiled_contract = self.contract_manager.compile_solidity(contract_code)

            # Деплой контракта
            tx_hash = self.contract_manager.w3.eth.contract(
                abi=compiled_contract['abi'],
                bytecode=compiled_contract['bytecode']
            ).constructor(
                "Freelancer Income Token",
                "FIT",
                owner_address,
                3000,  # 30% дохода для инвесторов
                7776000  # 90 дней период токенизации
            ).transact({'from': owner_address})

            tx_receipt = self.contract_manager.w3.eth.wait_for_transaction_receipt(tx_hash)
            contract_address = tx_receipt.contractAddress

            self.tokenization_contract = self.contract_manager.w3.eth.contract(
                address=contract_address,
                abi=compiled_contract['abi']
            )

            logger.info(f"Контракт токенизации доходов задеплоен: {contract_address}")

            return {
                "success": True,
                "contract_address": contract_address,
                "transaction_hash": tx_hash.hex(),
                "abi": compiled_contract['abi'],
                "token_symbol": "FIT",
                "income_share_percent": 30,
                "period_days": 90
            }

        except Exception as e:
            logger.error(f"Ошибка деплоя контракта токенизации: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }

    async def create_income_stream(self,
                                   freelancer_address: str,
                                   stream_name: str,
                                   description: str,
                                   estimated_monthly_income: float,
                                   tokenization_percentage: float,
                                   period_days: int,
                                   min_investment: float,
                                   max_investment: float,
                                   private_key: str) -> Dict[str, Any]:
        """
        Создание нового потока дохода для токенизации
        """
        if not self.tokenization_contract:
            deploy_result = await self.deploy_tokenization_contract(freelancer_address)
            if not deploy_result["success"]:
                return {
                    "success": False,
                    "error": f"Не удалось задеплоить контракт токенизации: {deploy_result.get('error')}"
                }

        # Валидация параметров
        if not (5 <= tokenization_percentage <= 50):
            return {"success": False, "error": "Доля для токенизации должна быть от 5% до 50%"}

        if not (30 <= period_days <= 365):
            return {"success": False, "error": "Период токенизации должен быть от 30 до 365 дней"}

        if min_investment < 0.01:
            return {"success": False, "error": "Минимальная инвестиция должна быть не менее 0.01 ETH"}

        if max_investment < min_investment:
            return {"success": False, "error": "Максимальная инвестиция должна быть больше минимальной"}

        # Расчет параметров
        income_share_bp = int(tokenization_percentage * 100)  # в базисных пунктах
        period_seconds = period_days * 86400

        # Создание записи о потоке дохода в БД
        stream_id = f"stream_{int(datetime.now().timestamp())}_{hash(freelancer_address) % 10000}"

        stream_data = {
            "stream_id": stream_id,
            "freelancer_address": freelancer_address,
            "stream_name": stream_name,
            "description": description,
            "estimated_monthly_income": estimated_monthly_income,
            "tokenization_percentage": tokenization_percentage,
            "period_days": period_days,
            "min_investment": min_investment,
            "max_investment": max_investment,
            "income_share_bp": income_share_bp,
            "period_seconds": period_seconds,
            "created_at": datetime.now().isoformat(),
            "status": "active",
            "total_invested": 0.0,
            "investors_count": 0,
            "contract_address": self.tokenization_contract.address
        }

        await self.db_service.save_income_stream(stream_data)
        self.income_streams[stream_id] = stream_data

        logger.info(f"Создан поток дохода {stream_id} для фрилансера {freelancer_address}")

        return {
            "success": True,
            "stream_id": stream_id,
            "freelancer_address": freelancer_address,
            "stream_name": stream_name,
            "tokenization_percentage": tokenization_percentage,
            "period_days": period_days,
            "estimated_annual_return": f"{tokenization_percentage * 12 * estimated_monthly_income / max_investment:.1f}%",
            # Упрощенный расчет
            "min_investment_eth": min_investment,
            "contract_address": self.tokenization_contract.address,
            "purchase_url": f"https://freelance-automation.io/invest/{stream_id}"
        }

    async def purchase_income_tokens(self,
                                     stream_id: str,
                                     investor_address: str,
                                     amount_eth: float,
                                     private_key: str) -> Dict[str, Any]:
        """
        Покупка токенов дохода инвестором
        """
        if stream_id not in self.income_streams:
            return {"success": False, "error": f"Поток дохода {stream_id} не найден"}

        stream = self.income_streams[stream_id]

        # Валидация суммы инвестиции
        if amount_eth < stream["min_investment"]:
            return {
                "success": False,
                "error": f"Минимальная сумма инвестиции: {stream['min_investment']} ETH"
            }

        if amount_eth > stream["max_investment"]:
            return {
                "success": False,
                "error": f"Максимальная сумма инвестиции: {stream['max_investment']} ETH"
            }

        try:
            # Отправка транзакции покупки токенов
            tx = self.tokenization_contract.functions.purchaseTokens().build_transaction({
                'from': investor_address,
                'value': Web3.to_wei(amount_eth, 'ether'),
                'nonce': self.contract_manager.w3.eth.get_transaction_count(investor_address),
                'gas': 200000,
                'gasPrice': self.contract_manager.w3.eth.gas_price
            })

            signed_tx = self.contract_manager.w3.eth.account.sign_transaction(tx, private_key)
            tx_hash = self.contract_manager.w3.eth.send_raw_transaction(signed_tx.rawTransaction)
            receipt = self.contract_manager.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

            if receipt.status == 1:
                # Обновление данных о потоке
                stream["total_invested"] += amount_eth
                stream["investors_count"] += 1

                await self.db_service.update_income_stream(stream_id, {
                    "total_invested": stream["total_invested"],
                    "investors_count": stream["investors_count"],
                    "last_investment_at": datetime.now().isoformat()
                })

                # Запись инвестиции в БД
                await self.db_service.save_investment({
                    "stream_id": stream_id,
                    "investor_address": investor_address,
                    "amount_eth": amount_eth,
                    "timestamp": datetime.now().isoformat(),
                    "transaction_hash": tx_hash.hex()
                })

                logger.info(f"Инвестиция {amount_eth} ETH успешно выполнена в поток {stream_id}")

                return {
                    "success": True,
                    "stream_id": stream_id,
                    "investor": investor_address,
                    "amount_eth": amount_eth,
                    "transaction_hash": tx_hash.hex(),
                    "blockchain_explorer_url": f"https://etherscan.io/tx/{tx_hash.hex()}",
                    "estimated_monthly_return": amount_eth * stream["tokenization_percentage"] / 100 * stream[
                        "estimated_monthly_income"] / stream["total_invested"],
                    "tokens_received": amount_eth * 100  # 1 ETH = 100 токенов
                }
            else:
                return {
                    "success": False,
                    "error": "Транзакция покупки токенов не подтверждена"
                }

        except Exception as e:
            logger.error(f"Ошибка покупки токенов: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }

    async def deposit_income(self,
                             stream_id: str,
                             freelancer_address: str,
                             amount_eth: float,
                             private_key: str) -> Dict[str, Any]:
        """
        Депозит дохода фрилансером для распределения инвесторам
        """
        if stream_id not in self.income_streams:
            return {"success": False, "error": f"Поток дохода {stream_id} не найден"}

        stream = self.income_streams[stream_id]

        try:
            # Отправка дохода в контракт
            tx = self.tokenization_contract.functions.depositIncome().build_transaction({
                'from': freelancer_address,
                'value': Web3.to_wei(amount_eth, 'ether'),
                'nonce': self.contract_manager.w3.eth.get_transaction_count(freelancer_address),
                'gas': 300000,
                'gasPrice': self.contract_manager.w3.eth.gas_price
            })

            signed_tx = self.contract_manager.w3.eth.account.sign_transaction(tx, private_key)
            tx_hash = self.contract_manager.w3.eth.send_raw_transaction(signed_tx.rawTransaction)
            receipt = self.contract_manager.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

            if receipt.status == 1:
                # Расчет распределения
                income_for_investors = amount_eth * stream["tokenization_percentage"] / 100
                income_for_freelancer = amount_eth - income_for_investors

                # Запись депозита в БД
                await self.db_service.save_income_deposit({
                    "stream_id": stream_id,
                    "freelancer_address": freelancer_address,
                    "total_amount_eth": amount_eth,
                    "investors_share_eth": income_for_investors,
                    "freelancer_share_eth": income_for_freelancer,
                    "timestamp": datetime.now().isoformat(),
                    "transaction_hash": tx_hash.hex()
                })

                logger.info(f"Доход {amount_eth} ETH успешно депонирован для потока {stream_id}")

                return {
                    "success": True,
                    "stream_id": stream_id,
                    "total_amount_eth": amount_eth,
                    "investors_share_eth": income_for_investors,
                    "freelancer_share_eth": income_for_freelancer,
                    "transaction_hash": tx_hash.hex(),
                    "distribution_details": f"{stream['tokenization_percentage']}% инвесторам, {100 - stream['tokenization_percentage']}% фрилансеру"
                }
            else:
                return {
                    "success": False,
                    "error": "Транзакция депозита дохода не подтверждена"
                }

        except Exception as e:
            logger.error(f"Ошибка депозита дохода: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }

    async def get_stream_analytics(self, stream_id: str) -> Dict[str, Any]:
        """Получение аналитики потока дохода"""
        if stream_id not in self.income_streams:
            return {"error": f"Поток дохода {stream_id} не найден"}

        stream = self.income_streams[stream_id]

        # Расчет метрик
        days_active = (datetime.now() - datetime.fromisoformat(stream["created_at"])).days
        days_remaining = max(0, stream["period_days"] - days_active)

        # Прогноз годовой доходности
        if stream["total_invested"] > 0:
            projected_annual_income = stream["estimated_monthly_income"] * 12
            investor_share = projected_annual_income * stream["tokenization_percentage"] / 100
            roi_percent = (investor_share / stream["total_invested"]) * 100
        else:
            roi_percent = 0

        return {
            "stream_id": stream_id,
            "stream_name": stream["stream_name"],
            "freelancer_address": stream["freelancer_address"],
            "status": stream["status"],
            "days_active": days_active,
            "days_remaining": days_remaining,
            "period_days": stream["period_days"],
            "tokenization_percentage": stream["tokenization_percentage"],
            "total_invested_eth": stream["total_invested"],
            "investors_count": stream["investors_count"],
            "estimated_monthly_income": stream["estimated_monthly_income"],
            "projected_annual_roi_percent": round(roi_percent, 2),
            "min_investment_eth": stream["min_investment"],
            "max_investment_eth": stream["max_investment"],
            "contract_address": stream["contract_address"],
            "blockchain_url": f"https://etherscan.io/token/{stream['contract_address']}",
            "last_updated": datetime.now().isoformat()
        }

    async def end_tokenization_period(self, stream_id: str, owner_address: str, private_key: str) -> Dict[str, Any]:
        """
        Завершение периода токенизации
        """
        if stream_id not in self.income_streams:
            return {"success": False, "error": f"Поток дохода {stream_id} не найден"}

        stream = self.income_streams[stream_id]

        # Проверка срока действия
        days_active = (datetime.now() - datetime.fromisoformat(stream["created_at"])).days
        if days_active < stream["period_days"]:
            return {
                "success": False,
                "error": f"Период токенизации еще не завершен. Осталось {stream['period_days'] - days_active} дней"
            }

        try:
            # Вызов функции завершения в контракте
            tx = self.tokenization_contract.functions.endTokenization().build_transaction({
                'from': owner_address,
                'nonce': self.contract_manager.w3.eth.get_transaction_count(owner_address),
                'gas': 200000,
                'gasPrice': self.contract_manager.w3.eth.gas_price
            })

            signed_tx = self.contract_manager.w3.eth.account.sign_transaction(tx, private_key)
            tx_hash = self.contract_manager.w3.eth.send_raw_transaction(signed_tx.rawTransaction)
            receipt = self.contract_manager.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

            if receipt.status == 1:
                # Обновление статуса потока
                await self.db_service.update_income_stream(stream_id, {
                    "status": "completed",
                    "ended_at": datetime.now().isoformat(),
                    "final_transaction_hash": tx_hash.hex()
                })

                logger.info(f"Период токенизации для потока {stream_id} успешно завершен")

                return {
                    "success": True,
                    "stream_id": stream_id,
                    "status": "completed",
                    "ended_at": datetime.now().isoformat(),
                    "transaction_hash": tx_hash.hex(),
                    "message": "Токенизация завершена. Инвесторы продолжат получать доход согласно условиям контракта."
                }
            else:
                return {
                    "success": False,
                    "error": "Транзакция завершения токенизации не подтверждена"
                }

        except Exception as e:
            logger.error(f"Ошибка завершения токенизации: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }