"""
Адаптер для российской платформы Хабр Фриланс
"""
import json
import logging
import re
from typing import Dict, Any, Optional, List
from datetime import datetime

from platforms.universal_platform_adapter import (
    UniversalPlatformAdapter,
    PlatformConfig,
    PlatformType,
    AuthenticationMethod,
    PlatformFieldMapping,
    Job,
    Bid
)

logger = logging.getLogger(__name__)


class HabrFreelanceAdapter(UniversalPlatformAdapter):
    """
    Адаптер для работы с Хабр Фриланс
    Особенности:
    - Российская платформа
    - Поддержка русского языка
    - Оплата в рублях
    - Популярные категории: разработка, дизайн, копирайтинг
    """

    def __init__(self, config_path: str = "platforms/habr_freelance/habr_freelance_config.json"):
        with open(config_path, 'r', encoding='utf-8') as f:
            config_data = json.load(f)

        config = PlatformConfig(
            name=config_data["name"],
            base_url=config_data["api_base_url"],
            platform_type=PlatformType(config_data["platform_type"]),
            auth_method=AuthenticationMethod(config_data["auth_method"]),
            api_version=config_data["api_version"],
            endpoints=config_data["endpoints"],
            field_mapping=PlatformFieldMapping(**config_data["field_mapping"]),
            auth_params=config_data["auth_params"],
            default_headers=config_data["default_headers"],
            pagination=config_data["pagination"],
            scraping=config_data.get("scraping", {}),
            rate_limit=config_data["rate_limit"]
        )

        super().__init__(config)
        self.categories = config_data.get("categories", {})

        logger.info("Инициализирован адаптер Хабр Фриланс")

    async def search_russian_orders(self,
                                    category: Optional[str] = None,
                                    budget_min: Optional[float] = None,
                                    budget_max: Optional[float] = None,
                                    only_verified: bool = False,
                                    page: int = 1) -> List[Job]:
        """
        Поиск заказов на Хабр Фриланс
        """
        params = {
            "page": page
        }

        if category and category in self.categories:
            params["categories"] = self.categories[category]

        if budget_min:
            params["budget_from"] = budget_min

        if budget_max:
            params["budget_to"] = budget_max

        if only_verified:
            params["verified"] = "true"

        # Хабр не имеет полноценного API, используем парсинг HTML
        return await self._scrape_orders(params)

    async def _scrape_orders(self, params: Dict[str, Any]) -> List[Job]:
        """Парсинг заказов с сайта Хабр Фриланс"""
        import aiohttp
        from bs4 import BeautifulSoup

        url = f"{self.config.base_url}/orders"

        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, headers=self.config.default_headers) as response:
                html = await response.text()

        soup = BeautifulSoup(html, 'html.parser')
        orders = []

        # Поиск всех заказов на странице
        order_elements = soup.select('article.task')

        for order_element in order_elements:
            try:
                order = self._parse_habr_order(order_element)
                if order:
                    orders.append(order)
            except Exception as e:
                logger.error(f"Ошибка парсинга заказа: {str(e)}")
                continue

        return orders

    def _parse_habr_order(self, order_element) -> Optional[Job]:
        """Парсинг элемента заказа Хабр Фриланс"""
        # Извлечение заголовка
        title_element = order_element.select_one('h2.task__title a')
        if not title_element:
            return None

        title = title_element.get_text(strip=True)
        order_url = f"https://freelance.habr.com{title_element['href']}"
        order_id = title_element['href'].split('/')[-1]

        # Извлечение описания
        description_element = order_element.select_one('div.task__description')
        description = description_element.get_text(strip=True) if description_element else ""

        # Извлечение бюджета
        budget_element = order_element.select_one('div.task__price')
        budget_text = budget_element.get_text(strip=True) if budget_element else ""

        budget = None
        currency = "RUB"

        # Парсинг бюджета (например: "5 000 ₽" или "10 000 - 15 000 ₽")
        if budget_text:
            # Удаление символов валюты и пробелов
            budget_clean = re.sub(r'[^\d\-]', '', budget_text)

            if '-' in budget_clean:
                # Диапазон бюджета - берем среднее
                parts = budget_clean.split('-')
                try:
                    min_budget = int(parts[0])
                    max_budget = int(parts[1])
                    budget = (min_budget + max_budget) / 2
                except:
                    pass
            else:
                try:
                    budget = int(budget_clean)
                except:
                    pass

        # Извлечение навыков
        skills = []
        skills_element = order_element.select_one('div.tags.tags--auto')
        if skills_element:
            skill_tags = skills_element.select('li.tags__item')
            for tag in skill_tags:
                skills.append(tag.get_text(strip=True))

        # Извлечение даты публикации
        meta_element = order_element.select_one('div.task__meta')
        posted_date = None
        if meta_element:
            meta_text = meta_element.get_text()
            # Поиск даты в формате "15 января 2024"
            date_match = re.search(r'(\d{1,2})\s+(\w+)\s+(\d{4})', meta_text)
            if date_match:
                day = int(date_match.group(1))
                month_name = date_match.group(2)
                year = int(date_match.group(3))

                # Преобразование названия месяца в число
                months = {
                    'января': 1, 'февраля': 2, 'марта': 3, 'апреля': 4,
                    'мая': 5, 'июня': 6, 'июля': 7, 'августа': 8,
                    'сентября': 9, 'октября': 10, 'ноября': 11, 'декабря': 12
                }

                month = months.get(month_name.lower(), 1)
                posted_date = datetime(year, month, day)

        # Извлечение количества предложений
        proposals_count = None
        count_element = order_element.select_one('span.count')
        if count_element:
            count_text = count_element.get_text(strip=True)
            try:
                proposals_count = int(count_text)
            except:
                pass

        # Извлечение дедлайна
        deadline = None
        deadline_element = order_element.select_one('div.task__deadline time')
        if deadline_element:
            deadline_text = deadline_element.get_text(strip=True)
            # Парсинг дедлайна (например: "до 20 января")

        # Определение типа заказа
        job_type = "fixed"
        if "посуточно" in budget_text.lower() or "в час" in budget_text.lower():
            job_type = "hourly"

        return Job(
            id=str(order_id),
            title=title,
            description=description,
            budget=float(budget) if budget else None,
            currency=currency,
            deadline=deadline,
            skills=skills,
            client_rating=None,
            job_type=job_type,
            experience_level="any",
            location="Russia",
            posted_date=posted_date,
            proposals_count=proposals_count,
            platform="Хабр Фриланс",
            raw_data={},
            url=order_url
        )

    async def place_russian_bid(self, order_id: str, price: float,
                                description: str, days: int = 7) -> Dict[str, Any]:
        """
        Размещение предложения на заказ Хабр Фриланс
        """
        bid_data = {
            "price": price,
            "description": description,
            "days": days,
            "csrfmiddlewaretoken": self.config.auth_params["cookies"]["csrftoken"]
        }

        endpoint = f"orders/{order_id}/offers"

        try:
            response = await self._make_request("POST", endpoint, data=bid_data)

            return {
                "success": True,
                "bid_id": response.get("id"),
                "order_id": order_id,
                "price": price,
                "status": "submitted"
            }
        except Exception as e:
            # Хабр может блокировать автоматические предложения
            logger.error(f"Ошибка размещения предложения: {str(e)}")

            return {
                "success": False,
                "error": str(e),
                "manual_action_required": True,
                "order_url": f"https://freelance.habr.com/tasks/{order_id}"
            }

    async def get_my_responses(self) -> List[Dict[str, Any]]:
        """Получение моих откликов"""
        response = await self._make_request("GET", "offers")

        return response.get("offers", [])

    async def get_order_details(self, order_id: str) -> Optional[Dict[str, Any]]:
        """Получение деталей заказа"""
        # Парсинг HTML страницы заказа
        url = f"https://freelance.habr.com/tasks/{order_id}"

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self.config.default_headers) as response:
                html = await response.text()

        soup = BeautifulSoup(html, 'html.parser')

        # Извлечение полной информации о заказе
        details = {
            "title": soup.select_one('h1.page-title').get_text(strip=True) if soup.select_one('h1.page-title') else "",
            "description": soup.select_one('div.task__description').get_text(strip=True) if soup.select_one(
                'div.task__description') else "",
            "budget": soup.select_one('div.task__price').get_text(strip=True) if soup.select_one(
                'div.task__price') else "",
            "responses_count": soup.select_one('a.tab-item[href*="responses"]').get_text(strip=True) if soup.select_one(
                'a.tab-item[href*="responses"]') else "0",
            "views_count": soup.select_one('div.task__views').get_text(strip=True) if soup.select_one(
                'div.task__views') else "0",
            "category": soup.select_one('a[href*="categories"]').get_text(strip=True) if soup.select_one(
                'a[href*="categories"]') else "",
            "published_at": soup.select_one('div.task__meta time').get_text(strip=True) if soup.select_one(
                'div.task__meta time') else ""
        }

        return details

    async def check_client_reputation(self, client_id: str) -> Dict[str, Any]:
        """Проверка репутации клиента"""
        response = await self._make_request("GET", f"profile/{client_id}")

        return {
            "name": response.get("username"),
            "rating": response.get("rating"),
            "orders_count": response.get("stats", {}).get("orders_count", 0),
            "reviews_count": response.get("stats", {}).get("reviews_count", 0),
            "registration_date": response.get("created_at"),
            "is_verified": response.get("is_verified", False),
            "badges": response.get("badges", [])
        }