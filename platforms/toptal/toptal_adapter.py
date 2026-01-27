"""
Адаптер для премиальной платформы Toptal
"""
import json
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta

from platforms.universal_platform_adapter import (
    UniversalPlatformAdapter,
    PlatformConfig,
    PlatformType,
    AuthenticationMethod,
    PlatformFieldMapping,
    Job
)

logger = logging.getLogger(__name__)


class ToptalAdapter(UniversalPlatformAdapter):
    """
    Адаптер для работы с премиальной платформой Toptal
    Особенности:
    - Строгий отбор через скрининг
    - Высокие ставки ($60-200/час)
    - Долгосрочные проекты
    - Требуется портфолио и тестирование
    """

    def __init__(self, config_path: str = "platforms/toptal/toptal_config.json"):
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
        self.screening_requirements = config_data.get("screening_requirements", {})

        logger.info("Инициализирован адаптер Toptal")

    async def search_premium_jobs(self,
                                  skills: List[str],
                                  min_hourly_rate: float = 60.0,
                                  max_hourly_rate: Optional[float] = None,
                                  experience_level: str = "senior",
                                  duration_min_days: Optional[int] = None) -> List[Job]:
        """
        Поиск премиальных заказов на Toptal
        """
        params = {
            "skills": ",".join(skills),
            "min_hourly_rate": min_hourly_rate,
            "experience_level": experience_level,
            "status": "open"
        }

        if max_hourly_rate:
            params["max_hourly_rate"] = max_hourly_rate

        if duration_min_days:
            params["min_duration_days"] = duration_min_days

        response = await self._make_request("GET", "jobs", params=params)

        jobs = []
        for raw_job in response.get("jobs", []):
            job = self._parse_job(raw_job)
            # Фильтрация по минимальной ставке
            if job.budget and job.budget >= min_hourly_rate:
                jobs.append(job)

        return jobs

    async def apply_to_job(self, job_id: str, cover_letter: str,
                           portfolio_items: List[str],
                           availability_hours: int = 40) -> Dict[str, Any]:
        """
        Подача заявки на заказ на Toptal
        Требуется качественное сопроводительное письмо и портфолио
        """
        application_data = {
            "cover_letter": cover_letter,
            "portfolio_items": portfolio_items,
            "availability_hours_per_week": availability_hours,
            "rate_expectation": None  # Toptal сам определяет ставку
        }

        endpoint = f"jobs/{job_id}/applications"
        response = await self._make_request("POST", endpoint, json=application_data)

        return {
            "success": True,
            "application_id": response.get("id"),
            "job_id": job_id,
            "status": "submitted",
            "screening_required": True
        }

    async def check_screening_status(self) -> Dict[str, Any]:
        """
        Проверка статуса скрининга
        """
        response = await self._make_request("GET", "screening/status")

        return {
            "status": response.get("status"),
            "test_score": response.get("test_score"),
            "english_level": response.get("english_level"),
            "portfolio_approved": response.get("portfolio_approved"),
            "ready_for_jobs": response.get("ready_for_jobs", False)
        }

    async def complete_profile(self, profile_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Заполнение профиля для соответствия требованиям Toptal
        """
        # Валидация данных профиля
        required_fields = ["name", "title", "skills", "experience_years", "portfolio"]

        for field in required_fields:
            if field not in profile_data:
                raise ValueError(f"Обязательное поле отсутствует: {field}")

        # Проверка опыта
        experience_years = profile_data.get("experience_years", 0)
        if experience_years < self.screening_requirements.get("experience_years", 3):
            raise ValueError(f"Требуется минимум {self.screening_requirements['experience_years']} лет опыта")

        # Проверка портфолио
        portfolio = profile_data.get("portfolio", [])
        if not portfolio and self.screening_requirements.get("portfolio_required", True):
            raise ValueError("Портфолио обязательно для Toptal")

        response = await self._make_request("PUT", "profile", json=profile_data)

        return {
            "success": True,
            "profile_id": response.get("id"),
            "completion_percentage": response.get("completion_percentage", 0),
            "ready_for_screening": response.get("ready_for_screening", False)
        }

    async def get_client_details(self, client_id: str) -> Dict[str, Any]:
        """
        Получение деталей клиента (только для премиум-платформ)
        """
        response = await self._make_request("GET", f"clients/{client_id}")

        return {
            "name": response.get("name"),
            "industry": response.get("industry"),
            "company_size": response.get("company_size"),
            "budget_range": response.get("budget_range"),
            "previous_projects": response.get("projects_count", 0),
            "rating": response.get("rating"),
            "verified": response.get("verified", False)
        }

    async def schedule_interview(self, job_id: str, preferred_times: List[str]) -> Dict[str, Any]:
        """
        Запрос собеседования с клиентом
        """
        interview_data = {
            "job_id": job_id,
            "preferred_times": preferred_times,
            "timezone": "UTC"
        }

        response = await self._make_request("POST", "interviews", json=interview_data)

        return {
            "success": True,
            "interview_id": response.get("id"),
            "scheduled_time": response.get("scheduled_time"),
            "client_id": response.get("client_id"),
            "meeting_link": response.get("meeting_link")
        }