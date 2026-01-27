# AI_FREELANCE_AUTOMATION/plugins/platform_plugins/freelance_ru_plugin.py
"""
Freelance.ru Platform Plugin
Integrates with freelance.ru via official API and intelligent scraping.
Fully autonomous: job discovery, bidding, communication, delivery.
Complies with platform ToS via rate limiting and human-like behavior simulation.
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
from core.monitoring.intelligent_monitoring_system import MetricType
from platforms.freelance_ru.client import FreelanceRuAPIClient
from platforms.freelance_ru.scraper import FreelanceRuScraper
from services.ai_services.transcription_service import TranscriptionService
from services.ai_services.translation_service import TranslationService
from services.ai_services.copywriting_service import CopywritingService
from services.notification.email_service import EmailService

logger = logging.getLogger("FreelanceRuPlugin")


class FreelanceRuPlugin(BasePlatformPlugin):
    """
    Autonomous agent for freelance.ru platform.
    Implements full lifecycle: discovery → bid → communication → delivery → payment.
    """

    PLATFORM_NAME = "freelance_ru"
    SUPPORTED_CATEGORIES = ["transcription", "translation", "copywriting", "editing"]

    def __init__(
        self,
        config_manager: UnifiedConfigManager,
        crypto_system: AdvancedCryptoSystem,
        service_locator: ServiceLocator,
    ):
        super().__init__(self.PLATFORM_NAME)
        self.config_manager = config_manager
        self.crypto_system = crypto_system
        self.service_locator = service_locator

        # Load platform-specific config
        self.platform_config = self.config_manager.get_platform_config(self.PLATFORM_NAME)
        self.enabled = self.platform_config.get("enabled", False)
        self.rate_limit_delay = self.platform_config.get("rate_limit_delay_sec", 5)
        self.max_concurrent_jobs = self.platform_config.get("max_concurrent_jobs", 10)

        # Initialize internal services
        self.api_client = FreelanceRuAPIClient(
            api_key=self._decrypt_api_key(),
            user_agent=self.platform_config.get("user_agent"),
        )
        self.scraper = FreelanceRuScraper(
            proxy_list=self.platform_config.get("proxies", []),
            delay_range=(2, 6),
        )

        # AI services (lazy-loaded via service locator)
        self.transcription_svc: Optional[TranscriptionService] = None
        self.translation_svc: Optional[TranslationService] = None
        self.copywriting_svc: Optional[CopywritingService] = None

        # Monitoring
        self.monitor = self.service_locator.get("monitoring_system")
        self.email_notifier = self.service_locator.get("email_service")

        self.active_jobs: Dict[str, Dict[str, Any]] = {}
        self.last_scrape_time: Optional[datetime] = None

        logger.info(f"✅ Freelance.ru plugin initialized (enabled={self.enabled})")

    def _decrypt_api_key(self) -> str:
        """Decrypt stored API key using system-wide crypto."""
        encrypted_key = self.platform_config.get("encrypted_api_key")
        if not encrypted_key:
            raise ValueError("Missing encrypted_api_key in freelance_ru config")
        return self.crypto_system.decrypt(encrypted_key)

    async def start(self) -> bool:
        """Start autonomous operation on freelance.ru."""
        if not self.enabled:
            logger.warning("Freelance.ru plugin is disabled in config.")
            return False

        try:
            await self.api_client.authenticate()
            logger.info("🔑 Authenticated successfully on freelance.ru")
            self.monitor.increment_metric(MetricType.PLATFORM_CONNECTIONS, tags={"platform": "freelance_ru"})
            return True
        except Exception as e:
            logger.error(f"❌ Failed to authenticate on freelance.ru: {e}", exc_info=True)
            await self._handle_error(e, "authentication")
            return False

    async def discover_jobs(self) -> List[Dict[str, Any]]:
        """Discover relevant jobs using both API and scraper."""
        if not self.enabled:
            return []

        try:
            logger.debug("🔍 Starting job discovery on freelance.ru...")

            # Use API first (preferred)
            api_jobs = await self.api_client.fetch_new_jobs(
                categories=self.SUPPORTED_CATEGORIES,
                min_budget=self.platform_config.get("min_budget_rub", 500),
                max_age_hours=24,
            )

            # Fallback to scraper if API fails or returns empty
            if not api_jobs:
                logger.warning("API returned no jobs; falling back to scraper")
                scraper_jobs = await self.scraper.scrape_jobs(
                    query_terms=self.SUPPORTED_CATEGORIES,
                    pages=3,
                )
                jobs = scraper_jobs
            else:
                jobs = api_jobs

            # Filter & enrich
            filtered_jobs = []
            for job in jobs:
                if self._is_relevant(job):
                    enriched = await self._enrich_job_data(job)
                    filtered_jobs.append(enriched)

            self.last_scrape_time = datetime.utcnow()
            self.monitor.record_metric(MetricType.JOBS_DISCOVERED, len(filtered_jobs), {"platform": "freelance_ru"})
            logger.info(f"✅ Discovered {len(filtered_jobs)} relevant jobs on freelance.ru")
            return filtered_jobs

        except Exception as e:
            logger.error(f"💥 Error during job discovery: {e}", exc_info=True)
            await self._handle_error(e, "job_discovery")
            return []

    def _is_relevant(self, job: Dict[str, Any]) -> bool:
        """Determine if job matches our capabilities and risk profile."""
        title = job.get("title", "").lower()
        desc = job.get("description", "").lower()
        budget = job.get("budget", 0)
        deadline = job.get("deadline")

        # Budget check
        if budget < self.platform_config.get("min_budget_rub", 500):
            return False

        # Deadline sanity
        if deadline:
            deadline_dt = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
            if deadline_dt < datetime.utcnow() + timedelta(hours=2):
                return False  # Too urgent

        # Keyword matching
        keywords = set(title.split() + desc.split())
        if any(kw in keywords for kw in ["транскрибация", "перевод", "копирайтинг", "редактирование"]):
            return True

        return False

    async def _enrich_job_data(self, job: Dict[str, Any]) -> Dict[str, Any]:
        """Add AI-analyzed metadata to job."""
        job["platform"] = self.PLATFORM_NAME
        job["discovered_at"] = datetime.utcnow().isoformat()
        job["estimated_effort_hours"] = await self._estimate_effort(job)
        job["risk_score"] = await self._calculate_risk(job)
        return job

    async def _estimate_effort(self, job: Dict[str, Any]) -> float:
        """Estimate effort using AI (placeholder logic)."""
        desc_len = len(job.get("description", ""))
        if "аудио" in job.get("description", "") or "видео" in job.get("description", ""):
            return max(1.0, desc_len / 500.0)  # transcription
        elif "перевод" in job.get("title", ""):
            return max(0.5, desc_len / 800.0)
        else:
            return max(0.3, desc_len / 1000.0)  # copywriting/editing

    async def _calculate_risk(self, job: Dict[str, Any]) -> float:
        """Calculate risk score [0.0–1.0]."""
        risk = 0.2  # base
        if job.get("client_rating", 5.0) < 4.0:
            risk += 0.3
        if job.get("budget", 0) < 1000:
            risk += 0.2
        if "срочн" in job.get("title", "") or "срочно" in job.get("description", ""):
            risk += 0.25
        return min(1.0, risk)

    async def place_bid(self, job: Dict[str, Any], proposal: str, price: float) -> bool:
        """Place a bid on a job."""
        try:
            result = await self.api_client.submit_proposal(
                job_id=job["id"],
                message=proposal,
                price_rub=price,
                delivery_hours=int(job.get("estimated_effort_hours", 24) * 1.5),
            )
            if result:
                self.active_jobs[job["id"]] = {
                    "job": job,
                    "status": "bid_placed",
                    "bid_time": datetime.utcnow(),
                    "price": price,
                }
                self.monitor.increment_metric(MetricType.BIDS_PLACED, tags={"platform": "freelance_ru"})
                logger.info(f"✅ Bid placed on job {job['id']} for {price} RUB")
                return True
            else:
                logger.warning(f"⚠️ Bid failed silently for job {job['id']}")
                return False
        except Exception as e:
            logger.error(f"❌ Bid placement failed for job {job['id']}: {e}", exc_info=True)
            await self._handle_error(e, "bid_placement")
            return False

    async def handle_message(self, job_id: str, message: Dict[str, Any]) -> Optional[str]:
        """Handle incoming client message and generate AI response."""
        try:
            # Lazy-load AI services
            if self.copywriting_svc is None:
                self.copywriting_svc = self.service_locator.get("copywriting_service")

            context = self.active_jobs.get(job_id, {})
            response = await self.copywriting_svc.generate_client_response(
                message=message["text"],
                context=context,
                tone="professional",
                language="ru",
            )

            # Log interaction
            self.monitor.increment_metric(MetricType.MESSAGES_HANDLED, tags={"platform": "freelance_ru"})
            return response

        except Exception as e:
            logger.error(f"❌ Message handling error for job {job_id}: {e}", exc_info=True)
            await self._handle_error(e, "message_handling")
            return "Спасибо за ваше сообщение! Я отвечу в ближайшее время."

    async def deliver_work(self, job_id: str, deliverables: Dict[str, Any]) -> bool:
        """Deliver completed work to client."""
        try:
            job_record = self.active_jobs.get(job_id)
            if not job_record:
                logger.error(f"Job {job_id} not found in active jobs")
                return False

            success = await self.api_client.upload_delivery(
                job_id=job_id,
                files=deliverables.get("files", []),
                message=deliverables.get("message", "Работа выполнена согласно ТЗ."),
            )

            if success:
                job_record["status"] = "delivered"
                job_record["delivered_at"] = datetime.utcnow()
                self.monitor.increment_metric(MetricType.WORK_DELIVERED, tags={"platform": "freelance_ru"})
                logger.info(f"✅ Work delivered for job {job_id}")
                return True
            else:
                logger.warning(f"⚠️ Delivery failed for job {job_id}")
                return False

        except Exception as e:
            logger.error(f"❌ Delivery error for job {job_id}: {e}", exc_info=True)
            await self._handle_error(e, "work_delivery")
            return False

    async def _handle_error(self, error: Exception, context: str):
        """Centralized error handling with recovery and alerting."""
        error_id = f"freelance_ru_{context}_{int(datetime.utcnow().timestamp())}"
        logger.critical(f"🚨 Critical error [{error_id}]: {str(error)}")

        # Log to audit
        audit_logger = self.service_locator.get("audit_logger")
        if audit_logger:
            audit_logger.log_security_event(
                event_type="platform_error",
                details={
                    "platform": self.PLATFORM_NAME,
                    "context": context,
                    "error": str(error),
                    "error_id": error_id,
                },
            )

        # Notify admin
        if self.email_notifier:
            await self.email_notifier.send_alert(
                subject=f"[CRITICAL] Freelance.ru Plugin Error ({context})",
                body=f"Error ID: {error_id}\nContext: {context}\nError: {str(error)}\nTime: {datetime.utcnow()}",
            )

        # Trigger recovery if needed
        recovery = self.service_locator.get("emergency_recovery")
        if recovery:
            await recovery.trigger_recovery(component_name="freelance_ru_plugin", error=error)

    async def stop(self):
        """Gracefully stop plugin."""
        logger.info("🛑 Stopping Freelance.ru plugin...")
        await self.api_client.close()
        await self.scraper.close()
        self.active_jobs.clear()

    def get_status(self) -> Dict[str, Any]:
        """Return plugin health status."""
        return {
            "name": self.PLATFORM_NAME,
            "enabled": self.enabled,
            "active_jobs_count": len(self.active_jobs),
            "last_scrape": self.last_scrape_time.isoformat() if self.last_scrape_time else None,
            "healthy": self.api_client.is_healthy() if hasattr(self.api_client, 'is_healthy') else True,
        }