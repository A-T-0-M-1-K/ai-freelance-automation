# platforms/kwork/client.py
"""
Kwork Platform Client — официальный клиент для взаимодействия с API Kwork.ru.
Реализует аутентификацию, получение заказов, отправку ставок, управление гигами.
Интегрируется с core.security, core.config, core.monitoring и core.dependency.
"""

import asyncio
import json
import logging
from typing import Dict, List, Optional, Any
from urllib.parse import urljoin

import aiohttp
from aiohttp import ClientSession, ClientResponseError, ClientTimeout

from core.config.unified_config_manager import UnifiedConfigManager
from core.security.advanced_crypto_system import AdvancedCryptoSystem
from core.monitoring.intelligent_monitoring_system import IntelligentMonitoringSystem
from core.dependency.service_locator import ServiceLocator

# Инициализация логгера
logger = logging.getLogger("KworkClient")


class KworkClient:
    """
    Асинхронный клиент для платформы Kwork.ru.
    Поддерживает:
      - Авторизацию через токен/cookies
      - Получение списка заказов (gigs)
      - Фильтрацию по категориям и ключевым словам
      - Отправку предложений (bids)
      - Обновление статуса гигов
      - Мониторинг состояния соединения
    """

    BASE_URL = "https://kwork.ru"
    API_BASE = "https://api.kwork.ru"

    def __init__(
        self,
        config_manager: Optional[UnifiedConfigManager] = None,
        crypto_system: Optional[AdvancedCryptoSystem] = None,
        monitor: Optional[IntelligentMonitoringSystem] = None,
    ):
        """
        Инициализация клиента.
        Если компоненты не переданы — загружаются через ServiceLocator.
        """
        self.config = config_manager or ServiceLocator.get("config")
        self.crypto = crypto_system or ServiceLocator.get("crypto")
        self.monitor = monitor or ServiceLocator.get("monitoring")

        # Загрузка конфигурации Kwork
        self.platform_config = self.config.get("platforms", {}).get("kwork", {})
        if not self.platform_config:
            raise ValueError("Kwork platform configuration not found in config.")

        self.session: Optional[ClientSession] = None
        self._auth_token: Optional[str] = None
        self._user_id: Optional[str] = None
        self._is_authenticated = False

        # Таймауты
        self.timeout = ClientTimeout(
            total=self.platform_config.get("timeout", 30),
            connect=self.platform_config.get("connect_timeout", 10),
        )

        # Метрики
        self._metrics_prefix = "platform.kwork.client"
        logger.info("Intialized KworkClient with config: %s", self.platform_config.keys())

    async def _load_auth_credentials(self) -> Dict[str, str]:
        """Загружает и расшифровывает учетные данные из защищенного хранилища."""
        encrypted_creds = self.config.get("secrets", {}).get("kwork", {})
        if not encrypted_creds:
            raise RuntimeError("Kwork credentials not configured in secrets.")

        try:
            decrypted = self.crypto.decrypt_dict(encrypted_creds)
            return {
                "login": decrypted["login"],
                "password": decrypted["password"],  # или token, если используется OAuth
            }
        except Exception as e:
            logger.error("Failed to decrypt Kwork credentials: %s", e)
            raise RuntimeError("Authentication data corrupted or missing.") from e

    async def authenticate(self) -> bool:
        """
        Выполняет вход в Kwork (через эмуляцию браузера или API, если доступно).
        В текущей версии Kwork не предоставляет публичное API для фрилансеров,
        поэтому используется headless-совместимый HTTP-клиент с cookies.
        """
        if self._is_authenticated:
            return True

        try:
            creds = await self._load_auth_credentials()
            # Примечание: Kwork требует авторизацию через форму + cookies.
            # Для автоматизации используется сессия с сохранением cookies.
            async with aiohttp.ClientSession(timeout=self.timeout) as temp_session:
                # Шаг 1: Получить CSRF-токен
                login_page = await temp_session.get(f"{self.BASE_URL}/login")
                login_page.raise_for_status()
                text = await login_page.text()
                # Извлечение CSRF (упрощённо; в продакшене — парсинг через BeautifulSoup или регулярки)
                csrf_token = self._extract_csrf(text)

                # Шаг 2: Отправить логин/пароль
                login_data = {
                    "login": creds["login"],
                    "password": creds["password"],
                    "csrf_token": csrf_token,
                }
                headers = {"Referer": f"{self.BASE_URL}/login"}
                resp = await temp_session.post(
                    f"{self.BASE_URL}/ajax/login", json=login_data, headers=headers
                )
                resp.raise_for_status()
                result = await resp.json()

                if result.get("success"):
                    # Сохраняем cookies и создаём постоянную сессию
                    self.session = aiohttp.ClientSession(
                        cookies=temp_session.cookie_jar.filter_cookies(self.BASE_URL),
                        timeout=self.timeout,
                    )
                    self._is_authenticated = True
                    self._user_id = result.get("user_id")
                    logger.info("✅ Successfully authenticated to Kwork as user %s", self._user_id)
                    self.monitor.increment_counter(f"{self._metrics_prefix}.auth.success")
                    return True
                else:
                    logger.warning("❌ Kwork login failed: %s", result.get("message"))
                    self.monitor.increment_counter(f"{self._metrics_prefix}.auth.failure")
                    return False

        except Exception as e:
            logger.exception("💥 Authentication error for Kwork: %s", e)
            self.monitor.increment_counter(f"{self._metrics_prefix}.auth.error")
            return False

    def _extract_csrf(self, html: str) -> str:
        """Извлекает CSRF-токен из HTML (заглушка; заменить на парсер в продакшене)."""
        # Пример: <input type="hidden" name="csrf_token" value="abc123">
        start = html.find('name="csrf_token"')
        if start == -1:
            raise ValueError("CSRF token not found in login page")
        start = html.find('value="', start)
        if start == -1:
            raise ValueError("CSRF value attribute not found")
        start += len('value="')
        end = html.find('"', start)
        return html[start:end]

    async def fetch_jobs(
        self, category: Optional[str] = None, keywords: Optional[List[str]] = None, limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        Получает список актуальных заказов (гигов) с Kwork.
        Возвращает унифицированный формат, совместимый с job_scraper.py.
        """
        if not self._is_authenticated:
            await self.authenticate()
            if not self._is_authenticated:
                raise RuntimeError("Cannot fetch jobs: not authenticated")

        try:
            params = {
                "category": category or "",
                "keywords": " ".join(keywords) if keywords else "",
                "limit": min(limit, 50),  # Kwork ограничивает выдачу
            }
            # Эмуляция запроса к поиску (реальный URL зависит от внутренней структуры Kwork)
            url = f"{self.BASE_URL}/search"
            async with self.session.get(url, params=params) as resp:
                resp.raise_for_status()
                html = await resp.text()

            # Парсинг HTML → список гигов (в продакшене использовать XPath/CSS + AI-фильтрацию)
            jobs = self._parse_jobs_from_html(html)
            self.monitor.increment_counter(f"{self._metrics_prefix}.jobs.fetched", len(jobs))
            logger.info("Fetched %d jobs from Kwork", len(jobs))
            return jobs

        except ClientResponseError as e:
            logger.error("HTTP error fetching Kwork jobs: %s", e)
            self.monitor.increment_counter(f"{self._metrics_prefix}.jobs.error")
            raise
        except Exception as e:
            logger.exception("Unexpected error during job fetch: %s", e)
            self.monitor.increment_counter(f"{self._metrics_prefix}.jobs.exception")
            raise

    def _parse_jobs_from_html(self, html: str) -> List[Dict[str, Any]]:
        """
        Парсит HTML-страницу и возвращает список заказов в унифицированном формате.
        Формат:
        {
            "job_id": str,
            "title": str,
            "description": str,
            "budget_min": float,
            "budget_max": float,
            "currency": str,
            "deadline_hours": int,
            "url": str,
            "skills": List[str],
            "client_rating": float,
            "platform": "kwork"
        }
        """
        # ЗАГЛУШКА: в реальной системе здесь будет полноценный парсер + ML-классификатор
        # Для демонстрации возвращаем пустой список
        logger.debug("Parsing jobs from HTML (stub implementation)")
        return []

    async def place_bid(self, job_id: str, proposal: str, price: float, delivery_time_hours: int) -> bool:
        """
        Отправляет предложение на заказ.
        В Kwork это эквивалентно созданию нового гига или отклику (в зависимости от типа заказа).
        """
        if not self._is_authenticated:
            await self.authenticate()
            if not self._is_authenticated:
                return False

        try:
            payload = {
                "job_id": job_id,
                "proposal": proposal,
                "price": price,
                "delivery_time": delivery_time_hours,
                "user_id": self._user_id,
            }
            # Условный endpoint (реальный зависит от внутреннего API Kwork)
            url = f"{self.BASE_URL}/ajax/send_proposal"
            async with self.session.post(url, json=payload) as resp:
                resp.raise_for_status()
                result = await resp.json()
                success = result.get("success", False)
                self.monitor.increment_counter(f"{self._metrics_prefix}.bids.sent", 1 if success else 0)
                logger.info("Bid sent for job %s: %s", job_id, "✅ Success" if success else "❌ Failed")
                return success

        except Exception as e:
            logger.exception("Failed to send bid to Kwork job %s: %s", job_id, e)
            self.monitor.increment_counter(f"{self._metrics_prefix}.bids.error")
            return False

    async def close(self):
        """Закрывает HTTP-сессию."""
        if self.session:
            await self.session.close()
            self.session = None
            self._is_authenticated = False
            logger.info("Kwork client session closed.")

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()


# Регистрация в ServiceLocator (опционально, при старте системы)
def register_kwork_client():
    """Регистрирует фабрику клиента в ServiceLocator."""
    def factory():
        return KworkClient()
    ServiceLocator.register("kwork_client", factory)


# При первом импорте — регистрируем
register_kwork_client()