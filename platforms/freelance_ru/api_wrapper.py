# platforms/freelance_ru/api_wrapper.py
"""
API Wrapper for Freelance.ru — official and unofficial endpoints.
Provides robust, authenticated, monitored access to job listings, bids, messages, and contracts.
Designed for autonomous operation with self-healing and rate-limit compliance.
"""

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urljoin

import aiohttp
from aiohttp import ClientSession, ClientResponse, ClientError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from core.config.unified_config_manager import UnifiedConfigManager
from core.security.advanced_crypto_system import AdvancedCryptoSystem
from core.monitoring.intelligent_monitoring_system import IntelligentMonitoringSystem
from core.dependency.service_locator import ServiceLocator

# Type alias for clarity
JsonDict = Dict[str, Any]

class FreelanceRuAPIWrapper:
    """
    Thread-safe, async-compatible wrapper for Freelance.ru API.
    Handles auth, retries, monitoring, and error recovery autonomously.
    """

    BASE_URL = "https://freelance.ru"
    API_BASE = "https://api.freelance.ru/v1"

    def __init__(
        self,
        config_manager: Optional[UnifiedConfigManager] = None,
        crypto_system: Optional[AdvancedCryptoSystem] = None,
        monitor: Optional[IntelligentMonitoringSystem] = None,
    ):
        self.logger = logging.getLogger("FreelanceRuAPI")
        self._session: Optional[ClientSession] = None

        # Use service locator if dependencies not injected
        self.config = config_manager or ServiceLocator.get("config")
        self.crypto = crypto_system or ServiceLocator.get("crypto")
        self.monitor = monitor or ServiceLocator.get("monitoring")

        # Load platform-specific config
        self.platform_config = self.config.get("platforms", {}).get("freelance_ru", {})
        self.api_key = self._load_api_key()
        self.user_agent = self.platform_config.get("user_agent", "AI-Freelancer-Autonomous/1.0")
        self.timeout = self.platform_config.get("timeout", 30)
        self.max_retries = self.platform_config.get("max_retries", 3)
        self.rate_limit_delay = self.platform_config.get("rate_limit_delay", 1.5)  # seconds

        self._last_request_time = 0.0

    def _load_api_key(self) -> str:
        """Securely load and decrypt API key from config."""
        encrypted_key = self.platform_config.get("encrypted_api_key")
        if not encrypted_key:
            raise ValueError("Missing 'encrypted_api_key' in freelance_ru config")
        return self.crypto.decrypt_secret(encrypted_key)

    async def _ensure_session(self) -> ClientSession:
        """Lazy-create and reuse aiohttp session."""
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(limit=20, limit_per_host=5)
            timeout = aiohttp.ClientTimeout(total=self.timeout)
            self._session = aiohttp.ClientSession(
                connector=connector,
                timeout=timeout,
                headers={
                    "User-Agent": self.user_agent,
                    "Accept": "application/json",
                    "Authorization": f"Bearer {self.api_key}",
                }
            )
        return self._session

    async def _respect_rate_limit(self):
        """Enforce polite request pacing to avoid bans."""
        now = time.time()
        elapsed = now - self._last_request_time
        if elapsed < self.rate_limit_delay:
            await asyncio.sleep(self.rate_limit_delay - elapsed)
        self._last_request_time = time.time()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((ClientError, asyncio.TimeoutError)),
        reraise=True
    )
    async def _make_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict] = None,
        json_data: Optional[JsonDict] = None,
        headers: Optional[Dict] = None,
    ) -> JsonDict:
        """Make a resilient HTTP request with monitoring and error context."""
        await self._respect_rate_limit()
        session = await self._ensure_session()
        url = urljoin(self.API_BASE, endpoint.lstrip("/"))

        try:
            self.logger.debug(f"📡 {method.upper()} {url} | params={params}")
            async with session.request(
                method, url, params=params, json=json_data, headers=headers
            ) as response:
                await self._log_response_metrics(response)

                if response.status == 429:
                    self.logger.warning("⚠️ Rate limit hit on Freelance.ru. Backing off...")
                    await asyncio.sleep(10)
                    raise aiohttp.ClientError("Rate limited")

                if response.status >= 400:
                    error_text = await response.text()
                    self.logger.error(f"❌ API Error {response.status}: {error_text}")
                    response.raise_for_status()

                data = await response.json(content_type=None)  # some APIs omit content-type
                self.monitor.record_metric("freelance_ru.successful_requests", 1)
                return data

        except Exception as e:
            self.monitor.record_metric("freelance_ru.failed_requests", 1)
            self.logger.exception(f"💥 Request failed: {e}")
            raise

    async def _log_response_metrics(self, response: ClientResponse):
        """Record latency and status for analytics."""
        latency = response.headers.get("X-Response-Time", "unknown")
        self.monitor.record_metric("freelance_ru.latency_ms", float(latency) if latency.replace('.', '').isdigit() else 0)
        self.monitor.record_metric(f"freelance_ru.status_{response.status}", 1)

    # --- Public API Methods ---

    async def get_active_jobs(self, category: Optional[str] = None, min_price: int = 0) -> List[JsonDict]:
        """
        Fetch active job listings with filtering.
        Supports category (e.g., 'transcription', 'translation') and min_price.
        """
        params = {
            "status": "active",
            "limit": 50,
            "offset": 0,
        }
        if category:
            params["category"] = category
        if min_price > 0:
            params["min_price"] = min_price

        data = await self._make_request("GET", "/jobs", params=params)
        return data.get("jobs", [])

    async def place_bid(self, job_id: str, proposal: str, price: int, delivery_days: int) -> JsonDict:
        """Submit a bid on a job."""
        payload = {
            "job_id": job_id,
            "proposal": proposal,
            "price": price,
            "delivery_days": delivery_days,
        }
        return await self._make_request("POST", "/bids", json_data=payload)

    async def get_conversation(self, job_id: str) -> List[JsonDict]:
        """Retrieve message history for a job."""
        return await self._make_request("GET", f"/conversations/{job_id}/messages")

    async def send_message(self, job_id: str, text: str) -> JsonDict:
        """Send a message to the client."""
        payload = {"job_id": job_id, "text": text}
        return await self._make_request("POST", "/messages", json_data=payload)

    async def get_job_details(self, job_id: str) -> JsonDict:
        """Get full job description and metadata."""
        return await self._make_request("GET", f"/jobs/{job_id}")

    async def close(self):
        """Gracefully close HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self.logger.info("🔌 Freelance.ru API session closed.")

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()