"""
Универсальный адаптер для поддержки любых фриланс-платформ
Позволяет добавлять новые платформы через конфигурацию без изменения кода
"""
import asyncio
import json
import logging
from typing import Dict, Any, Optional, List, Tuple, Callable
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
import aiohttp
from bs4 import BeautifulSoup
import re

from platforms.platform_factory import PlatformBase
from core.communication.multilingual_support import MultilingualSupport

logger = logging.getLogger(__name__)


class PlatformType(Enum):
    """Типы платформ"""
    FREELANCE_MARKETPLACE = "freelance_marketplace"
    PREMIUM_NETWORK = "premium_network"
    B2B_PLATFORM = "b2b_platform"
    LOCAL_MARKETPLACE = "local_marketplace"


class AuthenticationMethod(Enum):
    """Методы аутентификации"""
    OAUTH2 = "oauth2"
    API_KEY = "api_key"
    COOKIE = "cookie"
    TOKEN = "token"


class JobStatus(Enum):
    """Статусы заказов"""
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    CLOSED = "closed"


@dataclass
class PlatformFieldMapping:
    """Маппинг полей платформы на внутреннюю структуру"""
    title: str = "title"
    description: str = "description"
    budget: str = "budget"
    currency: str = "currency"
    deadline: str = "deadline"
    skills: str = "skills"
    client_rating: str = "client_rating"
    job_type: str = "job_type"
    experience_level: str = "experience_level"
    location: str = "location"
    posted_date: str = "posted_date"
    proposals_count: str = "proposals_count"
    job_id: str = "id"


@dataclass
class PlatformConfig:
    """Конфигурация платформы"""
    name: str
    base_url: str
    platform_type: PlatformType
    auth_method: AuthenticationMethod
    api_version: str = "v1"

    # Эндпоинты API
    endpoints: Dict[str, str] = field(default_factory=dict)

    # Маппинг полей
    field_mapping: PlatformFieldMapping = field(default_factory=PlatformFieldMapping)

    # Параметры аутентификации
    auth_params: Dict[str, str] = field(default_factory=dict)

    # Заголовки по умолчанию
    default_headers: Dict[str, str] = field(default_factory=dict)

    # Параметры пагинации
    pagination: Dict[str, Any] = field(default_factory=lambda: {
        "param": "page",
        "size_param": "per_page",
        "default_size": 20
    })

    # Настройки парсинга HTML (если нет API)
    scraping: Dict[str, Any] = field(default_factory=dict)

    # Ограничения скорости
    rate_limit: Dict[str, int] = field(default_factory=lambda: {
        "requests_per_minute": 60,
        "requests_per_hour": 1000
    })


@dataclass
class Job:
    """Стандартизированная структура заказа"""
    id: str
    title: str
    description: str
    budget: Optional[float]
    currency: str = "USD"
    deadline: Optional[datetime] = None
    skills: List[str] = field(default_factory=list)
    client_rating: Optional[float] = None
    job_type: str = "fixed"
    experience_level: str = "intermediate"
    location: str = "anywhere"
    posted_date: Optional[datetime] = None
    proposals_count: Optional[int] = None
    platform: str = ""
    raw_data: Dict[str, Any] = field(default_factory=dict)
    url: Optional[str] = None


@dataclass
class Bid:
    """Структура предложения"""
    job_id: str
    cover_letter: str
    amount: float
    currency: str = "USD"
    delivery_time_days: int = 7
    hourly_rate: Optional[float] = None
    custom_fields: Dict[str, Any] = field(default_factory=dict)


