# AI_FREELANCE_AUTOMATION/platforms/upwork/api_wrapper.py
"""
Upwork API Wrapper — безопасный, отказоустойчивый клиент для работы с Upwork API.
Обеспечивает:
- Аутентификацию OAuth 2.0
- Автоматическое обновление токенов
- Rate-limit handling
- Retry с экспоненциальной задержкой
- Логирование и аудит
- Интеграцию с системой мониторинга и восстановления
"""

import asyncio
import logging
import time
from typing import Any, Dict, Optional, List, Union
from urllib.parse import urljoin

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from core.config.unified_config_manager import UnifiedConfigManager
from core.security.advanced_crypto_system import AdvancedCryptoSystem
from core.monitoring.intelligent_monitoring_system import IntelligentMonitoringSystem
from core.security.audit_logger import AuditLogger

logger = logging.getLogger("UpworkAPIWrapper")


class UpworkAPIWrapper:
    """
    Обертка над официальным REST API Upwork.
    Поддерживает все критические операции: поиск заказов, ставки, управление контрактами, сообщения.
    """

    BASE_URL = "https://www.upwork.com/api/"
    AUTH_URL = "https://www.upwork.com/api/auth/v1/oauth2/token"

    def __init__(
        self,
        config_manager: UnifiedConfigManager,
        crypto_system: AdvancedCryptoSystem,
        monitoring_system: Optional[IntelligentMonitoringSystem] = None,
        audit_logger: Optional[AuditLogger] = None,
    ):
        self.config = config_manager.get_section("platforms.upwork")
        self.crypto = crypto_system
        self.monitoring = monitoring_system
        self.audit = audit_logger or AuditLogger()

        # Загрузка и расшифровка учетных данных
        self.client_id = self.config.get("client_id")
        self.client_secret_encrypted = self.config.get("client_secret_encrypted")
        self.refresh_token_encrypted = self.config.get("refresh_token_encrypted")

        # Расшифровка секретов
        try:
            self.client_secret = self.crypto.decrypt(self.client_secret_encrypted)
            self.refresh_token = self.crypto.decrypt(self.refresh_token_encrypted)
        except Exception as e:
            logger.critical("❌ Failed to decrypt Upwork credentials", exc_info=True)
            raise RuntimeError("Upwork credential decryption failed") from e

        self.access_token: Optional[str] = None
        self.token_expires_at: float = 0
        self._http_client: Optional[httpx.AsyncClient] = None

        # Инициализация HTTP-клиента
        self._init_http_client()

        logger.info("✅ Upwork API Wrapper initialized successfully")

    def _init_http_client(self):
        """Инициализирует HTTP-клиент с настройками по умолчанию."""
        timeout = httpx.Timeout(30.0, connect=10.0)
        limits = httpx.Limits(max_connections=10, max_keepalive_connections=5)
        self._http_client = httpx.AsyncClient(timeout=timeout, limits=limits)

    async def _ensure_access_token(self):
        """Гарантирует наличие валидного access_token (обновляет при необходимости)."""
        if not self.access_token or time.time() >= self.token_expires_at - 60:
            await self._refresh_access_token()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
    )
    async def _refresh_access_token(self):
        """Обновляет access_token с использованием refresh_token."""
        logger.debug("🔄 Refreshing Upwork access token...")

        data = {
            "grant_type": "refresh_token",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": self.refresh_token,
        }

        try:
            response = await self._http_client.post(self.AUTH_URL, data=data)
            response.raise_for_status()
            token_data = response.json()

            self.access_token = token_data["access_token"]
            expires_in = token_data.get("expires_in", 3600)
            self.token_expires_at = time.time() + expires_in

            # Обновляем refresh_token, если он изменился
            if "refresh_token" in token_data:
                new_rt = token_data["refresh_token"]
                if new_rt != self.refresh_token:
                    self.refresh_token = new_rt
                    # TODO: Сохранить обновленный refresh_token в зашифрованном виде в конфиг
                    # Это требует обратной связи в config_manager — можно реализовать позже

            logger.info("✅ Upwork access token refreshed successfully")
            if self.monitoring:
                await self.monitoring.record_metric("upwork.token_refresh.success", 1)

        except Exception as e:
            logger.error("❌ Failed to refresh Upwork token", exc_info=True)
            if self.monitoring:
                await self.monitoring.record_metric("upwork.token_refresh.failure", 1)
            raise

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Выполняет защищенный HTTP-запрос к Upwork API."""
        await self._ensure_access_token()

        url = urljoin(self.BASE_URL, endpoint.lstrip("/"))
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
            "User-Agent": "AI-Freelance-Automation/1.0",
        }

        try:
            response = await self._http_client.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                json=json_data,
            )

            # Логируем статус
            self.audit.log_api_call(
                platform="upwork",
                endpoint=endpoint,
                method=method,
                status_code=response.status_code,
                success=response.is_success,
            )

            if response.status_code == 429:
                # Rate limit — ждем и повторяем
                retry_after = int(response.headers.get("Retry-After", 5))
                logger.warning(f"⚠️ Upwork rate limit hit. Retrying after {retry_after}s")
                await asyncio.sleep(retry_after)
                return await self._make_request(method, endpoint, params, json_data)

            response.raise_for_status()
            return response.json()

        except httpx.HTTPStatusError as e:
            logger.error(f"❌ Upwork API HTTP error: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error("💥 Unexpected error during Upwork API call", exc_info=True)
            raise

    # --- Публичные методы API ---

    async def search_jobs(
        self,
        query: str = "",
        budget_min: Optional[int] = None,
        category: Optional[str] = None,
        page: int = 1,
        per_page: int = 20,
    ) -> List[Dict[str, Any]]:
        """Поиск заказов по ключевым словам и фильтрам."""
        params = {
            "q": query,
            "page": page,
            "per_page": min(per_page, 100),  # Upwork ограничивает до 100
        }
        if budget_min:
            params["budget"] = budget_min
        if category:
            params["category"] = category

        result = await self._make_request("GET", "/profiles/v2/search/jobs.json", params=params)
        return result.get("jobs", [])

    async def get_job_details(self, job_id: str) -> Dict[str, Any]:
        """Получение полной информации о заказе."""
        return await self._make_request("GET", f"/jobs/v1/jobs/{job_id}.json")

    async def submit_proposal(
        self,
        job_id: str,
        cover_message: str,
        amount: Union[int, float],
        is_hourly: bool = False,
        weekly_hours: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Отправка ставки на заказ."""
        payload = {
            "job_id": job_id,
            "cover_message": cover_message,
            "amount": amount,
            "is_hourly": is_hourly,
        }
        if is_hourly and weekly_hours:
            payload["weekly_hours"] = weekly_hours

        return await self._make_request("POST", "/freelancers/v1/freelancer/proposals", json_data=payload)

    async def get_contracts(self) -> List[Dict[str, Any]]:
        """Получение активных контрактов."""
        result = await self._make_request("GET", "/contracts/v1/contracts")
        return result.get("contracts", [])

    async def send_message(self, contract_id: str, message: str) -> Dict[str, Any]:
        """Отправка сообщения клиенту по контракту."""
        payload = {"message": message}
        return await self._make_request("POST", f"/messages/v3/contracts/{contract_id}/threads", json_data=payload)

    async def close(self):
        """Корректное закрытие HTTP-клиента."""
        if self._http_client:
            await self._http_client.aclose()
            logger.info("🔌 Upwork API client closed")

    def __del__(self):
        # Предупреждение: не гарантируется вызов в asyncio
        # Лучше использовать async context manager
        pass


# Утилиты для удобства использования
class UpworkAPIContext:
    """Async context manager для автоматического закрытия клиента."""

    def __init__(self, **kwargs):
        self.wrapper = UpworkAPIWrapper(**kwargs)

    async def __aenter__(self) -> UpworkAPIWrapper:
        return self.wrapper

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.wrapper.close()