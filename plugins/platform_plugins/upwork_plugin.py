# AI_FREELANCE_AUTOMATION/plugins/platform_plugins/upwork_plugin.py
"""
Upwork Platform Plugin — integrates with Upwork API to enable autonomous job bidding,
client communication, contract management, and payment handling.

This plugin is designed to be:
- Hot-swappable (can be loaded/unloaded at runtime)
- Isolated (runs in its own context with limited side effects)
- Secure (uses encrypted credentials, rate-limited, audited)
- Autonomous (requires zero human intervention)

Complies with:
- Upwork API v2 (OAuth 2.0 + REST)
- PCI DSS (for payment-related operations)
- GDPR (client data handling)
"""

import asyncio
import logging
from typing import Dict, Any, Optional, List, AsyncGenerator
from datetime import datetime, timedelta

from plugins.base_plugin import BasePlatformPlugin
from core.config.unified_config_manager import UnifiedConfigManager
from core.security.advanced_crypto_system import AdvancedCryptoSystem
from core.monitoring.intelligent_monitoring_system import IntelligentMonitoringSystem
from core.dependency.service_locator import ServiceLocator
from platforms.upwork.client import UpworkAPIClient
from platforms.upwork.scraper import UpworkJobScraper
from platforms.upwork.api_wrapper import UpworkAPIWrapper

logger = logging.getLogger("UpworkPlugin")


