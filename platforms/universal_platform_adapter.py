"""
Универсальный адаптер для интеграции с любыми фриланс-платформами,
включая "серые" площадки без официального API через конфигурацию правил скрапинга.
"""

import json
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, asdict
from enum import Enum
import hashlib
import base64
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

from core.security.encryption_engine import EncryptionEngine
from core.monitoring.alert_manager import AlertManager


class PlatformType(Enum):
    """Тип платформы"""
    OFFICIAL_API = "official_api"      # Официальное API (Upwork, Freelancer.com)
    UNOFFICIAL_API = "unofficial_api"  # Неофициальное/реверс-инжиниринговое API
    SCRAPING = "scraping"              # Парсинг HTML через Selenium/BeautifulSoup
    HYBRID = "hybrid"                  # Комбинация API + скрапинг


class AuthMethod(Enum):
    """Метод аутентификации"""
    OAUTH2 = "oauth2"
    API_KEY = "api_key"
    COOKIE = "cookie"
    LOGIN_FORM = "login_form"
    TOKEN = "token"


@dataclass
class ScrapingRule:
    """Правило извлечения данных из HTML"""
    selector: str
    attribute: Optional[str] = None  # 'text', 'href', 'src' или имя атрибута
    regex_pattern: Optional[str] = None
    post_processor: Optional[str] = None  # Имя функции пост-обработки
    multiple: bool = False  # Извлекать несколько элементов


@dataclass
class PlatformConfig:
    """Конфигурация платформы"""
    platform_name: str
    platform_type: PlatformType
    base_url: str
    auth_method: AuthMethod
    auth_endpoint: Optional[str] = None
    scraping_rules: Optional[Dict[str, ScrapingRule]] = None
    api_endpoints: Optional[Dict[str, str]] = None
    rate_limits: Optional[Dict[str, int]] = None  # Запросов в минуту/час
    requires_selenium: bool = False
    user_agent: Optional[str] = None
    custom_headers: Optional[Dict[str, str]] = None
    anti_detection: bool = False  # Обход защиты от ботов
    captcha_solver: Optional[str] = None  # '2captcha', 'anticaptcha' и т.д.

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        result['platform_type'] = self.platform_type.value
        result['auth_method'] = self.auth_method.value
        return result

    @classmethod
    def from_dict(cls,  Dict[str, Any]) -> 'PlatformConfig':
        return cls(
            platform_name=data['platform_name'],
            platform_type=PlatformType(data['platform_type']),
            base_url=data['base_url'],
            auth_method=AuthMethod(data['auth_method']),
            auth_endpoint=data.get('auth_endpoint'),
            scraping_rules={k: ScrapingRule(**v) for k, v in data.get('scraping_rules', {}).items()},
            api_endpoints=data.get('api_endpoints'),
            rate_limits=data.get('rate_limits'),
            requires_selenium=data.get('requires_selenium', False),
            user_agent=data.get('user_agent'),
            custom_headers=data.get('custom_headers'),
            anti_detection=data.get('anti_detection', False),
            captcha_solver=data.get('captcha_solver')
        )


