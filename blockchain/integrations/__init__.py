# AI_FREELANCE_AUTOMATION/blockchain/integrations/__init__.py
"""
Модуль интеграций с блокчейн-сетями.
Обеспечивает унифицированный интерфейс для взаимодействия с различными блокчейн-платформами
(Ethereum, Polygon, Binance Smart Chain и др.) в рамках автономной фриланс-системы.

Цели:
- Абстрагировать детали конкретных сетей
- Поддерживать горячую замену провайдеров
- Обеспечивать безопасность транзакций
- Интегрироваться с ядром через DI/Service Locator

Архитектурные принципы:
- Изоляция: каждый интеграционный адаптер работает в своём контексте
- Расширяемость: легко добавлять новые сети через плагины
- Безопасность: все ключи и подписи обрабатываются через core.security
- Надёжность: автоматическая повторная отправка при ошибках сети
"""

from typing import Dict, Type
from abc import ABC, abstractmethod

# Типизация для реестра интеграций
BlockchainIntegrationRegistry = Dict[str, Type["BaseBlockchainIntegration"]]


class BaseBlockchainIntegration(ABC):
    """
    Базовый абстрактный класс для всех блокчейн-интеграций.
    Гарантирует единый интерфейс для ядра системы.
    """

    @abstractmethod
    async def connect(self) -> bool:
        """Устанавливает соединение с блокчейн-сетью."""
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """Завершает соединение."""
        pass

    @abstractmethod
    async def get_balance(self, address: str) -> float:
        """Возвращает баланс кошелька в нативной валюте сети."""
        pass

    @abstractmethod
    async def send_transaction(self, to: str, amount: float, data: str = "") -> str:
        """Отправляет транзакцию. Возвращает хэш транзакции."""
        pass

    @abstractmethod
    async def call_contract(self, contract_address: str, function_name: str, *args) -> any:
        """Вызывает функцию смарт-контракта без изменения состояния."""
        pass

    @abstractmethod
    async def transact_contract(self, contract_address: str, function_name: str, *args) -> str:
        """Отправляет транзакцию в смарт-контракт. Возвращает хэш."""
        pass

    @abstractmethod
    def is_connected(self) -> bool:
        """Проверяет текущее состояние подключения."""
        pass


# Реестр доступных интеграций (заполняется при импорте модулей)
INTEGRATION_REGISTRY: BlockchainIntegrationRegistry = {}


def register_integration(network_name: str, integration_class: Type[BaseBlockchainIntegration]):
    """
    Регистрирует новую блокчейн-интеграцию в глобальном реестре.
    Используется декораторами в конкретных файлах интеграций.
    """
    if network_name in INTEGRATION_REGISTRY:
        raise ValueError(f"Интеграция для сети '{network_name}' уже зарегистрирована.")
    INTEGRATION_REGISTRY[network_name] = integration_class


# Утилита для получения интеграции по имени сети
def get_integration(network_name: str) -> Type[BaseBlockchainIntegration]:
    """
    Возвращает класс интеграции по имени сети.
    Выбрасывает KeyError, если интеграция не найдена.
    """
    return INTEGRATION_REGISTRY[network_name]


# Явный импорт для активации регистрации (если файлы существуют)
# Это позволяет избежать циклических импортов и поддерживает lazy-loading
try:
    from .ethereum_integration import EthereumIntegration  # noqa: F401
except ImportError:
    pass

try:
    from .polygon_integration import PolygonIntegration  # noqa: F401
except ImportError:
    pass

try:
    from .binance_integration import BinanceIntegration  # noqa: F401
except ImportError:
    pass

# Добавьте другие импорты по мере расширения поддержки сетей

__all__ = [
    "BaseBlockchainIntegration",
    "INTEGRATION_REGISTRY",
    "register_integration",
    "get_integration",
]