class UpworkPlugin(BasePlatformPlugin):
    """
    Autonomous plugin for Upwork platform integration.
    Implements full freelance lifecycle: discovery → bid → delivery → payment.
    """

    PLATFORM_NAME = "upwork"
    REQUIRED_CONFIG_KEYS = ["api_key", "api_secret", "access_token", "refresh_token", "user_id"]

    def __init__(
        self,
        config_manager: UnifiedConfigManager,
        crypto_system: AdvancedCryptoSystem,
        monitoring_system: Optional[IntelligentMonitoringSystem] = None,
        service_locator: Optional[ServiceLocator] = None,
    ):
        super().__init__(name=self.PLATFORM_NAME)
        self.config_manager = config_manager
        self.crypto = crypto_system
        self.monitoring = monitoring_system or IntelligentMonitoringSystem(self.config_manager)
        self.service_locator = service_locator

        # Internal state
        self._initialized = False
        self._client: Optional[UpworkAPIClient] = None
        self._scraper: Optional[UpworkJobScraper] = None
        self._api: Optional[UpworkAPIWrapper] = None
        self._last_refresh = datetime.min

        logger.info("Intialized UpworkPlugin (not yet connected)")

    async def initialize(self) -> bool:
        """Initialize plugin with secure credentials and validate connectivity."""
        if self._initialized:
            return True

        try:
            # Load and decrypt platform-specific config
            raw_config = self.config_manager.get_platform_config(self.PLATFORM_NAME)
            if not all(key in raw_config for key in self.REQUIRED_CONFIG_KEYS):
                raise ValueError(f"Missing required keys in {self.PLATFORM_NAME} config")

            # Decrypt sensitive fields
            decrypted_config = {
                "api_key": self.crypto.decrypt(raw_config["api_key"]),
                "api_secret": self.crypto.decrypt(raw_config["api_secret"]),
                "access_token": self.crypto.decrypt(raw_config["access_token"]),
                "refresh_token": self.crypto.decrypt(raw_config["refresh_token"]),
                "user_id": raw_config["user_id"],
            }

            # Initialize components
            self._client = UpworkAPIClient(**decrypted_config)
            self._scraper = UpworkJobScraper(client=self._client)
            self._api = UpworkAPIWrapper(client=self._client)

            # Test connectivity
            await self._client.ping()
            self._initialized = True
            self._last_refresh = datetime.utcnow()

            logger.info("✅ UpworkPlugin successfully initialized and authenticated")
            self.monitoring.log_metric("plugin.upwork.initialized", 1)
            return True

        except Exception as e:
            logger.error(f"❌ Failed to initialize UpworkPlugin: {e}", exc_info=True)
            self.monitoring.log_anomaly("plugin.upwork.init_failure", str(e))
            return False

    async def fetch_jobs(self, filters: Optional[Dict[str, Any]] = None) -> AsyncGenerator[Dict, None]:
        """
        Fetch relevant jobs from Upwork with AI-powered filtering.
        Yields one job at a time to support streaming processing.
        """
        if not self._initialized:
            await self.initialize()

        if not self._scraper:
            raise RuntimeError("UpworkPlugin not initialized")

        try:
            async for job in self._scraper.scrape_jobs(filters=filters):
                # Enrich with metadata
                job["_platform"] = self.PLATFORM_NAME
                job["_fetched_at"] = datetime.utcnow().isoformat()
                yield job

            self.monitoring.log_metric("plugin.upwork.jobs_fetched", 1)
        except Exception as e:
            logger.error(f"Error fetching jobs from Upwork: {e}", exc_info=True)
            self.monitoring.log_anomaly("plugin.upwork.job_fetch_error", str(e))
            raise

    async def submit_bid(self, job_id: str, proposal: str, price: float, delivery_time_days: int) -> bool:
        """Submit a bid on a specific job."""
        if not self._api:
            raise RuntimeError("UpworkPlugin not initialized")

        try:
            success = await self._api.submit_proposal(
                job_id=job_id,
                cover_letter=proposal,
                amount=price,
                duration=delivery_time_days,
            )
            if success:
                logger.info(f"✅ Bid submitted for job {job_id} on Upwork")
                self.monitoring.log_metric("plugin.upwork.bids_submitted", 1)
            else:
                logger.warning(f"⚠️ Bid submission failed for job {job_id}")
            return success
        except Exception as e:
            logger.error(f"Error submitting bid on Upwork: {e}", exc_info=True)
            self.monitoring.log_anomaly("plugin.upwork.bid_error", str(e))
            return False

    async def send_message(self, recipient_id: str, message: str) -> bool:
        """Send a message to a client or employer."""
        if not self._api:
            raise RuntimeError("UpworkPlugin not initialized")

        try:
            success = await self._api.send_message(recipient_id=recipient_id, text=message)
            if success:
                logger.debug(f"Message sent to {recipient_id} on Upwork")
                self.monitoring.log_metric("plugin.upwork.messages_sent", 1)
            return success
        except Exception as e:
            logger.error(f"Error sending message on Upwork: {e}", exc_info=True)
            self.monitoring.log_anomaly("plugin.upwork.message_error", str(e))
            return False

    async def get_conversation(self, thread_id: str) -> List[Dict]:
        """Retrieve full conversation history."""
        if not self._api:
            raise RuntimeError("UpworkPlugin not initialized")
        try:
            return await self._api.get_messages(thread_id)
        except Exception as e:
            logger.error(f"Error fetching conversation {thread_id}: {e}", exc_info=True)
            return []

    async def mark_job_complete(self, contract_id: str, deliverables: List[str]) -> bool:
        """Mark work as complete and attach deliverables."""
        if not self._api:
            raise RuntimeError("UpworkPlugin not initialized")
        try:
            return await self._api.submit_milestone(contract_id, deliverables)
        except Exception as e:
            logger.error(f"Error completing job {contract_id}: {e}", exc_info=True)
            return False

    async def refresh_credentials(self) -> bool:
        """Refresh OAuth tokens if near expiry."""
        if not self._client:
            return False

        now = datetime.utcnow()
        if (now - self._last_refresh) < timedelta(hours=1):
            return True  # Already refreshed recently

        try:
            new_tokens = await self._client.refresh_access_token()
            if new_tokens:
                # Re-encrypt and update config
                updated_config = {
                    "api_key": self.config_manager.get_platform_config(self.PLATFORM_NAME)["api_key"],
                    "api_secret": self.config_manager.get_platform_config(self.PLATFORM_NAME)["api_secret"],
                    "access_token": self.crypto.encrypt(new_tokens["access_token"]),
                    "refresh_token": self.crypto.encrypt(new_tokens["refresh_token"]),
                    "user_id": self.config_manager.get_platform_config(self.PLATFORM_NAME)["user_id"],
                }
                self.config_manager.update_platform_config(self.PLATFORM_NAME, updated_config)
                self._last_refresh = now
                logger.info("🔄 Upwork access token refreshed")
                return True
        except Exception as e:
            logger.error(f"Failed to refresh Upwork tokens: {e}", exc_info=True)
            return False
        return False

    async def health_check(self) -> Dict[str, Any]:
        """Return plugin health status for monitoring system."""
        return {
            "name": self.PLATFORM_NAME,
            "initialized": self._initialized,
            "last_refresh": self._last_refresh.isoformat(),
            "active_client": self._client is not None,
            "timestamp": datetime.utcnow().isoformat(),
        }

    async def shutdown(self) -> None:
        """Gracefully shut down plugin resources."""
        if self._client:
            await self._client.close_session()
        self._initialized = False
        logger.info("🔌 UpworkPlugin shut down gracefully")
