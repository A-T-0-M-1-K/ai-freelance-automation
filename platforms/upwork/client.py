# platforms/upwork/client.py
"""
Upwork Platform Client — secure, autonomous, and resilient interface to Upwork API.
Handles authentication, session management, rate limiting, error recovery,
and provides a clean abstraction for higher-level components (e.g., scraper, bid automator).
"""

import asyncio
import logging
import time
from typing import Optional, Dict, Any, List
from urllib.parse import urljoin

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from core.config.unified_config_manager import UnifiedConfigManager
from core.security.advanced_crypto_system import AdvancedCryptoSystem
from core.monitoring.intelligent_monitoring_system import IntelligentMonitoringSystem
from core.security.audit_logger import AuditLogger

logger = logging.getLogger("UpworkClient")


class UpworkClient:
    """
    Autonomous client for Upwork platform.
    Manages OAuth2 flow, token refresh, request signing, and resilient communication.
    """

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

        # API endpoints
        self.base_url = self.config.get("api_base_url", "https://www.upwork.com/api/")
        self.auth_url = self.config.get("auth_url", "https://www.upwork.com/ab/account-security/oauth2/authorize")
        self.token_url = self.config.get("token_url", "https://www.upwork.com/api/auth/v1/oauth2/token")

        # Credentials (decrypted at runtime)
        self.client_id = self._decrypt_credential("client_id")
        self.client_secret = self._decrypt_credential("client_secret")
        self.refresh_token = self._decrypt_credential("refresh_token")

        # State
        self.access_token: Optional[str] = None
        self.token_expires_at: float = 0
        self._http_client: Optional[httpx.AsyncClient] = None
        self._lock = asyncio.Lock()

        # Rate limiting
        self.last_request_time = 0.0
        self.min_request_interval = 1.0 / self.config.get("rate_limit_per_second", 5)  # e.g., 5 req/s → 0.2s

        logger.info("Intialized UpworkClient with secure credentials.")

    def _decrypt_credential(self, key: str) -> str:
        """Decrypt sensitive credential from config using the crypto system."""
        encrypted_value = self.config.get(f"credentials.{key}")
        if not encrypted_value:
            raise ValueError(f"Missing required Upwork credential: {key}")
        return self.crypto.decrypt(encrypted_value)

    async def _ensure_http_client(self):
        """Lazy initialize HTTP client."""
        if self._http_client is None:
            timeout = httpx.Timeout(
                connect=self.config.get("timeout.connect", 10.0),
                read=self.config.get("timeout.read", 30.0),
                write=self.config.get("timeout.write", 10.0),
                pool=self.config.get("timeout.pool", 5.0),
            )
            self._http_client = httpx.AsyncClient(timeout=timeout, follow_redirects=True)

    async def _ensure_access_token(self):
        """Ensure valid access token is available (refresh if needed)."""
        async with self._lock:
            now = time.time()
            if self.access_token is None or now >= self.token_expires_at - 60:  # refresh 1 min before expiry
                await self._refresh_access_token()

    async def _refresh_access_token(self):
        """Refresh OAuth2 access token using refresh token."""
        await self._ensure_http_client()
        try:
            data = {
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            }
            response = await self._http_client.post(self.token_url, data=data)
            response.raise_for_status()
            token_data = response.json()

            self.access_token = token_data["access_token"]
            expires_in = token_data.get("expires_in", 3600)
            self.token_expires_at = time.time() + expires_in

            # Securely store new refresh token if provided
            if "refresh_token" in token_data:
                self.refresh_token = token_data["refresh_token"]
                # 🔐 In real system: persist encrypted refresh token back to secure storage
                logger.info("Upwork access token refreshed successfully.")

        except Exception as e:
            self.audit.log_security_event(
                "upwork_token_refresh_failed",
                details={"error": str(e)},
                severity="high"
            )
            logger.error(f"Failed to refresh Upwork token: {e}", exc_info=True)
            raise RuntimeError("Upwork authentication failed") from e

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((httpx.RequestError, httpx.HTTPStatusError)),
    )
    async def _make_request(self, method: str, endpoint: str, **kwargs) -> httpx.Response:
        """Make an authenticated, rate-limited, retried HTTP request."""
        await self._ensure_access_token()
        await self._ensure_http_client()

        # Enforce rate limit
        async with self._lock:
            now = time.time()
            sleep_time = self.min_request_interval - (now - self.last_request_time)
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)
            self.last_request_time = time.time()

        url = urljoin(self.base_url, endpoint.lstrip("/"))
        headers = kwargs.pop("headers", {})
        headers.update({
            "Authorization": f"Bearer {self.access_token}",
            "User-Agent": "AI-Freelance-Automation/1.0",
            "Accept": "application/json",
        })

        response = await self._http_client.request(method, url, headers=headers, **kwargs)
        response.raise_for_status()

        # Log successful API call
        self.audit.log_api_call(
            platform="upwork",
            endpoint=endpoint,
            method=method,
            status=response.status_code,
            duration=response.elapsed.total_seconds()
        )

        if self.monitoring:
            self.monitoring.record_metric("upwork_api_calls_total", 1)
            self.monitoring.record_metric("upwork_api_latency_seconds", response.elapsed.total_seconds())

        return response

    async def get(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Perform GET request and return JSON."""
        response = await self._make_request("GET", endpoint, params=params)
        return response.json()

    async def post(self, endpoint: str, json: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Perform POST request and return JSON."""
        response = await self._make_request("POST", endpoint, json=json)
        return response.json()

    async def put(self, endpoint: str, json: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Perform PUT request and return JSON."""
        response = await self._make_request("PUT", endpoint, json=json)
        return response.json()

    async def delete(self, endpoint: str) -> Dict[str, Any]:
        """Perform DELETE request and return JSON."""
        response = await self._make_request("DELETE", endpoint)
        return response.json()

    async def list_jobs(self, query: str = "", category: str = "", budget_min: int = 0) -> List[Dict[str, Any]]:
        """Fetch relevant job listings from Upwork."""
        params = {
            "q": query,
            "category": category,
            "budget_gt": budget_min,
            "per_page": self.config.get("jobs_per_page", 50),
        }
        result = await self.get("/profiles/v2/search/jobs.json", params=params)
        return result.get("jobs", [])

    async def get_job_details(self, job_id: str) -> Dict[str, Any]:
        """Retrieve full job details by ID."""
        return await self.get(f"/jobs/v1/{job_id}.json")

    async def submit_proposal(self, job_id: str, proposal_data: Dict[str, Any]) -> Dict[str, Any]:
        """Submit a bid/proposal to a job."""
        return await self.post(f"/contracts/v1/clients/{job_id}/proposals.json", json=proposal_data)

    async def close(self):
        """Gracefully close HTTP client."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
        logger.info("UpworkClient closed.")
