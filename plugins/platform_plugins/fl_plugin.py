# plugins/platform_plugins/fl_plugin.py
"""
FL.ru Platform Plugin for AI Freelance Automation System.
Provides full integration with freelance.ru (FL.ru) via scraping and official API (if available).
Implements autonomous job discovery, bidding, messaging, and delivery.
"""

import asyncio
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime

from plugins.base_plugin import BasePlatformPlugin
from core.config.config import UnifiedConfigManager
from core.security.advanced_crypto_system import AdvancedCryptoSystem
from platforms.freelance_ru.client import FreelanceRuClient
from platforms.freelance_ru.scraper import FreelanceRuScraper
from platforms.freelance_ru.api_wrapper import FreelanceRuAPIWrapper
from services.ai_services.transcription_service import TranscriptionService
from services.ai_services.translation_service import TranslationService
from services.ai_services.copywriting_service import CopywritingService
from core.communication.empathetic_communicator import EmpatheticCommunicator
from core.automation.job_analyzer import JobAnalyzer
from core.automation.decision_engine import DecisionEngine

logger = logging.getLogger(__name__)


class FLPlugin(BasePlatformPlugin):
    """
    Freelance.ru (FL.ru) integration plugin.
    Fully autonomous: finds jobs, bids, communicates, delivers, and collects payments.
    """

    PLATFORM_NAME = "freelance_ru"
    SUPPORTED_CATEGORIES = ["transcription", "translation", "copywriting", "editing", "proofreading"]

    def __init__(
        self,
        config_manager: UnifiedConfigManager,
        crypto_system: AdvancedCryptoSystem,
        communicator: EmpatheticCommunicator,
        decision_engine: DecisionEngine,
        job_analyzer: JobAnalyzer,
        transcription_service: Optional[TranscriptionService] = None,
        translation_service: Optional[TranslationService] = None,
        copywriting_service: Optional[CopywritingService] = None,
    ):
        super().__init__(platform_name=self.PLATFORM_NAME)
        self.config_manager = config_manager
        self.crypto_system = crypto_system
        self.communicator = communicator
        self.decision_engine = decision_engine
        self.job_analyzer = job_analyzer

        # Optional AI services (only loaded if needed)
        self.transcription_service = transcription_service
        self.translation_service = translation_service
        self.copywriting_service = copywriting_service

        # Initialize platform-specific clients
        fl_config = self.config_manager.get_platform_config("freelance_ru")
        self.client = FreelanceRuClient(config=fl_config, crypto=crypto_system)
        self.scraper = FreelanceRuScraper(config=fl_config)
        self.api = FreelanceRuAPIWrapper(client=self.client)

        self.is_active = False
        self.last_scan = None
        logger.info("✅ FL.ru plugin initialized.")

    async def activate(self) -> bool:
        """Activate the plugin and authenticate on FL.ru."""
        try:
            await self.client.login()
            self.is_active = True
            logger.info("🔓 FL.ru plugin activated and authenticated.")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to activate FL.ru plugin: {e}", exc_info=True)
            return False

    async def deactivate(self) -> None:
        """Deactivate and clean up resources."""
        self.is_active = False
        await self.client.logout()
        logger.info("🔒 FL.ru plugin deactivated.")

    async def scan_for_jobs(self) -> List[Dict[str, Any]]:
        """
        Scan FL.ru for new relevant jobs.
        Returns list of normalized job dictionaries.
        """
        if not self.is_active:
            logger.warning("⚠️ FL plugin not active. Skipping job scan.")
            return []

        try:
            raw_jobs = await self.scraper.fetch_jobs()
            normalized_jobs = []
            for job in raw_jobs:
                normalized = self._normalize_job(job)
                if self._is_relevant(normalized):
                    normalized_jobs.append(normalized)

            self.last_scan = datetime.utcnow()
            logger.info(f"🔍 Found {len(normalized_jobs)} relevant jobs on FL.ru.")
            return normalized_jobs
        except Exception as e:
            logger.error(f"💥 Error scanning FL.ru jobs: {e}", exc_info=True)
            return []

    def _normalize_job(self, raw_job: Dict[str, Any]) -> Dict[str, Any]:
        """Convert raw FL.ru job into unified internal format."""
        return {
            "platform": self.PLATFORM_NAME,
            "job_id": str(raw_job.get("id")),
            "title": raw_job.get("title", ""),
            "description": raw_job.get("description", ""),
            "budget": raw_job.get("budget", 0),
            "currency": raw_job.get("currency", "RUB"),
            "deadline": raw_job.get("deadline"),
            "category": self._map_category(raw_job.get("category", "")),
            "skills": raw_job.get("skills", []),
            "client_id": raw_job.get("client_id"),
            "url": raw_job.get("url", ""),
            "posted_at": raw_job.get("posted_at"),
            "raw_data": raw_job,
        }

    def _map_category(self, fl_category: str) -> str:
        """Map FL.ru categories to internal service types."""
        mapping = {
            "Транскрибация": "transcription",
            "Переводы": "translation",
            "Копирайтинг": "copywriting",
            "Рерайтинг": "copywriting",
            "Редактирование": "editing",
            "Корректура": "proofreading",
        }
        return mapping.get(fl_category, "other")

    def _is_relevant(self, job: Dict[str, Any]) -> bool:
        """Check if job matches supported categories and minimum criteria."""
        if job["category"] not in self.SUPPORTED_CATEGORIES:
            return False
        min_budget = self.config_manager.get("automation.min_budget_rub", 300)
        return job.get("budget", 0) >= min_budget

    async def evaluate_and_bid(self, job: Dict[str, Any]) -> bool:
        """Decide whether to bid and submit a tailored proposal."""
        try:
            decision = await self.decision_engine.evaluate_job(job)
            if not decision["should_bid"]:
                logger.debug(f"⏭️ Skipping job {job['job_id']}: {decision['reason']}")
                return False

            # Generate AI-powered bid
            bid_text = await self._generate_bid(job, decision["suggested_price"])
            success = await self.api.submit_bid(
                job_id=job["job_id"],
                price=decision["suggested_price"],
                message=bid_text,
                delivery_time_days=decision["suggested_days"]
            )

            if success:
                logger.info(f"📨 Submitted bid for job {job['job_id']} at {decision['suggested_price']} RUB")
                return True
            else:
                logger.warning(f"⚠️ Bid submission failed for job {job['job_id']}")
                return False

        except Exception as e:
            logger.error(f"💥 Error during bidding for job {job['job_id']}: {e}", exc_info=True)
            return False

    async def _generate_bid(self, job: Dict[str, Any], price: float) -> str:
        """Generate human-like, personalized bid using AI."""
        prompt = f"""
You are a professional freelancer on FL.ru. Write a short, confident, and friendly bid for this job:

Title: {job['title']}
Description: {job['description']}
Budget: {job['budget']} RUB
Category: {job['category']}

Your bid should:
- Show understanding of the task
- Mention relevant experience
- Propose price: {price} RUB
- Suggest delivery in X days
- Be polite and professional
- Avoid generic phrases
"""
        if self.copywriting_service:
            return await self.copywriting_service.generate_text(prompt, max_tokens=250, temperature=0.7)
        else:
            # Fallback: simple template
            return (
                f"Здравствуйте! Готов(а) выполнить вашу задачу качественно и в срок. "
                f"Цена: {price} руб. Срок: 2 дня. Опыт в подобных проектах — более 3 лет."
            )

    async def handle_client_message(self, conversation_id: str, message: Dict[str, Any]) -> None:
        """Process incoming client messages and auto-reply."""
        try:
            response = await self.communicator.generate_response(
                platform=self.PLATFORM_NAME,
                conversation_id=conversation_id,
                message=message,
                context={"job_id": message.get("job_id")}
            )
            await self.api.send_message(conversation_id, response)
            logger.debug(f"💬 Replied to client in conversation {conversation_id}")
        except Exception as e:
            logger.error(f"❌ Failed to handle message in {conversation_id}: {e}", exc_info=True)

    async def deliver_work(self, job_id: str, deliverables: Dict[str, Any]) -> bool:
        """Submit completed work to client on FL.ru."""
        try:
            result = await self.api.submit_delivery(job_id, deliverables)
            if result:
                logger.info(f"📤 Delivered work for job {job_id}")
                return True
            else:
                logger.warning(f"⚠️ Delivery failed for job {job_id}")
                return False
        except Exception as e:
            logger.error(f"💥 Delivery error for job {job_id}: {e}", exc_info=True)
            return False

    def get_status(self) -> Dict[str, Any]:
        """Return plugin health and operational status."""
        return {
            "platform": self.PLATFORM_NAME,
            "active": self.is_active,
            "last_scan": self.last_scan.isoformat() if self.last_scan else None,
            "supported_categories": self.SUPPORTED_CATEGORIES,
        }