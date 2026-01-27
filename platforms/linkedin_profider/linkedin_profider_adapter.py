"""
Адаптер для B2B платформы LinkedIn ProFinder
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


class LinkedInProFinderAdapter(UniversalPlatformAdapter):
    """
    Адаптер для работы с LinkedIn ProFinder
    Особенности:
    - B2B фокус (корпоративные клиенты)
    - Интеграция с LinkedIn профилем
    - Высокие бюджеты проектов
    - Долгосрочные контракты
    """

    def __init__(self, config_path: str = "platforms/linkedin_profider/linkedin_profider_config.json"):
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
        self.project_types = config_data.get("project_types", [])

        logger.info("Инициализирован адаптер LinkedIn ProFinder")

    async def search_b2b_projects(self,
                                  industry: Optional[str] = None,
                                  company_size: Optional[str] = None,
                                  budget_min: Optional[float] = None,
                                  project_type: Optional[str] = None,
                                  location: Optional[str] = None) -> List[Job]:
        """
        Поиск B2B проектов на LinkedIn ProFinder
        """
        params = {
            "q": "projects"
        }

        if industry:
            params["industry"] = industry

        if company_size:
            params["company_size"] = company_size

        if budget_min:
            params["min_budget"] = budget_min

        if project_type and project_type in self.project_types:
            params["project_type"] = project_type

        if location:
            params["location"] = location

        response = await self._make_request("GET", "projects", params=params)

        projects = []
        for raw_project in response.get("elements", []):
            project = self._parse_linkedin_project(raw_project)
            projects.append(project)

        return projects

    def _parse_linkedin_project(self, raw_project: Dict[str, Any]) -> Job:
        """Парсинг проекта LinkedIn в стандартную структуру"""
        # Извлечение основных данных
        title = raw_project.get("title", "")
        description = raw_project.get("description", "")
        project_id = raw_project.get("id", "")

        # Извлечение бюджета
        budget_range = raw_project.get("budgetRange", {})
        budget_max = budget_range.get("max", {}).get("amount", 0)
        currency = budget_range.get("currencyCode", "USD")

        # Извлечение дедлайна
        deadline_str = raw_project.get("deadline")
        deadline = datetime.fromisoformat(deadline_str.replace('Z', '+00:00')) if deadline_str else None

        # Извлечение навыков
        skills = raw_project.get("skills", [])

        # Извлечение информации о клиенте
        client = raw_project.get("client", {})
        client_name = client.get("name", "")
        client_location = client.get("location", "anywhere")

        # Извлечение даты создания
        created_time = raw_project.get("createdTime")
        posted_date = datetime.fromtimestamp(created_time / 1000) if created_time else None

        # Формирование URL
        project_url = f"https://www.linkedin.com/profinder/projects/{project_id}"

        return Job(
            id=str(project_id),
            title=title,
            description=description,
            budget=float(budget_max) if budget_max else None,
            currency=currency,
            deadline=deadline,
            skills=skills,
            client_rating=None,
            job_type="project",
            experience_level="senior",
            location=client_location,
            posted_date=posted_date,
            proposals_count=raw_project.get("proposalCount", 0),
            platform="LinkedIn ProFinder",
            raw_data=raw_project,
            url=project_url
        )

    async def submit_proposal(self, project_id: str, proposal_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Подача предложения на проект LinkedIn ProFinder
        """
        # Валидация данных предложения
        required_fields = ["coverLetter", "hourlyRate", "availability"]

        for field in required_fields:
            if field not in proposal_data:
                raise ValueError(f"Обязательное поле отсутствует: {field}")

        endpoint = f"projects/{project_id}/proposals"
        response = await self._make_request("POST", endpoint, json=proposal_data)

        return {
            "success": True,
            "proposal_id": response.get("id"),
            "project_id": project_id,
            "status": "submitted"
        }

    async def get_lead_details(self, lead_id: str) -> Dict[str, Any]:
        """
        Получение деталей лида (потенциального клиента)
        """
        response = await self._make_request("GET", f"leads/{lead_id}")

        return {
            "company_name": response.get("companyName"),
            "industry": response.get("industry"),
            "company_size": response.get("companySize"),
            "contact_person": response.get("contactPerson"),
            "email": response.get("email"),
            "phone": response.get("phone"),
            "project_description": response.get("projectDescription"),
            "budget_range": response.get("budgetRange"),
            "timeline": response.get("timeline")
        }

    async def sync_linkedin_profile(self) -> Dict[str, Any]:
        """
        Синхронизация данных с LinkedIn профилем
        """
        # Получение профиля LinkedIn
        profile_response = await self._make_request("GET", "profile")

        # Получение рекомендаций
        recommendations_response = await self._make_request("GET", "recommendations")

        # Получение опыта работы
        experience_response = await self._make_request("GET", "experience")

        return {
            "profile_url": profile_response.get("publicProfileUrl"),
            "headline": profile_response.get("headline"),
            "summary": profile_response.get("summary"),
            "recommendations_count": len(recommendations_response.get("elements", [])),
            "experience_years": len(experience_response.get("elements", [])),
            "connections_count": profile_response.get("connectionsCount", 0),
            "synced_at": datetime.now().isoformat()
        }

    async def get_project_analytics(self) -> Dict[str, Any]:
        """
        Получение аналитики по проектам
        """
        response = await self._make_request("GET", "analytics/projects")

        return {
            "views": response.get("views", 0),
            "proposals_sent": response.get("proposalsSent", 0),
            "proposals_accepted": response.get("proposalsAccepted", 0),
            "conversion_rate": response.get("conversionRate", 0),
            "average_budget": response.get("averageBudget", 0),
            "top_industries": response.get("topIndustries", []),
            "top_skills": response.get("topSkills", [])
        }

    async def send_connection_request(self, project_id: str, message: str) -> Dict[str, Any]:
        """
        Отправка запроса на подключение клиенту проекта
        """
        connection_data = {
            "projectId": project_id,
            "message": message,
            "note": "Interested in your project"
        }

        response = await self._make_request("POST", "connections", json=connection_data)

        return {
            "success": True,
            "connection_id": response.get("id"),
            "status": "pending"
        }