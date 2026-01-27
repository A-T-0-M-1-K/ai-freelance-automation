# plugins/platform_plugins/kwork_plugin.py
"""
Kwork Platform Plugin for AI Freelance Automation System.
Provides full integration with kwork.ru API and scraping capabilities.
Implements autonomous job discovery, bidding, communication, and delivery.
"""

import asyncio
import json
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta

from plugins.base_plugin import BasePlatformPlugin
from core.config.unified_config_manager import UnifiedConfigManager
from core.security.advanced_crypto_system import AdvancedCryptoSystem
from core.dependency.service_locator import ServiceLocator
from platforms.kwork.client import KworkClient
from platforms.kwork.scraper import KworkScraper
from platforms.kwork.api_wrapper import KworkAPIWrapper

logger = logging.getLogger("KworkPlugin")


class KworkPlugin(BasePlatformPlugin):
    """
    Autonomous plugin for kwork.ru platform.
    Supports both official API (where available) and intelligent scraping.
    Fully compliant with system-wide security, monitoring, and error recovery.
    """

    PLATFORM_NAME = "kwork"
    SUPPORTED_CATEGORIES = ["transcription", "translation", "copywriting", "editing"]
    MIN_BID_DELAY = 10  # seconds between bids to avoid rate limiting

    def __init__(
        self,
        config_manager: UnifiedConfigManager,
        crypto_system: AdvancedCryptoSystem,
        service_locator: ServiceLocator,
    ):
        super().__init__(platform_name=self.PLATFORM_NAME)
        self.config_manager = config_manager
        self.crypto_system = crypto_system
        self.service_locator = service_locator

        # Load platform-specific config
        self.platform_config = self.config_manager.get_platform_config(self.PLATFORM_NAME)
        self.enabled = self.platform_config.get("enabled", False)
        self.account_id = self.platform_config.get("account_id")
        self.auth_token = None  # Will be decrypted on login

        # Initialize components
        self.client: Optional[KworkClient] = None
        self.scraper: Optional[KworkScraper] = None
        self.api: Optional[KworkAPIWrapper] = None
        self._last_bid_time = datetime.min

        # Performance & safety
        self.max_concurrent_jobs = self.platform_config.get("max_concurrent_jobs", 5)
        self.bid_success_rate_threshold = self.platform_config.get("bid_success_rate_threshold", 0.15)

        logger.info(f"Intialized KworkPlugin (enabled={self.enabled})")

    async def initialize(self) -> bool:
        """Initialize plugin components and authenticate."""
        if not self.enabled:
            logger.warning("KworkPlugin is disabled in config.")
            return False

        try:
            # Decrypt auth token
            encrypted_token = self.platform_config.get("auth_token_encrypted")
            if not encrypted_token:
                raise ValueError("Missing auth_token_encrypted in kwork config")
            self.auth_token = self.crypto_system.decrypt(encrypted_token)

            # Initialize subcomponents
            self.client = KworkClient(auth_token=self.auth_token, config=self.platform_config)
            self.scraper = KworkScraper(config=self.platform_config)
            self.api = KworkAPIWrapper(client=self.client)

            # Test connectivity
            profile = await self.client.get_profile()
            if not profile or "user_id" not in profile:
                raise ConnectionError("Failed to fetch Kwork profile")

            logger.info(f"✅ KworkPlugin authenticated as user_id={profile['user_id']}")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to initialize KworkPlugin: {e}", exc_info=True)
            await self._trigger_recovery(e)
            return False

    async def discover_jobs(self, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Discover relevant jobs from Kwork using scraper + API.
        Returns list of normalized job dicts.
        """
        if not self.enabled or not self.scraper:
            return []

        try:
            # Merge user filters with platform defaults
            effective_filters = {
                "categories": self.SUPPORTED_CATEGORIES,
                "min_budget": self.platform_config.get("min_budget", 300),
                "max_delivery_hours": self.platform_config.get("max_delivery_hours", 72),
                **(filters or {})
            }

            logger.debug(f"🔍 Discovering Kwork jobs with filters: {effective_filters}")

            # Use scraper for public job listings (Kwork has limited API)
            raw_jobs = await self.scraper.scrape_jobs(filters=effective_filters)

            # Normalize to system-wide format
            normalized_jobs = []
            for job in raw_jobs:
                normalized = self._normalize_job(job)
                if normalized:
                    normalized_jobs.append(normalized)

            logger.info(f"📥 Discovered {len(normalized_jobs)} relevant jobs on Kwork")
            return normalized_jobs

        except Exception as e:
            logger.error(f"💥 Error during Kwork job discovery: {e}", exc_info=True)
            await self._trigger_recovery(e)
            return []

    async def place_bid(self, job_id: str, proposal: Dict[str, Any]) -> bool:
        """
        Place a bid on a Kwork gig.
        Note: Kwork uses "gigs" instead of traditional bids — we simulate via custom offer.
        """
        if not self.enabled or not self.api:
            return False

        # Rate limiting
        now = datetime.now()
        if (now - self._last_bid_time).total_seconds() < self.MIN_BID_DELAY:
            await asyncio.sleep(self.MIN_BID_DELAY)

        try:
            # Format proposal for Kwork
            title = proposal.get("title", "Professional service")
            description = proposal.get("description", "")
            price = proposal.get("price", 500)
            delivery_time_hours = proposal.get("delivery_time_hours", 24)

            success = await self.api.send_custom_offer(
                gig_id=job_id,
                title=title,
                description=description,
                price_rub=price,
                delivery_hours=delivery_time_hours
            )

            if success:
                self._last_bid_time = now
                logger.info(f"✅ Placed bid on Kwork gig {job_id} for {price} RUB")
                return True
            else:
                logger.warning(f"⚠️ Bid failed on Kwork gig {job_id}")
                return False

        except Exception as e:
            logger.error(f"💥 Error placing bid on Kwork gig {job_id}: {e}", exc_info=True)
            await self._trigger_recovery(e)
            return False

    async def get_conversation(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Fetch conversation history for a job."""
        if not self.api:
            return None
        try:
            return await self.api.get_conversation(gig_id=job_id)
        except Exception as e:
            logger.warning(f"Could not fetch Kwork conversation for {job_id}: {e}")
            return None

    async def send_message(self, job_id: str, message: str) -> bool:
        """Send message to client on Kwork."""
        if not self.api:
            return False
        try:
            return await self.api.send_message(gig_id=job_id, message=message)
        except Exception as e:
            logger.error(f"Failed to send Kwork message to {job_id}: {e}")
            return False

    async def deliver_work(self, job_id: str, deliverables: Dict[str, Any]) -> bool:
        """Deliver completed work (not typical on Kwork, but simulated via message + file)."""
        message = deliverables.get("message", "Work completed! See attachment.")
        files = deliverables.get("files", [])
        # On Kwork, delivery usually happens via platform tools; we notify via message
        return await self.send_message(job_id, message)

    def _normalize_job(self, raw_job: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Convert Kwork-specific job format to unified system format."""
        try:
            return {
                "platform": self.PLATFORM_NAME,
                "job_id": str(raw_job["gig_id"]),
                "title": raw_job.get("title", ""),
                "description": raw_job.get("description", ""),
                "category": self._map_category(raw_job.get("category")),
                "budget_min": raw_job.get("price", 0),
                "budget_max": raw_job.get("price", 0),  # Kwork gigs are fixed-price
                "currency": "RUB",
                "deadline_hours": raw_job.get("delivery_time", 24),
                "client_rating": raw_job.get("seller_rating", 0),
                "url": f"https://kwork.ru/gigs/{raw_job['gig_id']}",
                "skills": raw_job.get("tags", []),
                "posted_at": raw_job.get("created_at") or datetime.utcnow().isoformat(),
                "metadata": {"raw": raw_job}
            }
        except KeyError as e:
            logger.warning(f"Skipping malformed Kwork job: missing {e}")
            return None

    def _map_category(self, kwork_category: str) -> str:
        """Map Kwork categories to internal types."""
        mapping = {
            "transkriptsiya": "transcription",
            "perevod": "translation",
            "kopirayting": "copywriting",
            "redaktirovanie": "editing",
        }
        return mapping.get(kwork_category.lower(), "other")

    async def _trigger_recovery(self, error: Exception):
        """Delegate error to system-wide recovery mechanism."""
        recovery = self.service_locator.get_service("emergency_recovery")
        if recovery:
            await recovery.handle_component_failure(component_name="kwork_plugin", error=error)

    async def shutdown(self):
        """Graceful shutdown."""
        if self.client:
            await self.client.close_session()
        logger.info("🔌 KworkPlugin shut down gracefully.")

    def get_status(self) -> Dict[str, Any]:
        """Return plugin health status for monitoring."""
        return {
            "platform": self.PLATFORM_NAME,
            "enabled": self.enabled,
            "initialized": self.client is not None,
            "last_bid": self._last_bid_time.isoformat() if self._last_bid_time else None,
            "max_concurrent_jobs": self.max_concurrent_jobs
        }