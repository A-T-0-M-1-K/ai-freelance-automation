# AI_FREELANCE_AUTOMATION/platforms/kwork/api_wrapper.py
"""
Kwork API Wrapper — безопасный, отказоустойчивый интерфейс для взаимодействия с Kwork.ru API.
Поддерживает:
- Авторизацию через токен
- Получение списка заказов
- Подачу заявок (бидов)
- Управление гигами (услугами)
- Общение с клиентами
- Обработку ошибок и автоматические повторы
- Логирование и аудит

Следует принципам:
- 100% автономности
- Самовосстановления
- Соответствия security-политике (PCI DSS, GDPR)
"""

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

import aiohttp
from aiohttp import ClientTimeout, ContentTypeError

from core.config.unified_config_manager import UnifiedConfigManager
from core.security.advanced_crypto_system import AdvancedCryptoSystem
from core.monitoring.intelligent_monitoring_system import IntelligentMonitoringSystem
from core.dependency.service_locator import ServiceLocator

# Инициализация логгера
logger = logging.getLogger("KworkAPIWrapper")


class KworkAPIWrapper:
    """
    Обертка над Kwork API с поддержкой асинхронных операций,
    автоматического восстановления и мониторинга.
    """

    def __init__(
        self,
        config_manager: Optional[UnifiedConfigManager] = None,
        crypto_system: Optional[AdvancedCryptoSystem] = None,
        monitor: Optional[IntelligentMonitoringSystem] = None,
    ):
        # Используем ServiceLocator, если компоненты не переданы явно
        self.config_manager = config_manager or ServiceLocator.get("config_manager")
        self.crypto = crypto_system or ServiceLocator.get("crypto_system")
        self.monitor = monitor or ServiceLocator.get("monitoring_system")

        # Загрузка конфигурации платформы
        self.platform_config = self.config_manager.get_platform_config("kwork")
        self.base_url = self.platform_config.get("api_base_url", "https://api.kwork.ru/")
        self.token_encrypted = self.platform_config.get("auth_token_encrypted")
        self.max_retries = self.platform_config.get("max_retries", 3)
        self.timeout_sec = self.platform_config.get("timeout_sec", 30)

        # Расшифровка токена
        try:
            self.auth_token = self.crypto.decrypt(self.token_encrypted)
        except Exception as e:
            logger.critical("❌ Не удалось расшифровать токен Kwork API", exc_info=True)
            raise RuntimeError("Kwork API token decryption failed") from e

        self.session: Optional[aiohttp.ClientSession] = None
        logger.info("✅ Kwork API Wrapper инициализирован")

    async def __aenter__(self):
        timeout = ClientTimeout(total=self.timeout_sec)
        self.session = aiohttp.ClientSession(
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {self.auth_token}",
                "Content-Type": "application/json",
                "User-Agent": "AI-Freelance-Automation/1.0"
            }
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
        if exc_type:
            logger.warning(f"⚠️ Сессия Kwork API завершена с ошибкой: {exc_val}")
        else:
            logger.debug("🔌 Сессия Kwork API закрыта корректно")

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Универсальный метод для выполнения запросов с retry и мониторингом.
        """
        url = urljoin(self.base_url.rstrip("/") + "/", endpoint.lstrip("/"))
        attempt = 0

        while attempt <= self.max_retries:
            try:
                logger.debug(f"📡 Отправка {method.upper()} запроса на {url} (попытка {attempt + 1})")
                async with self.session.request(method, url, json=data, params=params) as resp:
                    # Логируем статус
                    self.monitor.log_metric("kwork_api_response_code", resp.status)

                    if resp.status == 200:
                        try:
                            result = await resp.json()
                            logger.debug(f"✅ Успешный ответ от Kwork API: {result.get('success', True)}")
                            return result
                        except ContentTypeError:
                            text = await resp.text()
                            logger.error(f"❗ Некорректный JSON от Kwork API: {text[:200]}")
                            raise ValueError("Invalid JSON response from Kwork API")

                    elif resp.status == 429:
                        backoff = (2 ** attempt) + 1
                        logger.warning(f"⏳ Rate limit достигнут. Пауза {backoff} сек...")
                        await asyncio.sleep(backoff)
                        attempt += 1
                        continue

                    elif resp.status in (500, 502, 503, 504):
                        logger.warning(f"☁️ Серверная ошибка Kwork API: {resp.status}")
                        attempt += 1
                        await asyncio.sleep(2 ** attempt)
                        continue

                    else:
                        error_text = await resp.text()
                        logger.error(f"🚫 Ошибка Kwork API ({resp.status}): {error_text}")
                        raise RuntimeError(f"Kwork API error {resp.status}: {error_text}")

            except aiohttp.ClientError as e:
                logger.warning(f"🌐 Сетевая ошибка при запросе к Kwork (попытка {attempt + 1}): {e}")
                attempt += 1
                if attempt > self.max_retries:
                    self.monitor.log_anomaly("kwork_api_network_failure", {"error": str(e)})
                    raise
                await asyncio.sleep(2 ** attempt)

        raise RuntimeError("Превышено максимальное количество попыток запроса к Kwork API")

    async def get_active_jobs(self, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Получает список активных заказов (в категории, если указана).
        """
        params = {"category": category} if category else {}
        response = await self._make_request("GET", "/projects", params=params)
        if not response.get("success"):
            raise RuntimeError(f"Не удалось получить заказы: {response.get('message')}")
        return response.get("data", [])

    async def place_bid(self, project_id: str, price: float, days: int, description: str) -> bool:
        """
        Подает заявку на заказ.
        """
        payload = {
            "project_id": project_id,
            "price": price,
            "days": days,
            "description": description
        }
        response = await self._make_request("POST", "/bid", data=payload)
        success = response.get("success", False)
        if success:
            logger.info(f"✅ Заявка на проект {project_id} успешно отправлена")
            self.monitor.log_metric("kwork_bids_placed", 1)
        else:
            logger.error(f"❌ Ошибка подачи заявки: {response.get('message')}")
        return success

    async def get_conversations(self) -> List[Dict[str, Any]]:
        """
        Получает список диалогов с клиентами.
        """
        response = await self._make_request("GET", "/conversations")
        return response.get("data", [])

    async def send_message(self, conversation_id: str, text: str) -> bool:
        """
        Отправляет сообщение клиенту.
        """
        payload = {"conversation_id": conversation_id, "text": text}
        response = await self._make_request("POST", "/message", data=payload)
        return response.get("success", False)

    async def get_gigs(self) -> List[Dict[str, Any]]:
        """
        Получает список собственных гигов (услуг).
        """
        response = await self._make_request("GET", "/gigs")
        return response.get("data", [])

    async def update_gig(self, gig_id: str, updates: Dict[str, Any]) -> bool:
        """
        Обновляет гиг (например, цену или описание).
        """
        payload = {"gig_id": gig_id, **updates}
        response = await self._make_request("PUT", "/gig", data=payload)
        return response.get("success", False)


# Фабричный метод для ServiceLocator
def create_kwork_api_wrapper() -> KworkAPIWrapper:
    """Фабрика для создания экземпляра KworkAPIWrapper."""
    return KworkAPIWrapper()


# Регистрация в ServiceLocator (выполняется один раз при старте)
ServiceLocator.register_factory("kwork_api", create_kwork_api_wrapper)