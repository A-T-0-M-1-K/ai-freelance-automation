"""
Адаптер для российской платформы Профи.ру
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


class ProfiRuAdapter(UniversalPlatformAdapter):
    """
    Адаптер для работы с Профи.ру
    Особенности:
    - Российская платформа для специалистов
    - Верификация специалистов
    - Система отзывов и рейтингов
    - Оплата в рублях
    """

    def __init__(self, config_path: str = "platforms/profi_ru/profi_ru_config.json"):
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
            rate_limit=config_data["rate_limit"]
        )

        super().__init__(config)
        self.available_categories = config_data.get("categories", [])

        logger.info("Инициализирован адаптер Профи.ру")

    async def search_orders(self,
                            categories: Optional[List[str]] = None,
                            city: Optional[str] = None,
                            budget_min: Optional[float] = None,
                            only_new: bool = True,
                            page: int = 1) -> List[Job]:
        """
        Поиск заказов на Профи.ру
        """
        params = {
            "page": page,
            "limit": self.config.pagination["default_size"]
        }

        if categories:
            valid_categories = [c for c in categories if c in self.available_categories]
            if valid_categories:
                params["categories"] = ",".join(valid_categories)

        if city:
            params["city"] = city

        if budget_min:
            params["min_budget"] = budget_min

        if only_new:
            params["status"] = "new"

        response = await self._make_request("GET", "orders/search", params=params)

        orders = []
        for raw_order in response.get("orders", []):
            order = self._parse_order(raw_order)
            orders.append(order)

        return orders

    def _parse_order(self, raw_order: Dict[str, Any]) -> Job:
        """Парсинг заказа Профи.ру в стандартную структуру"""
        title = raw_order.get("title", "")
        description = raw_order.get("description", "")
        order_id = raw_order.get("id", "")

        # Извлечение бюджета
        price_info = raw_order.get("price", {})
        budget_max = price_info.get("max")
        currency = price_info.get("currency", "RUB")

        # Извлечение дедлайна
        deadline_str = raw_order.get("deadline")
        deadline = datetime.fromisoformat(deadline_str.replace('Z', '+00:00')) if deadline_str else None

        # Извлечение категорий
        categories = raw_order.get("categories", [])

        # Извлечение локации
        location_info = raw_order.get("location", {})
        city = location_info.get("city", "anywhere")

        # Извлечение даты создания
        created_at = raw_order.get("created_at")
        posted_date = datetime.fromisoformat(created_at.replace('Z', '+00:00')) if created_at else None

        # Извлечение количества откликов
        responses_count = raw_order.get("responses_count", 0)

        # Определение типа заказа
        order_type = raw_order.get("type", "one_time")

        return Job(
            id=str(order_id),
            title=title,
            description=description,
            budget=float(budget_max) if budget_max else None,
            currency=currency,
            deadline=deadline,
            skills=categories,
            client_rating=None,
            job_type=order_type,
            experience_level="any",
            location=city,
            posted_date=posted_date,
            proposals_count=responses_count,
            platform="Профи.ру",
            raw_data=raw_order,
            url=f"https://profi.ru/orders/{order_id}"
        )

    async def place_response(self, order_id: str, price: float,
                             comment: str, portfolio_links: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Отклик на заказ на Профи.ру
        """
        response_data = {
            "order_id": order_id,
            "price": price,
            "comment": comment,
            "portfolio_links": portfolio_links or []
        }

        endpoint = f"orders/{order_id}/responses"
        response = await self._make_request("POST", endpoint, json=response_data)

        return {
            "success": True,
            "response_id": response.get("id"),
            "order_id": order_id,
            "status": "submitted",
            "requires_verification": response.get("requires_verification", False)
        }

    async def get_my_responses(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """Получение моих откликов"""
        params = {}
        if status:
            params["status"] = status

        response = await self._make_request("GET", "responses", params=params)

        return response.get("responses", [])

    async def complete_specialist_verification(self, specialist_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Прохождение верификации специалиста на Профи.ру
        """
        # Валидация данных
        required_fields = ["name", "specialization", "experience_years", "portfolio", "documents"]

        for field in required_fields:
            if field not in specialist_data:
                raise ValueError(f"Обязательное поле отсутствует: {field}")

        response = await self._make_request("POST", "verification", json=specialist_data)

        return {
            "success": True,
            "verification_id": response.get("id"),
            "status": response.get("status"),
            "specialist_level": response.get("level"),
            "badges": response.get("badges", []),
            "visibility_boost": response.get("visibility_boost", 0)
        }

    async def get_client_info(self, client_id: str) -> Dict[str, Any]:
        """Получение информации о клиенте"""
        response = await self._make_request("GET", f"clients/{client_id}")

        return {
            "name": response.get("name"),
            "rating": response.get("rating"),
            "orders_count": response.get("orders_count", 0),
            "is_verified": response.get("is_verified", False),
            "preferred_categories": response.get("preferred_categories", []),
            "budget_range": response.get("budget_range", {})
        }

    async def get_market_statistics(self, category: str, city: str) -> Dict[str, Any]:
        """Получение статистики рынка"""
        params = {
            "category": category,
            "city": city
        }

        response = await self._make_request("GET", "statistics/market", params=params)

        return {
            "average_price": response.get("average_price"),
            "orders_count": response.get("orders_count"),
            "competition_level": response.get("competition_level"),
            "demand_trend": response.get("demand_trend"),
            "top_skills": response.get("top_skills", []),
            "average_response_time": response.get("average_response_time")
        }