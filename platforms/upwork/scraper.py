# AI_FREELANCE_AUTOMATION/platforms/upwork/scraper.py
"""
Upwork Job Scraper — интеллектуальный парсер заказов с платформы Upwork.
Использует официальное API (при наличии) и fallback-методы при его недоступности.
Поддерживает ML-фильтрацию, rate limiting, обход блокировок, логирование и восстановление.
"""

import asyncio
import json
import logging
import time
from typing import List, Dict, Any, Optional
from urllib.parse import urljoin

import aiohttp
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from core.config.unified_config_manager import UnifiedConfigManager
from core.security.advanced_crypto_system import AdvancedCryptoSystem
from core.monitoring.intelligent_monitoring_system import IntelligentMonitoringSystem
from core.dependency.service_locator import ServiceLocator
from services.storage.database_service import DatabaseService


class UpworkJobScraper:
    """
    Интеллектуальный скрапер для Upwork.
    Поддерживает:
      - Официальный API (OAuth2)
      - Headless-браузер как fallback (через плагин)
      - ML-фильтрацию нерелевантных заказов
      - Автоматическое обновление токенов
      - Соответствие ToS через rate limiting
    """

    def __init__(
        self,
        config_manager: Optional[UnifiedConfigManager] = None,
        crypto: Optional[AdvancedCryptoSystem] = None,
        monitor: Optional[IntelligentMonitoringSystem] = None,
        db: Optional[DatabaseService] = None
    ):
        self.logger = logging.getLogger("UpworkScraper")
        self.config = config_manager or ServiceLocator.get("config_manager")
        self.crypto = crypto or ServiceLocator.get("crypto_system")
        self.monitor = monitor or ServiceLocator.get("monitoring_system")
        self.db = db or ServiceLocator.get("database_service")

        # Загрузка конфигурации Upwork
        self.platform_config = self.config.get("platforms", {}).get("upwork", {})
        self.api_base_url = self.platform_config.get("api_base_url", "https://www.upwork.com/api/")
        self.scraping_delay = self.platform_config.get("scraping_delay_sec", 5)
        self.max_retries = self.platform_config.get("max_retries", 3)
        self.enabled = self.platform_config.get("enabled", False)

        # Аутентификация
        self.client_id = self._decrypt_secret("upwork_client_id")
        self.client_secret = self._decrypt_secret("upwork_client_secret")
        self.refresh_token = self._decrypt_secret("upwork_refresh_token")
        self.access_token = None
        self.token_expires_at = 0

        self.session: Optional[aiohttp.ClientSession] = None
        self._is_initialized = False

    def _decrypt_secret(self, key: str) -> str:
        """Безопасное извлечение и расшифровка секрета."""
        encrypted = self.config.get("secrets", {}).get(key)
        if not encrypted:
            raise ValueError(f"Missing required secret: {key}")
        return self.crypto.decrypt(encrypted)

    async def initialize(self):
        """Инициализация сессии и токена доступа."""
        if not self.enabled:
            self.logger.warning("Upwork scraping is disabled in config.")
            return

        self.session = aiohttp.ClientSession(
            headers={"User-Agent": "AI-Freelance-Automation/1.0"},
            timeout=aiohttp.ClientTimeout(total=30)
        )
        await self._refresh_access_token()
        self._is_initialized = True
        self.logger.info("✅ Upwork scraper initialized successfully.")

    async def shutdown(self):
        """Корректное завершение работы."""
        if self.session:
            await self.session.close()
        self._is_initialized = False
        self.logger.info("🔌 Upwork scraper shut down.")

    async def _refresh_access_token(self):
        """Обновление OAuth2 access token через refresh token."""
        if time.time() < self.token_expires_at - 60:
            return  # Токен ещё валиден

        url = "https://www.upwork.com/api/auth/v1/oauth2/token"
        payload = {
            "grant_type": "refresh_token",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": self.refresh_token
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, data=payload) as resp:
                    if resp.status != 200:
                        raise RuntimeError(f"Failed to refresh token: {resp.status} {await resp.text()}")
                    data = await resp.json()
                    self.access_token = data["access_token"]
                    self.token_expires_at = time.time() + data["expires_in"]
                    self.logger.debug("🔄 Upwork access token refreshed.")
        except Exception as e:
            self.monitor.log_anomaly("upwork_auth_failure", str(e))
            raise

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((aiohttp.ClientError, asyncio.TimeoutError))
    )
    async def _fetch_jobs_api(self, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Запрос к официальному API Upwork."""
        await self._refresh_access_token()

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/json"
        }

        url = urljoin(self.api_base_url, "profiles/v2/search/jobs.json")
        async with self.session.get(url, headers=headers, params=params) as resp:
            if resp.status == 429:
                self.logger.warning("⚠️ Rate limited by Upwork API. Backing off...")
                await asyncio.sleep(60)
                raise aiohttp.ClientError("Rate limited")
            elif resp.status != 200:
                text = await resp.text()
                self.logger.error(f"❌ API error {resp.status}: {text}")
                raise aiohttp.ClientError(f"HTTP {resp.status}: {text}")

            data = await resp.json()
            return data.get("jobs", [])

    async def scrape_jobs(
        self,
        query: str = "",
        budget_min: Optional[float] = None,
        category: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Основной метод сбора заказов.
        Возвращает нормализованные данные в едином формате.
        """
        if not self._is_initialized:
            await self.initialize()

        if not self.enabled:
            return []

        self.logger.info(f"🔍 Scraping Upwork jobs: query='{query}', budget≥{budget_min}, category={category}")

        # Параметры запроса к API
        params = {
            "q": query,
            "per_page": min(limit, 100),
            "sort": "recency"
        }
        if budget_min:
            params["budget"] = f"{budget_min}-"

        try:
            raw_jobs = await self._fetch_jobs_api(params)
            normalized_jobs = self._normalize_jobs(raw_jobs)
            filtered_jobs = await self._ml_filter_jobs(normalized_jobs)
            self.logger.info(f"✅ Retrieved and filtered {len(filtered_jobs)} relevant jobs from Upwork.")
            return filtered_jobs
        except Exception as e:
            self.logger.exception("💥 Error during Upwork scraping")
            self.monitor.log_anomaly("upwork_scraping_failure", str(e))
            # Fallback: попытка через headless-браузер (если плагин установлен)
            return await self._fallback_scrape(query, budget_min, category, limit)

    def _normalize_jobs(self, raw_jobs: List[Dict]) -> List[Dict[str, Any]]:
        """Приведение данных к единому внутреннему формату."""
        normalized = []
        for job in raw_jobs:
            normalized_job = {
                "platform": "upwork",
                "job_id": job.get("id"),
                "title": job.get("title", "").strip(),
                "description": job.get("description", "").strip(),
                "budget": {
                    "type": job.get("budget", {}).get("type", "hourly"),
                    "amount": job.get("budget", {}).get("amount", 0),
                    "currency": job.get("budget", {}).get("currency", "USD")
                },
                "skills": job.get("skills", []),
                "posted_at": job.get("date_created"),
                "client": {
                    "country": job.get("client", {}).get("country"),
                    "rating": job.get("client", {}).get("feedback", {}).get("score"),
                    "reviews": job.get("client", {}).get("feedback", {}).get("count", 0)
                },
                "url": f"https://www.upwork.com/jobs/{job.get('id')}",
                "raw_data": job  # для отладки и будущего анализа
            }
            normalized.append(normalized_job)
        return normalized

    async def _ml_filter_jobs(self, jobs: List[Dict]) -> List[Dict]:
        """Фильтрация через ML-модель (загружается через service locator)."""
        try:
            model_manager = ServiceLocator.get("ai_model_manager")
            filter_model = await model_manager.get_model("job_relevance_classifier")
            filtered = []
            for job in jobs:
                relevance_score = await filter_model.predict({
                    "title": job["title"],
                    "description": job["description"],
                    "skills": job["skills"]
                })
                if relevance_score >= 0.75:  # порог релевантности
                    job["relevance_score"] = float(relevance_score)
                    filtered.append(job)
            return filtered
        except Exception as e:
            self.logger.warning(f"⚠️ ML filtering failed, returning all jobs: {e}")
            return jobs

    async def _fallback_scrape(self, query, budget_min, category, limit) -> List[Dict[str, Any]]:
        """Резервный метод через headless-браузер (если плагин активен)."""
        try:
            plugin_manager = ServiceLocator.get("plugin_manager")
            if plugin_manager.is_plugin_active("upwork_browser_scraper"):
                browser_scraper = plugin_manager.get_plugin("upwork_browser_scraper")
                return await browser_scraper.scrape(query, budget_min, category, limit)
            else:
                self.logger.error("No fallback scraper available for Upwork.")
                return []
        except Exception as e:
            self.logger.exception("Fallback scraping also failed")
            return []

    async def save_jobs_to_db(self, jobs: List[Dict]):
        """Сохранение найденных заказов в базу данных."""
        if not jobs:
            return
        await self.db.insert_many("jobs_raw", jobs)
        self.logger.debug(f"💾 Saved {len(jobs)} Upwork jobs to database.")


# Экспорт для совместимости
__all__ = ["UpworkJobScraper"]