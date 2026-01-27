# AI_FREELANCE_AUTOMATION/services/notification/webhook_service.py
"""
Webhook notification service for external integrations.
Sends structured event notifications to third-party endpoints (e.g., Slack, Discord, custom dashboards).
Supports retry logic, payload signing, and async delivery with full audit logging.
"""

import asyncio
import hashlib
import hmac
import json
import logging
from typing import Any, Dict, Optional, List
from urllib.parse import urlparse

import aiohttp
from aiohttp import ClientTimeout, ClientResponseError

from core.config.unified_config_manager import UnifiedConfigManager
from core.security.advanced_crypto_system import AdvancedCryptoSystem
from core.monitoring.intelligent_monitoring_system import IntelligentMonitoringSystem
from core.dependency.service_locator import ServiceLocator


class WebhookService:
    """
    Asynchronous webhook dispatcher with security, reliability, and observability.

    Features:
    - HMAC-SHA256 payload signing
    - Exponential backoff retries
    - Configurable timeout & concurrency
    - Full audit logging via Security/Audit system
    - Metrics collection for monitoring
    """

    def __init__(
            self,
            config_manager: Optional[UnifiedConfigManager] = None,
            crypto_system: Optional[AdvancedCryptoSystem] = None,
            monitor: Optional[IntelligentMonitoringSystem] = None
    ):
        self.logger = logging.getLogger("WebhookService")
        self.config = config_manager or ServiceLocator.get("config")
        self.crypto = crypto_system or ServiceLocator.get("crypto")
        self.monitor = monitor or ServiceLocator.get("monitoring")

        # Load webhook-specific config
        self.webhook_config = self.config.get_section("notifications").get("webhooks", {})
        self.enabled = self.webhook_config.get("enabled", False)
        self.max_retries = self.webhook_config.get("max_retries", 3)
        self.timeout_seconds = self.webhook_config.get("timeout", 10)
        self.concurrency_limit = self.webhook_config.get("concurrency", 5)

        self._session: Optional[aiohttp.ClientSession] = None
        self._semaphore = asyncio.Semaphore(self.concurrency_limit)

        if not self.enabled:
            self.logger.info("Webhook service is disabled in config.")

    async def __aenter__(self):
        timeout = ClientTimeout(total=self.timeout_seconds)
        self._session = aiohttp.ClientSession(timeout=timeout)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._session:
            await self._session.close()

    def _sign_payload(self, payload: str, secret: str) -> str:
        """Generate HMAC-SHA256 signature for payload integrity."""
        signature = hmac.new(
            key=secret.encode("utf-8"),
            msg=payload.encode("utf-8"),
            digestmod=hashlib.sha256
        ).hexdigest()
        return f"sha256={signature}"

    async def _send_single_webhook(
            self,
            url: str,
            event: str,
            data: Dict[str, Any],
            secret: Optional[str] = None
    ) -> bool:
        """Send a single webhook with retry logic."""
        if not self.enabled:
            return True  # Treat as success if disabled

        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            self.logger.error(f"Invalid webhook URL: {url}")
            return False

        payload = json.dumps({
            "event": event,
            "timestamp": asyncio.get_event_loop().time(),
            "data": data
        }, ensure_ascii=False, separators=(",", ":"))

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "AI-Freelance-Automation/1.0"
        }

        if secret:
            headers["X-Signature"] = self._sign_payload(payload, secret)

        attempt = 0
        while attempt <= self.max_retries:
            try:
                async with self._semaphore:
                    assert self._session is not None
                    async with self._session.post(url, data=payload, headers=headers) as resp:
                        if resp.status < 400:
                            self.logger.debug(f"✅ Webhook delivered to {url} (event: {event})")
                            self.monitor.record_metric("webhook.success", 1)
                            return True
                        else:
                            self.logger.warning(
                                f"⚠️ Webhook failed (status {resp.status}) to {url}: {await resp.text()}"
                            )
            except (ClientResponseError, asyncio.TimeoutError, aiohttp.ClientError) as e:
                self.logger.warning(f"⚠️ Webhook attempt {attempt + 1} failed for {url}: {e}")

            attempt += 1
            if attempt <= self.max_retries:
                backoff = (2 ** attempt) + 1  # exponential backoff
                await asyncio.sleep(backoff)

        self.logger.error(f"❌ Webhook permanently failed after {self.max_retries + 1} attempts: {url}")
        self.monitor.record_metric("webhook.failure", 1)
        return False

    async def notify(
            self,
            event: str,
            data: Dict[str, Any],
            targets: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, bool]:
        """
        Send webhook notification to one or more configured endpoints.

        Args:
            event (str): Event type (e.g., 'job.completed', 'payment.received')
            data (dict): Event payload
            targets (list, optional): List of {'url': str, 'secret': str?}
                                      If None, uses global config from notifications.webhooks.targets

        Returns:
            dict: {url: success_bool}
        """
        if not self.enabled:
            return {}

        if targets is None:
            targets = self.webhook_config.get("targets", [])

        if not targets:
            self.logger.debug("No webhook targets configured.")
            return {}

        tasks = [
            self._send_single_webhook(
                url=target["url"],
                event=event,
                data=data,
                secret=target.get("secret")
            )
            for target in targets
            if "url" in target
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Handle exceptions as failures
        outcome = {}
        for i, result in enumerate(results):
            url = targets[i]["url"]
            if isinstance(result, Exception):
                self.logger.error(f"💥 Webhook task crashed for {url}: {result}")
                outcome[url] = False
            else:
                outcome[url] = result

        return outcome


# Standalone helper for easy integration
async def send_webhook_notification(event: str, data: Dict[str, Any]) -> None:
    """Convenience function for sending webhooks without manual setup."""
    async with WebhookService() as service:
        await service.notify(event, data)