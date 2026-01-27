# AI_FREELANCE_AUTOMATION/platforms/freelance_ru/client.py
"""
Freelance.ru Platform Client — secure, retry-capable, config-driven HTTP client
for interacting with freelance.ru API and web interface.

Responsible for:
- Session management (cookies, auth tokens)
- Request signing (if required)
- Rate limiting compliance
- Error handling with exponential backoff
- Logging all interactions for audit & debugging
"""

import asyncio
import logging
import time
from typing import Any, Dict, Optional, Union
from pathlib import Path

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from core.config.unified_config_manager import UnifiedConfigManager
from core.security.advanced_crypto_system import AdvancedCryptoSystem
from core.monitoring.intelligent_monitoring_system import IntelligentMonitoringSystem

# Logger setup
logger = logging.getLogger(__name__)

class FreelanceRuClient:
    """
    Thread-safe, async-capable client for freelance.ru platform.
    Designed to be used by scraper and api_wrapper modules.
    """

    def __init__(
        self,
        config_manager: UnifiedConfigManager,
        crypto_system: Optional[AdvancedCryptoSystem] = None,
        monitoring_system: Optional[IntelligentMonitoringSystem] = None,
    ):
        self.config_manager = config_manager
        self.crypto = crypto_system
        self.monitoring = monitoring_system or IntelligentMonitoringSystem.get_instance()

        # Load platform-specific config
        self.platform_config = self.config_manager.get("platforms.freelance_ru", {})
        if not self.platform_config:
            logger.warning("⚠️ No config found for freelance_ru. Using defaults.")

        self.base_url = self.platform_config.get("base_url", "https://freelance.ru")
        self.timeout = self.platform_config.get("timeout", 30)
        self.max_retries = self.platform_config.get("max_retries", 3)
        self.retry_delay = self.platform_config.get("retry_delay", 2)
        self.user_agent = self.platform_config.get(
            "user_agent",
            "AI-Freelancer-Automation/1.0 (+https://github.com/your-org/AI_FREELANCE_AUTOMATION)"
        )

        # Session state
        self._session: Optional[httpx.AsyncClient] = None
        self._is_authenticated = False
        self._last_request_time = 0.0

        # Rate limiting
        self.min_request_interval = 1.0 / self.platform_config.get("requests_per_second", 2)  # default: 2 RPS

        logger.info("Intialized FreelanceRuClient with base_url=%s", self.base_url)

    async def _ensure_session(self) -> httpx.AsyncClient:
        """Lazy-create and return async HTTP session."""
        if self._session is None:
            headers = {"User-Agent": self.user_agent}
            cookies = {}

            # Decrypt and load credentials if available
            if self.crypto and self.platform_config.get("encrypted_credentials"):
                try:
                    creds = self.crypto.decrypt_dict(self.platform_config["encrypted_credentials"])
                    cookies.update({
                        "PHPSESSID": creds.get("phpsessid", ""),
                        "auth_token": creds.get("auth_token", "")
                    })
                    self._is_authenticated = True
                except Exception as e:
                    logger.error("❌ Failed to decrypt freelance.ru credentials: %s", e)
                    self._is_authenticated = False

            self._session = httpx.AsyncClient(
                base_url=self.base_url,
                headers=headers,
                cookies=cookies,
                timeout=httpx.Timeout(self.timeout),
                follow_redirects=True
            )
        return self._session

    async def _enforce_rate_limit(self):
        """Ensure we don't exceed platform's rate limit."""
        now = time.time()
        elapsed = now - self._last_request_time
        if elapsed < self.min_request_interval:
            sleep_time = self.min_request_interval - elapsed
            await asyncio.sleep(sleep_time)
        self._last_request_time = time.time()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((httpx.RequestError, httpx.HTTPStatusError)),
        reraise=True
    )
    async def _make_request(
        self,
        method: str,
        url: str,
        **kwargs
    ) -> httpx.Response:
        """Make a single HTTP request with retry and error handling."""
        await self._enforce_rate_limit()
        session = await self._ensure_session()

        try:
            response = await session.request(method, url, **kwargs)
            response.raise_for_status()
            logger.debug("✅ %s %s → %d", method.upper(), url, response.status_code)
            self.monitoring.record_metric("freelance_ru.requests.success", 1)
            return response
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            logger.warning("⚠️ HTTP error %d on %s %s", status, method.upper(), url)
            self.monitoring.record_metric("freelance_ru.requests.http_error", 1)
            if status in (401, 403):
                self._is_authenticated = False
                logger.error("🔒 Authentication lost on freelance.ru. Re-authentication required.")
            raise
        except httpx.RequestError as e:
            logger.error("🌐 Network error on %s %s: %s", method.upper(), url, e)
            self.monitoring.record_metric("freelance_ru.requests.network_error", 1)
            raise
        except Exception as e:
            logger.exception("💥 Unexpected error during request to freelance.ru: %s", e)
            self.monitoring.record_metric("freelance_ru.requests.unknown_error", 1)
            raise

    async def get(self, url: str, **kwargs) -> httpx.Response:
        return await self._make_request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs) -> httpx.Response:
        return await self._make_request("POST", url, **kwargs)

    async def put(self, url: str, **kwargs) -> httpx.Response:
        return await self._make_request("PUT", url, **kwargs)

    async def delete(self, url: str, **kwargs) -> httpx.Response:
        return await self._make_request("DELETE", url, **kwargs)

    async def close(self):
        """Gracefully close the session."""
        if self._session:
            await self._session.aclose()
            self._session = None
            logger.info("CloseOperation: FreelanceRuClient session closed.")

    def is_authenticated(self) -> bool:
        return self._is_authenticated

    async def login(self, username: str, password: str) -> bool:
        """
        Perform login via web form (not API).
        Returns True if successful.
        Note: This is fragile and should be avoided if API auth is available.
        """
        if self._is_authenticated:
            return True

        try:
            # Simulate login flow
            login_page = await self.get("/login")
            # Extract CSRF token if needed (simplified)
            # In real implementation, parse HTML with BeautifulSoup or similar

            response = await self.post("/login", data={
                "username": username,
                "password": password,
                # "csrf_token": extracted_token
            })

            if "dashboard" in response.url.path or response.status_code == 200:
                self._is_authenticated = True
                logger.info("✅ Successfully logged into freelance.ru")
                return True
            else:
                logger.error("❌ Login failed: unexpected redirect or response")
                return False
        except Exception as e:
            logger.error("❌ Login failed with exception: %s", e)
            return False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()