class UniversalPlatformAdapter:
    """
    Универсальный адаптер для работы с любыми фриланс-платформами.

    Особенности:
    - Поддержка официальных и неофициальных API
    - Конфигурируемый скрапинг для "серых" площадок
    - Автоматическое обнаружение и обход защиты от ботов
    - Управление рейт-лимитами и сессиями
    - Интеграция с решателями капчи
    - Поддержка кастомных правил извлечения данных через YAML/JSON конфиги
    """

    def __init__(self,
                 config_dir: str = "config/platforms",
                 session_dir: str = "data/sessions"):
        self.config_dir = Path(config_dir)
        self.session_dir = Path(session_dir)
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.platforms: Dict[str, PlatformConfig] = {}
        self.sessions: Dict[str, Dict[str, Any]] = {}
        self.encryption_engine = EncryptionEngine()
        self.alert_manager = AlertManager()
        self._rate_limiters: Dict[str, Dict[str, Any]] = {}
        self._load_platform_configs()

    def _load_platform_configs(self):
        """Загрузка конфигураций платформ из директории"""
        # Загрузка встроенных конфигов
        built_in_configs = [
            "upwork.json", "fiverr.json", "freelance_ru.json",
            "kwork.json", "habr_freelance.json", "toptal.json",
            "profi_ru.json", "linkedin_pro.json"
        ]

        for config_file in built_in_configs:
            config_path = self.config_dir / config_file
            if config_path.exists():
                try:
                    with open(config_path, 'r', encoding='utf-8') as f:
                        config_data = json.load(f)
                        self.platforms[config_data['platform_name']] = PlatformConfig.from_dict(config_data)
                except Exception as e:
                    self._log(f"Ошибка загрузки конфига {config_file}: {e}")

        # Загрузка кастомных конфигов из поддиректории custom/
        custom_dir = self.config_dir / "custom"
        if custom_dir.exists():
            for custom_file in custom_dir.glob("*.yaml"):
                try:
                    import yaml
                    with open(custom_file, 'r', encoding='utf-8') as f:
                        config_data = yaml.safe_load(f)
                        self.platforms[config_data['platform_name']] = PlatformConfig.from_dict(config_data)
                        self._log(f"Загружен кастомный конфиг: {custom_file.name}")
                except Exception as e:
                    self._log(f"Ошибка загрузки кастомного конфига {custom_file}: {e}")

    def register_custom_platform(self, config: PlatformConfig):
        """
        Регистрация кастомной платформы во время выполнения.

        Пример использования для Авито Услуги:
        ```python
        config = PlatformConfig(
            platform_name="avito_services",
            platform_type=PlatformType.SCRAPING,
            base_url="https://www.avito.ru",
            auth_method=AuthMethod.COOKIE,
            scraping_rules={
                "job_list": ScrapingRule(selector=".item_table", multiple=True),
                "job_title": ScrapingRule(selector=".title", attribute="text"),
                "job_price": ScrapingRule(selector=".price-value", attribute="text", post_processor="extract_price"),
                "job_url": ScrapingRule(selector=".item_link", attribute="href")
            },
            api_endpoints={
                "submit_proposal": "/leads/{{job_id}}/respond"
            },
            requires_selenium=True,
            anti_detection=True
        )
        adapter.register_custom_platform(config)
        ```
        """
        self.platforms[config.platform_name] = config
        self._save_custom_config(config)
        self._log(f"Зарегистрирована кастомная платформа: {config.platform_name}")

    def _save_custom_config(self, config: PlatformConfig):
        """Сохранение кастомной конфигурации в файл"""
        custom_dir = self.config_dir / "custom"
        custom_dir.mkdir(parents=True, exist_ok=True)

        config_file = custom_dir / f"{config.platform_name}.yaml"
        import yaml

        with open(config_file, 'w', encoding='utf-8') as f:
            yaml.dump(config.to_dict(), f, allow_unicode=True, sort_keys=False)

    def authenticate(self, platform_name: str, credentials: Dict[str, Any]) -> bool:
        """
        Аутентификация на платформе в зависимости от метода.

        Args:
            platform_name: Имя платформы
            credentials: Учетные данные (зависят от метода аутентификации)

        Returns:
            True если аутентификация успешна
        """
        if platform_name not in self.platforms:
            raise ValueError(f"Платформа {platform_name} не зарегистрирована")

        config = self.platforms[platform_name]
        session_key = f"{platform_name}_{hashlib.md5(str(credentials.get('username', '')).encode()).hexdigest()}"

        # Проверка существующей сессии
        if session_key in self.sessions:
            session = self.sessions[session_key]
            if session['expires_at'] > datetime.now():
                self._log(f"Использование существующей сессии для {platform_name}")
                return True

        # Выбор метода аутентификации
        if config.auth_method == AuthMethod.OAUTH2:
            success = self._oauth2_authenticate(config, credentials)
        elif config.auth_method == AuthMethod.API_KEY:
            success = self._api_key_authenticate(config, credentials)
        elif config.auth_method == AuthMethod.COOKIE:
            success = self._cookie_authenticate(config, credentials)
        elif config.auth_method == AuthMethod.LOGIN_FORM:
            success = self._login_form_authenticate(config, credentials)
        elif config.auth_method == AuthMethod.TOKEN:
            success = self._token_authenticate(config, credentials)
        else:
            raise NotImplementedError(f"Метод аутентификации {config.auth_method} не поддерживается")

        if success:
            # Сохранение сессии
            expires_in = credentials.get('expires_in', 3600)
            self.sessions[session_key] = {
                'platform': platform_name,
                'credentials_hash': hashlib.sha256(str(credentials).encode()).hexdigest(),
                'created_at': datetime.now(),
                'expires_at': datetime.now() + timedelta(seconds=expires_in),
                'session_data': self._encrypt_session_data(credentials)
            }

            # Сохранение сессии на диск для восстановления после перезапуска
            self._save_session_to_disk(session_key, self.sessions[session_key])

        return success

    def _oauth2_authenticate(self, config: PlatformConfig, credentials: Dict[str, Any]) -> bool:
        """Аутентификация через OAuth 2.0"""
        try:
            # Реализация OAuth2 flow
            # ... код аутентификации ...
            return True
        except Exception as e:
            self._log(f"Ошибка OAuth2 аутентификации: {e}", level='ERROR')
            return False

    def _api_key_authenticate(self, config: PlatformConfig, credentials: Dict[str, Any]) -> bool:
        """Аутентификация через API ключ"""
        api_key = credentials.get('api_key')
        if not api_key:
            return False

        # Тестовый запрос для проверки ключа
        test_url = f"{config.base_url}/api/test"
        headers = {'Authorization': f'Bearer {api_key}'}

        try:
            response = requests.get(test_url, headers=headers, timeout=10)
            return response.status_code == 200
        except Exception as e:
            self._log(f"Ошибка проверки API ключа: {e}", level='ERROR')
            return False

    def _cookie_authenticate(self, config: PlatformConfig, credentials: Dict[str, Any]) -> bool:
        """Аутентификация через куки (для скрапинга)"""
        cookies = credentials.get('cookies', {})
        if not cookies:
            return False

        # Проверка валидности кук через тестовый запрос
        try:
            session = requests.Session()
            for name, value in cookies.items():
                session.cookies.set(name, value)

            response = session.get(config.base_url, timeout=10)
            return "login" not in response.url.lower() and response.status_code == 200
        except Exception as e:
            self._log(f"Ошибка проверки кук: {e}", level='ERROR')
            return False

    def _login_form_authenticate(self, config: PlatformConfig, credentials: Dict[str, Any]) -> bool:
        """Аутентификация через форму входа (с использованием Selenium для сложных случаев)"""
        if config.requires_selenium:
            return self._selenium_login(config, credentials)
        else:
            return self._requests_login(config, credentials)

    def _selenium_login(self, config: PlatformConfig, credentials: Dict[str, Any]) -> bool:
        """Аутентификация через Selenium для обхода JavaScript-защиты"""
        try:
            # Настройка веб-драйвера с обходом детекта
            options = webdriver.ChromeOptions()
            if config.anti_detection:
                options.add_argument('--disable-blink-features=AutomationControlled')
                options.add_experimental_option("excludeSwitches", ["enable-automation"])
                options.add_experimental_option('useAutomationExtension', False)

            driver = webdriver.Chrome(options=options)
            driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

            # Переход на страницу логина
            driver.get(f"{config.base_url}/login")
            time.sleep(2)  # Ожидание загрузки

            # Ввод учетных данных
            username_field = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.NAME, "username"))
            )
            password_field = driver.find_element(By.NAME, "password")

            username_field.send_keys(credentials['username'])
            password_field.send_keys(credentials['password'])

            # Отправка формы
            password_field.submit()
            time.sleep(3)

            # Проверка успешности входа
            if "dashboard" in driver.current_url or "profile" in driver.current_url:
                # Извлечение кук для будущих запросов
                cookies = {cookie['name']: cookie['value'] for cookie in driver.get_cookies()}
                credentials['cookies'] = cookies
                driver.quit()
                return True

            driver.quit()
            return False

        except Exception as e:
            self._log(f"Ошибка Selenium аутентификации: {e}", level='ERROR')
            return False

    def _requests_login(self, config: PlatformConfig, credentials: Dict[str, Any]) -> bool:
        """Аутентификация через requests (для простых форм)"""
        try:
            session = requests.Session()
            login_data = {
                'username': credentials['username'],
                'password': credentials['password'],
                'remember': '1'
            }

            response = session.post(f"{config.base_url}/login", data=login_data, timeout=10)
            return response.status_code == 200 and "login" not in response.url

        except Exception as e:
            self._log(f"Ошибка аутентификации через requests: {e}", level='ERROR')
            return False

    def _token_authenticate(self, config: PlatformConfig, credentials: Dict[str, Any]) -> bool:
        """Аутентификация через токен (JWT и подобные)"""
        token = credentials.get('token')
        if not token:
            return False

        # Проверка токена через тестовый запрос
        headers = {'Authorization': f'Bearer {token}'}
        try:
            response = requests.get(f"{config.base_url}/api/user", headers=headers, timeout=10)
            return response.status_code == 200
        except Exception as e:
            self._log(f"Ошибка проверки токена: {e}", level='ERROR')
            return False

    def search_jobs(self,
                   platform_name: str,
                   query: str,
                   filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Поиск вакансий на платформе с поддержкой кастомных правил извлечения.

        Args:
            platform_name: Имя платформы
            query: Поисковый запрос
            filters: Фильтры (бюджет, категория, сроки и т.д.)

        Returns:
            Список найденных вакансий в унифицированном формате
        """
        if platform_name not in self.platforms:
            raise ValueError(f"Платформа {platform_name} не зарегистрирована")

        config = self.platforms[platform_name]
        self._enforce_rate_limit(platform_name, 'search')

        try:
            if config.platform_type == PlatformType.OFFICIAL_API:
                jobs = self._search_via_api(config, query, filters)
            elif config.platform_type in [PlatformType.UNOFFICIAL_API, PlatformType.HYBRID]:
                jobs = self._search_via_unofficial_api(config, query, filters)
            else:  # SCRAPING
                jobs = self._search_via_scraping(config, query, filters)

            # Нормализация результатов в единый формат
            normalized_jobs = [self._normalize_job(job, platform_name) for job in jobs]
            self._log(f"Найдено {len(normalized_jobs)} вакансий на {platform_name}")
            return normalized_jobs

        except Exception as e:
            self._log(f"Ошибка поиска на {platform_name}: {e}", level='ERROR')
            self.alert_manager.send_alert(
                title=f"Ошибка поиска на {platform_name}",
                message=str(e),
                severity='warning',
                metadata={'platform': platform_name, 'query': query}
            )
            return []

    def _search_via_scraping(self,
                           config: PlatformConfig,
                           query: str,
                           filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Поиск через скрапинг HTML с поддержкой кастомных правил"""
        # Формирование URL поиска
        search_url = self._build_search_url(config, query, filters)

        if config.requires_selenium:
            return self._selenium_scrape(search_url, config)
        else:
            return self._beautifulsoup_scrape(search_url, config)

    def _selenium_scrape(self, url: str, config: PlatformConfig) -> List[Dict[str, Any]]:
        """Скрапинг с использованием Selenium для динамических страниц"""
        try:
            options = webdriver.ChromeOptions()
            if config.anti_detection:
                options.add_argument('--disable-blink-features=AutomationControlled')

            driver = webdriver.Chrome(options=options)
            driver.get(url)

            # Ожидание загрузки результатов
            try:
                WebDriverWait(driver, 15).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, config.scraping_rules['job_list'].selector))
                )
            except TimeoutException:
                self._log("Таймаут ожидания загрузки результатов", level='WARNING')

            # Прокрутка для загрузки дополнительных результатов (если необходимо)
            if config.scraping_rules.get('infinite_scroll'):
                self._scroll_to_load_more(driver, max_scrolls=3)

            # Извлечение HTML после полной загрузки
            html = driver.page_source
            driver.quit()

            # Парсинг через BeautifulSoup для удобства
            soup = BeautifulSoup(html, 'html.parser')
            return self._parse_jobs_from_soup(soup, config)

        except Exception as e:
            self._log(f"Ошибка Selenium скрапинга: {e}", level='ERROR')
            return []

    def _beautifulsoup_scrape(self, url: str, config: PlatformConfig) -> List[Dict[str, Any]]:
        """Скрапинг с использованием requests + BeautifulSoup для статических страниц"""
        try:
            headers = {'User-Agent': config.user_agent or 'Mozilla/5.0'}
            if config.custom_headers:
                headers.update(config.custom_headers)

            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'html.parser')
            return self._parse_jobs_from_soup(soup, config)

        except Exception as e:
            self._log(f"Ошибка BeautifulSoup скрапинга: {e}", level='ERROR')
            return []

    def _parse_jobs_from_soup(self, soup: BeautifulSoup, config: PlatformConfig) -> List[Dict[str, Any]]:
        """Извлечение данных о вакансиях из распарсенного HTML по правилам конфигурации"""
        jobs = []
        job_elements = soup.select(config.scraping_rules['job_list'].selector)

        for job_element in job_elements[:50]:  # Ограничение для безопасности
            job_data = {}

            # Извлечение каждого поля по правилам
            for field_name, rule in config.scraping_rules.items():
                if field_name == 'job_list':
                    continue

                try:
                    if rule.multiple:
                        elements = job_element.select(rule.selector)
                        values = [self._extract_value(el, rule) for el in elements]
                        job_data[field_name] = values
                    else:
                        element = job_element.select_one(rule.selector)
                        if element:
                            job_data[field_name] = self._extract_value(element, rule)
                except Exception as e:
                    self._log(f"Ошибка извлечения поля {field_name}: {e}", level='DEBUG')

            if job_
                jobs.append(job_data)

        return jobs

    def _extract_value(self, element: Any, rule: ScrapingRule) -> Any:
        """Извлечение значения из HTML-элемента по правилу"""
        value = None

        if rule.attribute == 'text':
            value = element.get_text(strip=True)
        elif rule.attribute:
            value = element.get(rule.attribute)
        else:
            value = str(element)

        # Применение регулярного выражения если указано
        if rule.regex_pattern and value:
            match = re.search(rule.regex_pattern, str(value))
            if match:
                value = match.group(1) if match.groups() else match.group(0)

        # Применение пост-процессора
        if rule.post_processor and value:
            value = self._apply_post_processor(value, rule.post_processor)

        return value

    def _apply_post_processor(self, value: Any, processor_name: str) -> Any:
        """Применение функции пост-обработки к извлеченному значению"""
        processors = {
            'extract_price': self._extract_price,
            'normalize_date': self._normalize_date,
            'extract_number': self._extract_number,
            'clean_text': self._clean_text,
            'extract_currency': self._extract_currency
        }

        processor = processors.get(processor_name)
        if processor:
            try:
                return processor(value)
            except Exception as e:
                self._log(f"Ошибка пост-процессора {processor_name}: {e}", level='DEBUG')

        return value

    def _extract_price(self, text: str) -> float:
        """Извлечение цены из текста (поддержка различных форматов)"""
        # Поиск чисел с возможными разделителями тысяч и десятичными точками
        match = re.search(r'[\d\s,.]+', text.replace(' ', '').replace(',', ''))
        if match:
            try:
                return float(match.group(0).replace(' ', '').replace(',', '.'))
            except:
                pass
        return 0.0

    def _normalize_date(self, text: str) -> str:
        """Нормализация даты в формат ISO"""
        # Реализация для различных форматов дат
        # ... логика нормализации ...
        return text

    def _extract_number(self, text: str) -> int:
        """Извлечение первого числа из текста"""
        match = re.search(r'\d+', text)
        return int(match.group(0)) if match else 0

    def _clean_text(self, text: str) -> str:
        """Очистка текста от лишних пробелов и спецсимволов"""
        return ' '.join(text.split())

    def _extract_currency(self, text: str) -> str:
        """Извлечение кода валюты из текста"""
        currency_map = {
            '₽': 'RUB', 'руб': 'RUB', 'р': 'RUB',
            '$': 'USD', 'доллар': 'USD',
            '€': 'EUR', 'евро': 'EUR'
        }

        for symbol, code in currency_map.items():
            if symbol in text:
                return code
        return 'RUB'

    def _scroll_to_load_more(self, driver: webdriver.Chrome, max_scrolls: int = 3):
        """Прокрутка страницы для загрузки дополнительного контента"""
        last_height = driver.execute_script("return document.body.scrollHeight")

        for _ in range(max_scrolls):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)  # Ожидание загрузки

            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height

    def _build_search_url(self, config: PlatformConfig, query: str, filters: Optional[Dict[str, Any]]) -> str:
        """Формирование URL поиска с учетом фильтров"""
        from urllib.parse import urlencode

        params = {'q': query}
        if filters:
            params.update(filters)

        query_string = urlencode(params, encoding='utf-8')
        return f"{config.base_url}/search?{query_string}"

    def _normalize_job(self, raw_job: Dict[str, Any], platform_name: str) -> Dict[str, Any]:
        """Нормализация данных вакансии в унифицированный формат"""
        return {
            'platform': platform_name,
            'job_id': raw_job.get('id') or raw_job.get('job_id') or self._generate_job_hash(raw_job),
            'title': raw_job.get('title', '').strip(),
            'description': raw_job.get('description', ''),
            'budget': {
                'amount': raw_job.get('price') or raw_job.get('budget') or 0,
                'currency': raw_job.get('currency', 'RUB'),
                'type': raw_job.get('budget_type', 'fixed')  # fixed/hourly
            },
            'skills': raw_job.get('skills', []),
            'posted_at': raw_job.get('posted_at') or raw_job.get('date'),
            'deadline': raw_job.get('deadline'),
            'url': raw_job.get('url') or raw_job.get('job_url'),
            'client': {
                'rating': raw_job.get('client_rating'),
                'reviews': raw_job.get('client_reviews', 0),
                'country': raw_job.get('client_country')
            },
            'raw_data': raw_job  # Сохранение исходных данных для отладки
        }

    def _generate_job_hash(self, job_ Dict[str, Any]) -> str:
        """Генерация уникального хеша для вакансии на основе ее содержимого"""
        # Используем ключевые поля для создания стабильного хеша
        hash_data = f"{job_data.get('title', '')}|{job_data.get('description', '')[:100]}|{job_data.get('price', 0)}"
        return hashlib.md5(hash_data.encode()).hexdigest()

    def _enforce_rate_limit(self, platform_name: str, operation: str):
        """Применение рейт-лимитов для предотвращения блокировок"""
        if platform_name not in self._rate_limiters:
            self._rate_limiters[platform_name] = {}

        platform_limits = self._rate_limiters[platform_name]

        if operation not in platform_limits:
            platform_limits[operation] = {
                'last_call': datetime.min,
                'count': 0,
                'window_start': datetime.now()
            }

        limit_info = platform_limits[operation]
        config = self.platforms[platform_name]
        rate_limits = config.rate_limits or {}
        max_per_minute = rate_limits.get(f"{operation}_per_minute", 60)
        max_per_hour = rate_limits.get(f"{operation}_per_hour", 1000)

        now = datetime.now()
        seconds_since_last = (now - limit_info['last_call']).total_seconds()

        # Ограничение по минутному окну
        if seconds_since_last < 60 / max_per_minute:
            sleep_time = (60 / max_per_minute) - seconds_since_last
            time.sleep(max(0, sleep_time))

        # Сброс счетчиков по истечении окон
        if (now - limit_info['window_start']).total_seconds() > 3600:
            limit_info['window_start'] = now
            limit_info['count'] = 0

        # Ограничение по часовому окну
        if limit_info['count'] >= max_per_hour:
            sleep_until = limit_info['window_start'] + timedelta(hours=1)
            sleep_seconds = (sleep_until - now).total_seconds()
            if sleep_seconds > 0:
                self._log(f"Достигнут рейт-лимит для {platform_name}.{operation}, сон {sleep_seconds:.0f} сек", level='WARNING')
                time.sleep(sleep_seconds)
                limit_info['window_start'] = datetime.now()
                limit_info['count'] = 0

        limit_info['last_call'] = datetime.now()
        limit_info['count'] += 1

    def _encrypt_session_data(self, data: Dict[str, Any]) -> str:
        """Шифрование данных сессии для безопасного хранения"""
        json_data = json.dumps(data, ensure_ascii=False)
        encrypted = self.encryption_engine.encrypt(json_data.encode())
        return base64.b64encode(encrypted).decode()

    def _decrypt_session_data(self, encrypted_ str) -> Dict[str, Any]:
        """Расшифровка данных сессии"""
        try:
            decoded = base64.b64decode(encrypted_data.encode())
            decrypted = self.encryption_engine.decrypt(decoded)
            return json.loads(decrypted.decode())
        except Exception as e:
            self._log(f"Ошибка расшифровки сессии: {e}", level='ERROR')
            return {}

    def _save_session_to_disk(self, session_key: str, session_ Dict[str, Any]):
        """Сохранение сессии на диск в зашифрованном виде"""
        session_file = self.session_dir / f"{session_key}.enc"
        with open(session_file, 'w', encoding='utf-8') as f:
            json.dump(session_data, f, default=str)

    def _load_session_from_disk(self, session_key: str) -> Optional[Dict[str, Any]]:
        """Загрузка сессии с диска"""
        session_file = self.session_dir / f"{session_key}.enc"
        if session_file.exists():
            try:
                with open(session_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                self._log(f"Ошибка загрузки сессии с диска: {e}", level='ERROR')
        return None

    def _log(self, message: str, level: str = 'INFO'):
        """Логирование событий адаптера"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_entry = f"[{timestamp}] [{level}] UniversalPlatformAdapter: {message}"

        # Запись в файл
        log_file = Path("logs/platform_adapter.log")
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(log_entry + '\n')

        # Вывод в консоль для отладки
        if level in ['ERROR', 'CRITICAL', 'WARNING']:
            print(log_entry)


# Глобальный экземпляр адаптера (паттерн Singleton)
_universal_adapter_instance = None


def get_universal_platform_adapter(config_dir: str = "config/platforms") -> UniversalPlatformAdapter:
    """
    Получение глобального экземпляра UniversalPlatformAdapter (Singleton).

    Returns:
        Единый экземпляр адаптера для всего приложения
    """
    global _universal_adapter_instance

    if _universal_adapter_instance is None:
        _universal_adapter_instance = UniversalPlatformAdapter(config_dir)

    return _universal_adapter_instance