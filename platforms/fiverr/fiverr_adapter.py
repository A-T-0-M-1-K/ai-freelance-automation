"""
Адаптер для платформы Fiverr
"""
import json
import logging
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


class FiverrAdapter(UniversalPlatformAdapter):
    """
    Адаптер для работы с платформой Fiverr
    """

    def __init__(self, config_path: str = "platforms/fiverr/fiverr_config.json"):
        # Загрузка конфигурации
        with open(config_path, 'r', encoding='utf-8') as f:
            config_data = json.load(f)

        # Создание конфигурации платформы
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
            rate_limit=config_data["rate_limit"]
        )

        super().__init__(config)
        self.categories = config_data.get("categories", [])
        self.package_types = config_data.get("package_types", [])

        logger.info("Инициализирован адаптер Fiverr")

    async def search_gigs(self,
                          query: str,
                          category: Optional[str] = None,
                          min_price: Optional[float] = None,
                          max_price: Optional[float] = None,
                          page: int = 1) -> List[Job]:
        """
        Поиск гигов на Fiverr
        """
        params = {
            "query": query,
            "page": page
        }

        if category and category in self.categories:
            params["category"] = category

        if min_price:
            params["min_price"] = min_price

        if max_price:
            params["max_price"] = max_price

        response = await self._make_request("GET", "gigs/search", params=params)

        gigs = []
        for raw_gig in response.get("gigs", []):
            # Преобразование гига в стандартную структуру Job
            gig = self._parse_gig(raw_gig)
            gigs.append(gig)

        return gigs

    def _parse_gig(self, raw_gig: Dict[str, Any]) -> Job:
        """Парсинг гига Fiverr в стандартную структуру"""
        # Извлечение основных данных
        title = raw_gig.get("title", "")
        description = raw_gig.get("description", "")
        gig_id = raw_gig.get("id", "")

        # Извлечение пакетов (цены)
        packages = raw_gig.get("packages", [])
        if packages:
            basic_package = packages[0]
            budget = basic_package.get("price")
            currency = basic_package.get("currency", "USD")
            delivery_time = basic_package.get("delivery_time", 7)
        else:
            budget = None
            currency = "USD"
            delivery_time = 7

        # Извлечение навыков
        skills = raw_gig.get("skills", [])

        # Извлечение информации о продавце
        seller = raw_gig.get("seller", {})
        client_rating = seller.get("rating")
        location = seller.get("location", "anywhere")

        # Извлечение даты создания
        created_at = raw_gig.get("created_at")

        # Формирование URL
        gig_url = f"https://www.fiverr.com/gigs/{gig_id}"

        return Job(
            id=str(gig_id),
            title=title,
            description=description,
            budget=float(budget) if budget else None,
            currency=currency,
            deadline=datetime.now() if delivery_time else None,
            skills=skills,
            client_rating=float(client_rating) if client_rating else None,
            job_type="gig",
            experience_level="any",
            location=location,
            posted_date=datetime.fromisoformat(created_at.replace('Z', '+00:00')) if created_at else None,
            proposals_count=None,
            platform="Fiverr",
            raw_data=raw_gig,
            url=gig_url
        )

    async def create_gig(self,
                         title: str,
                         category: str,
                         description: str,
                         packages: List[Dict[str, Any]],
                         skills: List[str]) -> Dict[str, Any]:
        """
        Создание нового гига на Fiverr
        """
        gig_data = {
            "title": title,
            "category": category,
            "description": description,
            "packages": packages,
            "skills": skills
        }

        response = await self._make_request("POST", "gigs", json=gig_data)

        return {
            "success": True,
            "gig_id": response.get("id"),
            "url": f"https://www.fiverr.com/gigs/{response.get('id')}"
        }

    async def place_order(self, gig_id: str, package_type: str, requirements: str) -> Dict[str, Any]:
        """
        Размещение заказа на гиг
        """
        if package_type not in self.package_types:
            raise ValueError(f"Неверный тип пакета. Допустимые: {self.package_types}")

        order_data = {
            "gig_id": gig_id,
            "package": package_type,
            "requirements": requirements
        }

        response = await self._make_request("POST", "orders", json=order_data)

        return {
            "success": True,
            "order_id": response.get("id"),
            "gig_id": gig_id
        }

    async def get_analytics(self) -> Dict[str, Any]:
        """
        Получение аналитики по гигам
        """
        response = await self._make_request("GET", "analytics")

        return {
            "impressions": response.get("impressions", 0),
            "clicks": response.get("clicks", 0),
            "orders": response.get("orders", 0),
            "earnings": response.get("earnings", 0),
            "conversion_rate": response.get("conversion_rate", 0)
        }