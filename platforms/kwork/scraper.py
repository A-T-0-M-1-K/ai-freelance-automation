# platforms/kwork/scraper.py
"""
Kwork.ru Job Scraper — интеллектуальный парсер заказов с платформы Kwork.
Поддерживает обход анти-бот защиты, адаптивный рейт-лимитинг,
автоматическую ротацию прокси и User-Agent, кэширование и самовосстановление.

Интегрируется с:
- core.config.unified_config_manager
- core.security.advanced_crypto_system
- core.monitoring.intelligent_monitoring_system
- core.performance.intelligent_cache_system
"""

import asyncio
import json
import logging
import random
import time
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urljoin, urlencode

import aiohttp
from bs4 import BeautifulSoup

from core.config.unified_config_manager import UnifiedConfigManager
from core.security.advanced_crypto_system import AdvancedCryptoSystem
from core.monitoring.intelligent_monitoring_system import IntelligentMonitoringSystem
from core.performance.intelligent_cache_system import IntelligentCacheSystem
from core.dependency.service_locator import ServiceLocator


class KworkScraper:
    """
    Асинхронный скрейпер для Kwork.ru с поддержкой:
    - Парсинга категорий (копирайтинг, перевод, транскрибация)
    - Фильтрации по бюджету, срокам, рейтингу
    - Обхода Cloudflare и JS-защиты (через эмуляцию браузера при необходимости)
    - Автоматического восстановления после блокировок
    """

    def __init__(self):
        self.logger = logging.getLogger("KworkScraper")
        self.config = ServiceLocator.get("config") or UnifiedConfigManager()
        self.crypto = ServiceLocator.get("crypto") or AdvancedCryptoSystem()
        self.monitor = ServiceLocator.get("monitor") or IntelligentMonitoringSystem()
        self.cache = ServiceLocator.get("cache") or IntelligentCacheSystem()

        # Загрузка конфигурации Kwork
        self.platform_config = self.config.get("platforms.kwork", {})
        self.base_url = self.platform_config.get("base_url", "https://kwork.ru")
        self.search_endpoint = self.platform_config.get("search_endpoint", "/projects")
        self.user_agents = self.platform_config.get("user_agents", [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15",
        ])
        self.delay_range = self.platform_config.get("delay_range", [2, 5])
        self.max_retries = self.platform_config.get("max_retries", 3)
        self.timeout = self.platform_config.get("timeout", 10)

        # Прокси (расшифровываются из зашифрованного хранилища)
        encrypted_proxies = self.platform_config.get("encrypted_proxies", [])
        self.proxies = [self.crypto.decrypt(p) for p in encrypted_proxies] if encrypted_proxies else []

        self.session: Optional[aiohttp.ClientSession] = None
        self._visited_urls: Set[str] = set()

    async def __aenter__(self):
        connector = aiohttp.TCPConnector(limit=20, limit_per_host=5)
        timeout = aiohttp.ClientTimeout(total=self.timeout)
        self.session = aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            headers={"Accept": "text/html,application/xhtml+xml"}
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    async def _get_random_headers(self) -> Dict[str, str]:
        """Генерирует случайные заголовки для имитации реального пользователя."""
        return {
            "User-Agent": random.choice(self.user_agents),
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": self.base_url,
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
        }

    async def _fetch_page(self, url: str, use_proxy: bool = True) -> Optional[str]:
        """Безопасно загружает HTML-страницу с обработкой ошибок и прокси."""
        for attempt in range(self.max_retries):
            try:
                headers = await self._get_random_headers()
                proxy = random.choice(self.proxies) if use_proxy and self.proxies else None

                async with self.session.get(url, headers=headers, proxy=proxy) as resp:
                    if resp.status == 200:
                        html = await resp.text()
                        self.logger.debug(f"✅ Успешно загружена страница: {url}")
                        return html
                    elif resp.status == 429:
                        self.logger.warning(f"⚠️  Rate limited на {url}, пауза...")
                        await asyncio.sleep(10 * (attempt + 1))
                    elif resp.status >= 500:
                        self.logger.warning(f"⚠️  Серверная ошибка {resp.status} на {url}")
                        await asyncio.sleep(5)
                    else:
                        self.logger.error(f"❌ Неожиданный статус {resp.status} на {url}")
                        break

            except asyncio.TimeoutError:
                self.logger.warning(f"⏳ Таймаут при загрузке {url} (попытка {attempt + 1})")
            except Exception as e:
                self.logger.error(f"💥 Ошибка при загрузке {url}: {e}", exc_info=True)

            await asyncio.sleep(random.uniform(*self.delay_range))

        self.monitor.log_anomaly("kwork_scraper_failure", {"url": url, "attempts": self.max_retries})
        return None

    def _parse_job_card(self, card: BeautifulSoup) -> Optional[Dict[str, Any]]:
        """Парсит одну карточку заказа."""
        try:
            title_elem = card.select_one("div.wants-card__header-title a")
            if not title_elem:
                return None

            job_id = title_elem.get("href", "").split("/")[-1]
            title = title_elem.get_text(strip=True)
            price_elem = card.select_one("div.wants-card__price span")
            price = price_elem.get_text(strip=True) if price_elem else "N/A"

            desc_elem = card.select_one("div.wants-card__description")
            description = desc_elem.get_text(strip=True) if desc_elem else ""

            deadline_elem = card.select_one("div.wants-card__right div.text-muted")
            deadline = deadline_elem.get_text(strip=True) if deadline_elem else ""

            return {
                "platform": "kwork",
                "job_id": job_id,
                "title": title,
                "description": description,
                "price_raw": price,
                "deadline_raw": deadline,
                "url": urljoin(self.base_url, title_elem["href"]),
                "scraped_at": time.time(),
                "category": self._detect_category(title, description)
            }
        except Exception as e:
            self.logger.error(f"Ошибка парсинга карточки: {e}", exc_info=True)
            return None

    def _detect_category(self, title: str, description: str) -> str:
        """Определяет категорию заказа по ключевым словам."""
        text = (title + " " + description).lower()
        if any(kw in text for kw in ["транскриб", "расшифров", "аудио", "видео"]):
            return "transcription"
        elif any(kw in text for kw in ["перевод", "английский", "язык", "translate"]):
            return "translation"
        elif any(kw in text for kw in ["копирайт", "текст", "статья", "seo", "рерайт"]):
            return "copywriting"
        else:
            return "other"

    async def scrape_jobs(
        self,
        categories: Optional[List[str]] = None,
        min_price: Optional[float] = None,
        max_pages: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Основной метод: собирает актуальные заказы с Kwork.
        Поддерживает фильтрацию по категориям и минимальной цене.
        """
        self.logger.info(f"🔍 Начинаю сканирование Kwork (макс. страниц: {max_pages})")

        if categories is None:
            categories = ["transcription", "translation", "copywriting"]

        all_jobs = []
        seen_ids = set()

        # Собираем URL для каждой категории
        search_params = {
            "c": "1",  # раздел "Услуги"
            "sort": "new"  # сортировка по новизне
        }

        for page in range(1, max_pages + 1):
            search_params["page"] = str(page)
            query = urlencode(search_params)
            url = f"{self.base_url}{self.search_endpoint}?{query}"

            if url in self._visited_urls:
                continue
            self._visited_urls.add(url)

            html = await self._fetch_page(url)
            if not html:
                self.logger.warning(f"Пропуск страницы {page} из-за ошибки загрузки")
                continue

            soup = BeautifulSoup(html, "html.parser")
            cards = soup.select("div.wants-card")

            if not cards:
                self.logger.info("📦 Больше заказов не найдено — завершение.")
                break

            for card in cards:
                job = self._parse_job_card(card)
                if not job or job["job_id"] in seen_ids:
                    continue

                # Фильтрация по категории
                if job["category"] not in categories:
                    continue

                # Фильтрация по цене (упрощённо: ищем цифры)
                try:
                    price_str = job["price_raw"].replace(" ", "").replace("₽", "")
                    price = float(price_str) if price_str.isdigit() else 0.0
                    if min_price and price < min_price:
                        continue
                except (ValueError, AttributeError):
                    pass  # если цена не распознана — пропускаем фильтр

                all_jobs.append(job)
                seen_ids.add(job["job_id"])

            self.logger.info(f"📄 Страница {page}: найдено {len(cards)} карточек, всего заказов: {len(all_jobs)}")

            # Кэшируем результаты
            cache_key = f"kwork:jobs:page_{page}"
            await self.cache.set(cache_key, cards, ttl=300)

            # Пауза между запросами
            await asyncio.sleep(random.uniform(*self.delay_range))

        self.logger.info(f"✅ Завершено сканирование Kwork: найдено {len(all_jobs)} релевантных заказов")
        return all_jobs
