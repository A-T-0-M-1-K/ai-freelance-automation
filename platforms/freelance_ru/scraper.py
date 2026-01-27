# platforms/freelance_ru/scraper.py
"""
Intelligent job scraper for Freelance.ru platform.
Uses AI-powered filtering to extract relevant orders based on user profile,
budget, skills, and historical success patterns.
"""

import asyncio
import json
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
from urllib.parse import urljoin

import aiohttp
from bs4 import BeautifulSoup

from core.config.unified_config_manager import UnifiedConfigManager
from core.monitoring.intelligent_monitoring_system import IntelligentMonitoringSystem
from core.security.advanced_crypto_system import AdvancedCryptoSystem
from core.ai_management.intelligent_model_manager import IntelligentModelManager
from services.storage.database_service import DatabaseService


class FreelanceRuScraper:
    """
    Scrapes job listings from freelance.ru with intelligent filtering and anti-detection measures.
    Integrates with AI models for relevance scoring and risk assessment.
    """

    PLATFORM_NAME = "freelance_ru"
    BASE_URL = "https://freelance.ru"
    JOBS_ENDPOINT = "/project/search"
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    def __init__(
            self,
            config: UnifiedConfigManager,
            crypto: AdvancedCryptoSystem,
            monitor: IntelligentMonitoringSystem,
            ai_manager: IntelligentModelManager,
            db: DatabaseService,
    ):
        self.config = config
        self.crypto = crypto
        self.monitor = monitor
        self.ai_manager = ai_manager
        self.db = db
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self.session: Optional[aiohttp.ClientSession] = None

        # Load platform-specific settings
        self.platform_config = self.config.get("platforms", {}).get(self.PLATFORM_NAME, {})
        self.enabled = self.platform_config.get("enabled", False)
        self.rate_limit_delay = self.platform_config.get("rate_limit_delay_sec", 2)
        self.max_retries = self.platform_config.get("max_retries", 3)
        self.timeout = aiohttp.ClientTimeout(total=self.platform_config.get("timeout_sec", 30))

    async def __aenter__(self):
        headers = {"User-Agent": self.USER_AGENT}
        cookies = await self._load_authenticated_cookies()
        self.session = aiohttp.ClientSession(
            headers=headers,
            cookies=cookies,
            timeout=self.timeout,
            trust_env=True,
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    async def _load_authenticated_cookies(self) -> Dict[str, str]:
        """Load encrypted session cookies from secure storage."""
        try:
            encrypted_cookies = await self.db.get_platform_credentials(self.PLATFORM_NAME)
            if not encrypted_cookies:
                self.logger.warning("No stored credentials for freelance.ru — scraping anonymously")
                return {}
            decrypted = self.crypto.decrypt_data(encrypted_cookies)
            return json.loads(decrypted)
        except Exception as e:
            self.logger.error(f"Failed to load freelance.ru cookies: {e}")
            return {}

    async def scrape_jobs(self, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Scrape and intelligently filter job listings from freelance.ru.

        Args:
            filters: Optional dict with keys like 'category', 'min_budget', 'skills', etc.

        Returns:
            List of normalized job dictionaries ready for decision engine.
        """
        if not self.enabled:
            self.logger.info("Freelance.ru scraping is disabled in config")
            return []

        self.logger.info("🔍 Starting job scraping on freelance.ru...")
        raw_jobs = await self._fetch_raw_jobs(filters or {})
        enriched_jobs = await self._enrich_and_filter_jobs(raw_jobs)
        self.logger.info(f"✅ Scraped and filtered {len(enriched_jobs)} relevant jobs")
        return enriched_jobs

    async def _fetch_raw_jobs(self, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Fetch raw HTML and parse job listings."""
        all_jobs = []
        page = 1
        max_pages = self.platform_config.get("max_pages_per_run", 5)

        while page <= max_pages:
            try:
                url = self._build_search_url(page, filters)
                self.logger.debug(f"Fetching page {page}: {url}")
                async with self.session.get(url) as response:
                    if response.status == 429:
                        self.logger.warning("Rate limited by freelance.ru — backing off")
                        await asyncio.sleep(self.rate_limit_delay * 5)
                        continue
                    response.raise_for_status()
                    html = await response.text()

                jobs = self._parse_jobs_from_html(html)
                if not jobs:
                    self.logger.debug("No more jobs found — stopping pagination")
                    break

                all_jobs.extend(jobs)
                page += 1
                await asyncio.sleep(self.rate_limit_delay)

            except Exception as e:
                self.logger.error(f"Error fetching page {page}: {e}", exc_info=True)
                await asyncio.sleep(self.rate_limit_delay * 2)
                page += 1  # skip to avoid infinite loop

        return all_jobs

    def _build_search_url(self, page: int, filters: Dict[str, Any]) -> str:
        """Construct search URL with filters."""
        # Example: https://freelance.ru/project/search?page=1&cat=123&price_from=1000
        params = {"page": str(page)}

        if filters.get("category_id"):
            params["cat"] = str(filters["category_id"])
        if filters.get("min_budget"):
            params["price_from"] = str(filters["min_budget"])
        if filters.get("query"):
            params["q"] = filters["query"]

        query = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{self.BASE_URL}{self.JOBS_ENDPOINT}?{query}"

    def _parse_jobs_from_html(self, html: str) -> List[Dict[str, Any]]:
        """Parse job cards from HTML using BeautifulSoup."""
        soup = BeautifulSoup(html, "html.parser")
        job_cards = soup.select("div.project")
        jobs = []

        for card in job_cards:
            try:
                title_elem = card.select_one("h2.title a")
                if not title_elem:
                    continue

                job_id = title_elem.get("href", "").split("/")[-1]
                title = title_elem.get_text(strip=True)
                description = card.select_one("p.text").get_text(strip=True) if card.select_one("p.text") else ""
                price_elem = card.select_one("div.price")
                price = self._extract_price(price_elem.get_text()) if price_elem else None
                deadline_elem = card.select_one("span.term")
                deadline_str = deadline_elem.get_text(strip=True) if deadline_elem else None
                deadline = self._parse_deadline(deadline_str) if deadline_str else None

                job = {
                    "platform": self.PLATFORM_NAME,
                    "job_id": job_id,
                    "title": title,
                    "description": description,
                    "budget": price,
                    "currency": "RUB",
                    "deadline": deadline.isoformat() if deadline else None,
                    "url": urljoin(self.BASE_URL, title_elem["href"]),
                    "scraped_at": datetime.utcnow().isoformat(),
                    "raw_html_snippet": str(card)[:500],  # for debugging
                }
                jobs.append(job)

            except Exception as e:
                self.logger.warning(f"Failed to parse job card: {e}")
                continue

        return jobs

    def _extract_price(self, price_text: str) -> Optional[int]:
        """Extract integer price from text like '1 500 ₽'."""
        import re
        match = re.search(r"[\d\s]+", price_text)
        if match:
            clean = match.group().replace(" ", "")
            return int(clean) if clean.isdigit() else None
        return None

    def _parse_deadline(self, deadline_str: str) -> Optional[datetime]:
        """Parse deadline string like 'до 25 янв' or 'сегодня'."""
        # Simplified — in production, use dateparser or custom logic
        if "сегодня" in deadline_str:
            return datetime.utcnow().replace(hour=23, minute=59, second=59)
        # Add more parsing as needed
        return None

    async def _enrich_and_filter_jobs(self, raw_jobs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Use AI to score relevance and filter out low-quality or risky jobs."""
        if not raw_jobs:
            return []

        # Batch inference for efficiency
        try:
            model = await self.ai_manager.get_model("job_relevance_classifier")
            enriched = []

            for job in raw_jobs:
                # Prepare input for AI model
                input_text = f"{job['title']} | {job['description']}"
                relevance_score = await model.predict(input_text)
                job["ai_relevance_score"] = float(relevance_score)

                # Apply threshold (configurable)
                threshold = self.config.get("automation", {}).get("min_relevance_threshold", 0.7)
                if job["ai_relevance_score"] >= threshold:
                    enriched.append(job)

            self.logger.info(f"AI filtered {len(raw_jobs)} → {len(enriched)} jobs")
            return enriched

        except Exception as e:
            self.logger.error(f"AI enrichment failed — returning raw jobs: {e}")
            # Fallback: return all jobs if AI fails (graceful degradation)
            return raw_jobs


# Factory function for DI compatibility
def create_freelance_ru_scraper(
        config: UnifiedConfigManager,
        crypto: AdvancedCryptoSystem,
        monitor: IntelligentMonitoringSystem,
        ai_manager: IntelligentModelManager,
        db: DatabaseService,
) -> FreelanceRuScraper:
    """Factory to support dependency injection."""
    return FreelanceRuScraper(config, crypto, monitor, ai_manager, db)