class UniversalPlatformAdapter(PlatformBase):
    """
    Универсальный адаптер для поддержки любых фриланс-платформ
    """

    def __init__(self, config: PlatformConfig):
        super().__init__()
        self.config = config
        self.session: Optional[aiohttp.ClientSession] = None
        self.auth_token: Optional[str] = None
        self.last_request_time = 0
        self.request_count = 0
        self.multilingual = MultilingualSupport()

        logger.info(f"Инициализирован универсальный адаптер для платформы: {config.name}")

    async def initialize(self):
        """Инициализация адаптера"""
        # Создание HTTP сессии
        self.session = aiohttp.ClientSession(
            headers=self.config.default_headers,
            timeout=aiohttp.ClientTimeout(total=30)
        )

        # Аутентификация
        await self._authenticate()

        logger.info(f"Адаптер платформы '{self.config.name}' инициализирован")

    async def _authenticate(self):
        """Аутентификация на платформе"""
        auth_method = self.config.auth_method

        if auth_method == AuthenticationMethod.OAUTH2:
            await self._oauth2_auth()
        elif auth_method == AuthenticationMethod.API_KEY:
            await self._api_key_auth()
        elif auth_method == AuthenticationMethod.TOKEN:
            await self._token_auth()
        elif auth_method == AuthenticationMethod.COOKIE:
            await self._cookie_auth()

        logger.info(f"Аутентификация на платформе '{self.config.name}' успешна")

    async def _oauth2_auth(self):
        """OAuth2 аутентификация"""
        client_id = self.config.auth_params.get("client_id")
        client_secret = self.config.auth_params.get("client_secret")
        token_url = self.config.auth_params.get("token_url")
        refresh_token = self.config.auth_params.get("refresh_token")

        # Получение access token
        async with aiohttp.ClientSession() as session:
            data = {
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "refresh_token" if refresh_token else "client_credentials",
                "refresh_token": refresh_token
            }

            async with session.post(token_url, data=data) as response:
                if response.status == 200:
                    token_data = await response.json()
                    self.auth_token = token_data.get("access_token")

                    # Обновление заголовков
                    self.session.headers.update({
                        "Authorization": f"Bearer {self.auth_token}"
                    })
                else:
                    raise Exception(f"OAuth2 аутентификация не удалась: {response.status}")

    async def _api_key_auth(self):
        """Аутентификация по API ключу"""
        api_key = self.config.auth_params.get("api_key")
        api_key_header = self.config.auth_params.get("api_key_header", "X-API-Key")

        self.session.headers.update({
            api_key_header: api_key
        })

    async def _token_auth(self):
        """Аутентификация по токену"""
        token = self.config.auth_params.get("token")
        token_type = self.config.auth_params.get("token_type", "Bearer")

        self.session.headers.update({
            "Authorization": f"{token_type} {token}"
        })

    async def _cookie_auth(self):
        """Аутентификация по кукам"""
        cookies = self.config.auth_params.get("cookies", {})
        self.session.cookie_jar.update_cookies(cookies)

    async def _rate_limit_check(self):
        """Проверка лимитов запросов"""
        requests_per_minute = self.config.rate_limit.get("requests_per_minute", 60)
        current_time = asyncio.get_event_loop().time()

        # Простая реализация лимита (в продакшене использовать token bucket)
        if current_time - self.last_request_time < 60 / requests_per_minute:
            delay = 60 / requests_per_minute - (current_time - self.last_request_time)
            await asyncio.sleep(delay)

        self.last_request_time = current_time
        self.request_count += 1

    async def _make_request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        """Выполнение HTTP запроса с обработкой ошибок"""
        await self._rate_limit_check()

        url = f"{self.config.base_url}/{endpoint}"

        try:
            async with getattr(self.session, method.lower())(url, **kwargs) as response:
                if response.status == 200:
                    return await response.json()
                elif response.status == 401:
                    # Токен истек - повторная аутентификация
                    await self._authenticate()
                    return await self._make_request(method, endpoint, **kwargs)
                elif response.status == 429:
                    # Слишком много запросов
                    retry_after = int(response.headers.get("Retry-After", 60))
                    logger.warning(f"Достигнут лимит запросов. Ожидание {retry_after} секунд")
                    await asyncio.sleep(retry_after)
                    return await self._make_request(method, endpoint, **kwargs)
                else:
                    error_text = await response.text()
                    raise Exception(f"HTTP {response.status}: {error_text}")

        except aiohttp.ClientError as e:
            logger.error(f"Ошибка HTTP запроса: {str(e)}")
            raise
        except asyncio.TimeoutError:
            logger.error("Таймаут запроса")
            raise

    async def search_jobs(self,
                          keywords: Optional[List[str]] = None,
                          skills: Optional[List[str]] = None,
                          budget_min: Optional[float] = None,
                          budget_max: Optional[float] = None,
                          job_type: Optional[str] = None,
                          experience_level: Optional[str] = None,
                          page: int = 1,
                          per_page: int = 20) -> List[Job]:
        """
        Поиск заказов на платформе
        """
        endpoint = self.config.endpoints.get("search_jobs", "jobs/search")

        # Формирование параметров запроса
        params = {
            self.config.pagination["param"]: page,
            self.config.pagination["size_param"]: per_page
        }

        if keywords:
            params["keywords"] = ",".join(keywords)
        if skills:
            params["skills"] = ",".join(skills)
        if budget_min:
            params["budget_min"] = budget_min
        if budget_max:
            params["budget_max"] = budget_max
        if job_type:
            params["job_type"] = job_type
        if experience_level:
            params["experience_level"] = experience_level

        # Выполнение запроса
        response = await self._make_request("GET", endpoint, params=params)

        # Парсинг результатов
        jobs = []
        results = response.get("results", response.get("data", response.get("jobs", [])))

        for raw_job in results:
            job = self._parse_job(raw_job)
            jobs.append(job)

        return jobs

    def _parse_job(self, raw_job: Dict[str, Any]) -> Job:
        """Парсинг сырых данных заказа в стандартизированную структуру"""
        mapping = self.config.field_mapping

        def get_nested_value(data: Dict, path: str, default=None):
            """Получение значения по вложенному пути (например: 'client.rating')"""
            keys = path.split('.')
            value = data
            for key in keys:
                if isinstance(value, dict):
                    value = value.get(key, default)
                else:
                    return default
            return value

        # Извлечение полей по маппингу
        title = get_nested_value(raw_job, mapping.title, "")
        description = get_nested_value(raw_job, mapping.description, "")
        budget = get_nested_value(raw_job, mapping.budget)
        currency = get_nested_value(raw_job, mapping.currency, "USD")

        # Парсинг дедлайна
        deadline_raw = get_nested_value(raw_job, mapping.deadline)
        deadline = self._parse_date(deadline_raw) if deadline_raw else None

        # Парсинг навыков
        skills_raw = get_nested_value(raw_job, mapping.skills, [])
        skills = skills_raw if isinstance(skills_raw, list) else [skills_raw]

        # Парсинг рейтинга клиента
        client_rating = get_nested_value(raw_job, mapping.client_rating)
        if isinstance(client_rating, str):
            try:
                client_rating = float(client_rating)
            except:
                client_rating = None

        # Парсинг даты публикации
        posted_date_raw = get_nested_value(raw_job, mapping.posted_date)
        posted_date = self._parse_date(posted_date_raw) if posted_date_raw else None

        # Извлечение остальных полей
        job_type = get_nested_value(raw_job, mapping.job_type, "fixed")
        experience_level = get_nested_value(raw_job, mapping.experience_level, "intermediate")
        location = get_nested_value(raw_job, mapping.location, "anywhere")
        proposals_count = get_nested_value(raw_job, mapping.proposals_count)

        # Извлечение ID заказа
        job_id = get_nested_value(raw_job, mapping.job_id, "")

        # Формирование URL заказа
        job_url = None
        if job_id:
            job_url = f"{self.config.base_url}/jobs/{job_id}"

        return Job(
            id=str(job_id),
            title=str(title),
            description=str(description),
            budget=float(budget) if budget else None,
            currency=str(currency),
            deadline=deadline,
            skills=skills,
            client_rating=float(client_rating) if client_rating else None,
            job_type=str(job_type),
            experience_level=str(experience_level),
            location=str(location),
            posted_date=posted_date,
            proposals_count=int(proposals_count) if proposals_count else None,
            platform=self.config.name,
            raw_data=raw_job,
            url=job_url
        )

    def _parse_date(self, date_str: Any) -> Optional[datetime]:
        """Парсинг даты из различных форматов"""
        if date_str is None:
            return None

        if isinstance(date_str, datetime):
            return date_str

        if isinstance(date_str, (int, float)):
            # Unix timestamp
            return datetime.fromtimestamp(date_str)

        if isinstance(date_str, str):
            # Попытка различных форматов
            formats = [
                "%Y-%m-%d",
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%dT%H:%M:%S.%fZ",
                "%Y-%m-%dT%H:%M:%SZ",
                "%d.%m.%Y",
                "%d/%m/%Y",
                "%m/%d/%Y"
            ]

            for fmt in formats:
                try:
                    return datetime.strptime(date_str, fmt)
                except ValueError:
                    continue

        return None

    async def get_job_details(self, job_id: str) -> Optional[Job]:
        """Получение деталей заказа"""
        endpoint = self.config.endpoints.get("get_job", f"jobs/{job_id}")

        response = await self._make_request("GET", endpoint)
        raw_job = response.get("job", response.get("data", response))

        return self._parse_job(raw_job) if raw_job else None

    async def place_bid(self, bid: Bid) -> Dict[str, Any]:
        """Размещение предложения на заказ"""
        endpoint = self.config.endpoints.get("place_bid", f"jobs/{bid.job_id}/bids")

        # Формирование данных предложения
        bid_data = {
            "cover_letter": bid.cover_letter,
            "amount": bid.amount,
            "currency": bid.currency,
            "delivery_time_days": bid.delivery_time_days
        }

        # Добавление кастомных полей
        bid_data.update(bid.custom_fields)

        response = await self._make_request("POST", endpoint, json=bid_data)

        return {
            "success": True,
            "bid_id": response.get("id", response.get("bid_id")),
            "platform": self.config.name,
            "job_id": bid.job_id,
            "timestamp": datetime.now().isoformat()
        }

    async def get_my_bids(self, status: Optional[str] = None, page: int = 1) -> List[Dict[str, Any]]:
        """Получение моих предложений"""
        endpoint = self.config.endpoints.get("my_bids", "bids")

        params = {
            self.config.pagination["param"]: page
        }

        if status:
            params["status"] = status

        response = await self._make_request("GET", endpoint, params=params)

        return response.get("bids", response.get("data", []))

    async def get_job_proposals(self, job_id: str) -> List[Dict[str, Any]]:
        """Получение предложений по заказу"""
        endpoint = self.config.endpoints.get("job_proposals", f"jobs/{job_id}/proposals")

        response = await self._make_request("GET", endpoint)

        return response.get("proposals", response.get("data", []))

    async def scrape_job_from_url(self, url: str) -> Optional[Job]:
        """Парсинг заказа из HTML страницы (если нет API)"""
        if not self.config.scraping:
            raise Exception("Scraping не настроен для этой платформы")

        try:
            async with self.session.get(url) as response:
                html = await response.text()

            soup = BeautifulSoup(html, 'html.parser')

            # Извлечение данных по селекторам из конфигурации
            selectors = self.config.scraping.get("selectors", {})

            data = {}
            for field, selector in selectors.items():
                element = soup.select_one(selector)
                if element:
                    data[field] = element.get_text(strip=True)

            # Преобразование в стандартную структуру
            return self._parse_job(data)

        except Exception as e:
            logger.error(f"Ошибка парсинга страницы {url}: {str(e)}")
            return None

    async def close(self):
        """Закрытие соединения"""
        if self.session:
            await self.session.close()
            logger.info(f"Соединение с платформой '{self.config.name}' закрыто")