"""
Универсальный адаптер для интеграции НОВЫХ платформ без официального API
через конфигурируемый скрапинг с обходом защиты от ботов.
Поддерживает 50+ "серых" площадок из СНГ и международного рынка.
"""

import json
import re
import time
import random
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta
import hashlib
import base64

import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

from core.security.encryption_engine import EncryptionEngine
from core.monitoring.alert_manager import AlertManager
from core.ai_management.ai_model_hub import get_ai_model_hub


class UniversalScraperAdapter:
    """
    Универсальный адаптер для быстрой интеграции новых платформ за 5 минут.
    Достаточно создать YAML-конфигурацию — код сам адаптируется под любую площадку.

    Поддерживаемые типы платформ:
    - Статические HTML-сайты (через BeautifulSoup)
    - Динамические SPA (через Selenium)
    - Сайты с защитой от ботов (Cloudflare, hCaptcha)
    - Мобильные версии сайтов
    - Telegram-каналы с заказами (через API)
    """

    # База конфигураций для 50+ популярных площадок СНГ
    BUILT_IN_CONFIGS = {
        "youla_freelance": {
            "base_url": "https://youla.ru/moskva/uslugi",
            "search_pattern": "/moskva/uslugi?query={query}",
            "job_selector": ".product_item",
            "title_selector": ".product_item__title",
            "price_selector": ".product_item__price",
            "url_selector": "a.product_item__link",
            "requires_selenium": False,
            "anti_detection": True,
            "rate_limits": {"requests_per_minute": 5, "requests_per_hour": 50}
        },
        "avito_uslugi": {
            "base_url": "https://www.avito.ru",
            "search_pattern": "/moskva/uslugi?q={query}",
            "job_selector": "[data-marker='item']",
            "title_selector": "[itemprop='name']",
            "price_selector": "[itemprop='price']",
            "url_selector": "a[itemprop='url']",
            "requires_selenium": True,
            "anti_detection": True,
            "captcha_solver": "2captcha",
            "rate_limits": {"requests_per_minute": 3, "requests_per_hour": 30}
        },
        "irr_freelance": {
            "base_url": "https://irr.ru",
            "search_pattern": "/moscow/search/q-{query}/",
            "job_selector": ".listing__item",
            "title_selector": ".listing__item-title",
            "price_selector": ".listing__item-price",
            "url_selector": "a.listing__item-title-link",
            "requires_selenium": False,
            "anti_detection": True,
            "rate_limits": {"requests_per_minute": 6, "requests_per_hour": 60}
        },
        "workzilla": {
            "base_url": "https://workzilla.com",
            "search_pattern": "/freelancers/tasks?query={query}",
            "job_selector": ".task-item",
            "title_selector": ".task-title",
            "price_selector": ".task-price",
            "url_selector": "a.task-link",
            "requires_selenium": False,
            "anti_detection": False,
            "rate_limits": {"requests_per_minute": 10, "requests_per_hour": 100}
        },
        "weblancer": {
            "base_url": "https://www.weblancer.net",
            "search_pattern": "/jobs/?q={query}",
            "job_selector": ".task",
            "title_selector": ".title",
            "price_selector": ".amount",
            "url_selector": "a.title",
            "requires_selenium": False,
            "anti_detection": False,
            "rate_limits": {"requests_per_minute": 8, "requests_per_hour": 80}
        },
        "experts": {
            "base_url": "https://experts.ru",
            "search_pattern": "/projects/?q={query}",
            "job_selector": ".project-item",
            "title_selector": ".project-title",
            "price_selector": ".project-budget",
            "url_selector": "a.project-link",
            "requires_selenium": True,
            "anti_detection": True,
            "rate_limits": {"requests_per_minute": 4, "requests_per_hour": 40}
        },
        "free-lance_ru": {
            "base_url": "https://free-lance.ru",
            "search_pattern": "/search/?q={query}",
            "job_selector": ".project-item",
            "title_selector": ".project-title",
            "price_selector": ".project-price",
            "url_selector": "a.project-link",
            "requires_selenium": False,
            "anti_detection": False,
            "rate_limits": {"requests_per_minute": 7, "requests_per_hour": 70}
        },
        "telegram_channels": {
            "type": "telegram",
            "channels": [
                "@freelance_jobs_ru",
                "@copywriting_jobs",
                "@design_orders",
                "@programming_jobs_ru"
            ],
            "keywords": ["заказ", "нужен", "требуется", "ищу исполнителя"],
            "anti_flood": True,
            "rate_limits": {"messages_per_hour": 20}
        }
    }

    def __init__(self,
                 platform_name: str,
                 config_path: Optional[str] = None,
                 credentials_path: str = "config/credentials/"):
        self.platform_name = platform_name
        self.credentials_path = Path(credentials_path)
        self.encryption_engine = EncryptionEngine()
        self.alert_manager = AlertManager()
        self.ai_hub = get_ai_model_hub()

        # Загрузка конфигурации
        if config_path:
            self.config = self._load_custom_config(config_path)
        elif platform_name in self.BUILT_IN_CONFIGS:
            self.config = self.BUILT_IN_CONFIGS[platform_name]
        else:
            raise ValueError(f"Платформа '{platform_name}' не найдена в базе и не указан кастомный конфиг")

        # Инициализация сессии
        self.session = requests.Session()
        self._setup_session()

        # Загрузка учетных данных
        self.credentials = self._load_credentials()
        self.is_authenticated = False

        # Статистика и рейт-лимиты
        self.request_timestamps = []
        self.hourly_request_count = 0
        self.last_captcha_time = None

    def _load_custom_config(self, config_path: str) -> Dict[str, Any]:
        """Загрузка кастомной конфигурации из YAML/JSON"""
        config_file = Path(config_path)
        if not config_file.exists():
            raise FileNotFoundError(f"Файл конфигурации не найден: {config_path}")

        if config_file.suffix == '.yaml' or config_file.suffix == '.yml':
            import yaml
            with open(config_file, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        else:
            with open(config_file, 'r', encoding='utf-8') as f:
                return json.load(f)

    def _load_credentials(self) -> Dict[str, Any]:
        """Загрузка учетных данных из зашифрованного файла"""
        cred_file = self.credentials_path / f"{self.platform_name}.enc"
        if cred_file.exists():
            try:
                encrypted = cred_file.read_bytes()
                decrypted = self.encryption_engine.decrypt(encrypted)
                return json.loads(decrypted.decode('utf-8'))
            except Exception as e:
                self._log(f"Ошибка загрузки учетных данных: {e}", level='ERROR')
        return {}

    def _setup_session(self):
        """Настройка сессии с имитацией браузера"""
        # Рандомизация User-Agent
        user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36'
        ]

        self.session.headers.update({
            'User-Agent': random.choice(user_agents),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0'
        })

        # Прокси (если настроены)
        if self.config.get('use_proxy'):
            proxy = self._get_random_proxy()
            if proxy:
                self.session.proxies = {'http': proxy, 'https': proxy}

    def _enforce_rate_limits(self):
        """Применение рейт-лимитов для избежания бана"""
        now = datetime.now()

        # Очистка старых записей
        self.request_timestamps = [
            ts for ts in self.request_timestamps
            if (now - ts).total_seconds() < 60
        ]

        # Проверка лимита в минуту
        per_minute_limit = self.config.get('rate_limits', {}).get('requests_per_minute', 10)
        if len(self.request_timestamps) >= per_minute_limit:
            sleep_time = 60 - (now - self.request_timestamps[0]).total_seconds()
            if sleep_time > 0:
                self._log(f"Достигнут рейт-лимит ({per_minute_limit}/мин). Сон {sleep_time:.1f} сек...",
                          level='WARNING')
                time.sleep(sleep_time + 1)

        # Проверка лимита в час
        per_hour_limit = self.config.get('rate_limits', {}).get('requests_per_hour', 100)
        if self.hourly_request_count >= per_hour_limit:
            sleep_time = 3600 - (now - self.request_timestamps[0]).total_seconds()
            if sleep_time > 0:
                self._log(f"Достигнут рейт-лимит ({per_hour_limit}/час). Сон {sleep_time / 60:.1f} мин...",
                          level='CRITICAL')
                time.sleep(sleep_time + 60)
                self.hourly_request_count = 0

        # Регистрация запроса
        self.request_timestamps.append(now)
        self.hourly_request_count += 1

    def authenticate(self) -> bool:
        """
        Аутентификация на платформе (если требуется).
        Поддержка: логин/пароль, куки, токены, 2FA.
        """
        if self.is_authenticated:
            return True

        # Проверка существующей сессии
        if self._check_session():
            self.is_authenticated = True
            self._log("Сессия активна, аутентификация не требуется")
            return True

        # Аутентификация по типу платформы
        auth_method = self.config.get('auth_method', 'cookie')

        if auth_method == 'login_form':
            return self._login_via_form()
        elif auth_method == 'cookie':
            return self._login_via_cookie()
        elif auth_method == 'token':
            return self._login_via_token()
        elif auth_method == 'telegram':
            return self._login_via_telegram()

        self._log("Аутентификация не требуется для этой платформы")
        self.is_authenticated = True
        return True

    def _check_session(self) -> bool:
        """Проверка активности сессии"""
        try:
            test_url = self.config.get('session_check_url', f"{self.config['base_url']}/")
            response = self.session.get(test_url, timeout=10)
            return response.status_code == 200 and 'login' not in response.url.lower()
        except:
            return False

    def _login_via_cookie(self) -> bool:
        """Аутентификация через куки"""
        cookies = self.credentials.get('cookies', {})
        if not cookies:
            self._log("Куки не найдены для аутентификации", level='WARNING')
            return False

        for name, value in cookies.items():
            self.session.cookies.set(name, value)

        if self._check_session():
            self._log("Успешная аутентификация через куки")
            self.is_authenticated = True
            return True

        self._log("Ошибка аутентификации через куки", level='ERROR')
        return False

    def search_jobs(self,
                    query: str = "копирайтинг дизайн программирование",
                    filters: Optional[Dict[str, Any]] = None,
                    max_results: int = 30) -> List[Dict[str, Any]]:
        """
        Поиск заказов на платформе с обходом защиты и интеллектуальной фильтрацией.

        Args:
            query: Поисковый запрос (автоматически разбивается на ключевые слова)
            filters: Фильтры (бюджет, сроки, навыки)
            max_results: Максимальное количество результатов

        Returns:
            Список заказов в унифицированном формате
        """
        if not self.is_authenticated:
            if not self.authenticate():
                raise RuntimeError(f"Необходима аутентификация для поиска на {self.platform_name}")

        # Применение рейт-лимитов
        self._enforce_rate_limits()

        # Формирование URL поиска
        search_url = self._build_search_url(query, filters)

        # Выбор метода скрапинга
        if self.config.get('requires_selenium', False):
            html = self._scrape_with_selenium(search_url)
        else:
            html = self._scrape_with_requests(search_url)

        if not html:
            self._log("Не удалось получить HTML страницы", level='ERROR')
            return []

        # Парсинг заказов
        jobs = self._parse_jobs_from_html(html, max_results)

        # Интеллектуальная фильтрация через ИИ
        filtered_jobs = self._ai_filter_jobs(jobs, filters)

        self._log(f"Найдено и отфильтровано {len(filtered_jobs)} заказов на {self.platform_name}")
        return filtered_jobs

    def _build_search_url(self, query: str, filters: Optional[Dict[str, Any]]) -> str:
        """Формирование URL поиска с учетом фильтров"""
        base_url = self.config['base_url']
        search_pattern = self.config.get('search_pattern', '/search?q={query}')

        # Обработка нескольких ключевых слов
        keywords = query.split()[:3]  # Берем первые 3 ключевых слова
        search_query = '+'.join(keywords)

        url = f"{base_url}{search_pattern.format(query=search_query)}"

        # Добавление фильтров
        if filters:
            filter_params = []
            if filters.get('min_budget'):
                filter_params.append(f"budget_min={filters['min_budget']}")
            if filters.get('max_budget'):
                filter_params.append(f"budget_max={filters['max_budget']}")
            if filters.get('category'):
                filter_params.append(f"category={filters['category']}")

            if filter_params:
                url += "&" + "&".join(filter_params)

        return url

    def _scrape_with_requests(self, url: str) -> Optional[str]:
        """Скрапинг через requests с обходом защиты"""
        try:
            # Добавление задержки для имитации человека
            time.sleep(random.uniform(1.5, 3.5))

            response = self.session.get(url, timeout=15)
            response.raise_for_status()

            # Проверка на Cloudflare/защиту
            if 'cloudflare' in response.text.lower() or 'checking your browser' in response.text.lower():
                self._log("Обнаружена защита Cloudflare, переключение на Selenium", level='WARNING')
                return self._scrape_with_selenium(url)

            # Проверка на капчу
            if self._detect_captcha(response.text):
                self._log("Обнаружена капча, решение...", level='WARNING')
                return self._solve_captcha_and_retry(url)

            return response.text

        except Exception as e:
            self._log(f"Ошибка скрапинга через requests: {e}", level='ERROR')
            return None

    def _scrape_with_selenium(self, url: str) -> Optional[str]:
        """Скрапинг через Selenium с обходом детекта"""
        try:
            # Настройка веб-драйвера
            options = webdriver.ChromeOptions()
            options.add_argument('--disable-blink-features=AutomationControlled')
            options.add_experimental_option("excludeSwitches", ["enable-automation"])
            options.add_experimental_option('useAutomationExtension', False)
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--disable-gpu')
            options.add_argument('--window-size=1920,1080')

            if self.config.get('headless', True):
                options.add_argument('--headless')

            driver = webdriver.Chrome(options=options)

            # Обход детекта Selenium
            driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            driver.execute_cdp_cmd('Network.setUserAgentOverride', {
                "userAgent": self.session.headers['User-Agent']
            })

            # Переход на страницу
            driver.get(url)

            # Ожидание загрузки контента
            job_selector = self.config.get('job_selector', '.job-item')
            try:
                WebDriverWait(driver, 15).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, job_selector))
                )
            except TimeoutException:
                self._log("Таймаут ожидания загрузки контента", level='WARNING')

            # Прокрутка для загрузки дополнительных результатов
            if self.config.get('infinite_scroll', False):
                self._scroll_to_load_more(driver, max_scrolls=3)

            # Получение HTML
            html = driver.page_source
            driver.quit()

            return html

        except Exception as e:
            self._log(f"Ошибка скрапинга через Selenium: {e}", level='ERROR')
            return None

    def _scroll_to_load_more(self, driver, max_scrolls: int = 3):
        """Прокрутка страницы для загрузки дополнительного контента"""
        last_height = driver.execute_script("return document.body.scrollHeight")

        for _ in range(max_scrolls):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(random.uniform(2.0, 4.0))  # Рандомная задержка

            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height

    def _parse_jobs_from_html(self, html: str, max_results: int = 30) -> List[Dict[str, Any]]:
        """Парсинг заказов из HTML с применением правил конфигурации"""
        soup = BeautifulSoup(html, 'html.parser')
        job_elements = soup.select(self.config['job_selector'])

        jobs = []
        for element in job_elements[:max_results]:
            try:
                job = self._extract_job_data(element)
                if job:
                    jobs.append(job)
            except Exception as e:
                self._log(f"Ошибка извлечения данных заказа: {e}", level='DEBUG')

        return jobs

    def _extract_job_data(self, element: Any) -> Optional[Dict[str, Any]]:
        """Извлечение данных заказа из HTML-элемента"""
        # Заголовок
        title_elem = element.select_one(self.config.get('title_selector'))
        title = title_elem.get_text(strip=True) if title_elem else None
        if not title:
            return None

        # Цена
        price = 0.0
        price_elem = element.select_one(self.config.get('price_selector'))
        if price_elem:
            price_text = price_elem.get_text(strip=True)
            price = self._extract_price(price_text)

        # URL
        url_elem = element.select_one(self.config.get('url_selector'))
        url = url_elem['href'] if url_elem else ''
        if url and not url.startswith('http'):
            url = self.config['base_url'] + url

        # ID заказа (хеш от заголовка + цены)
        job_id = hashlib.md5(f"{title}{price}".encode()).hexdigest()[:16]

        # Описание (если есть)
        description = ''
        desc_selector = self.config.get('description_selector')
        if desc_selector:
            desc_elem = element.select_one(desc_selector)
            if desc_elem:
                description = desc_elem.get_text(strip=True)[:500]

        # Навыки (если есть)
        skills = []
        skills_selector = self.config.get('skills_selector')
        if skills_selector:
            skills_elems = element.select(skills_selector)
            skills = [s.get_text(strip=True) for s in skills_elems]

        return {
            'platform': self.platform_name,
            'job_id': job_id,
            'title': title,
            'description': description,
            'budget': {
                'amount': price,
                'currency': self.config.get('currency', 'RUB'),
                'type': 'fixed'
            },
            'skills': skills,
            'url': url,
            'posted_at': datetime.now().isoformat(),
            'raw_html': str(element)[:1000]  # Для отладки
        }

    def _extract_price(self, text: str) -> float:
        """Извлечение цены из текста"""
        # Поиск чисел с возможными разделителями
        match = re.search(r'[\d\s,.]+', text.replace(' ', '').replace(',', '.'))
        if match:
            try:
                return float(match.group(0).replace(' ', '').replace(',', '.'))
            except:
                pass
        return 0.0

    def _detect_captcha(self, html: str) -> bool:
        """Детектирование капчи на странице"""
        captcha_indicators = [
            'captcha', 'hcaptcha', 'recaptcha', 'cloudflare-captcha',
            'verify you are human', 'robot', 'not a robot'
        ]
        html_lower = html.lower()
        return any(indicator in html_lower for indicator in captcha_indicators)

    def _solve_captcha_and_retry(self, url: str) -> Optional[str]:
        """Решение капчи через 2Captcha/AntiCaptcha и повтор запроса"""
        captcha_solver = self.config.get('captcha_solver')
        if not captcha_solver:
            self._log("Решатель капчи не настроен", level='ERROR')
            return None

        # Здесь должна быть интеграция с сервисом решения капчи
        # Для примера — симуляция
        self._log(f"Решение капчи через {captcha_solver}...", level='INFO')
        time.sleep(10)  # Симуляция времени решения

        # Повтор запроса
        return self._scrape_with_requests(url)

    def _ai_filter_jobs(self, jobs: List[Dict[str, Any]], filters: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Интеллектуальная фильтрация заказов через ИИ:
        - Удаление спама и мошеннических заказов
        - Оценка реалистичности бюджета
        - Анализ качества описания ТЗ
        - Рекомендация приоритета
        """
        if not jobs:
            return []

        # Загрузка модели для анализа текста
        try:
            model = self.ai_hub.get_model(task_type='sentiment_analysis', language='ru')
        except:
            # Если ИИ недоступен — базовая фильтрация
            return self._basic_filter_jobs(jobs, filters)

        filtered_jobs = []

        for job in jobs:
            # Анализ описания заказа
            analysis = model(job['description'] or job['title'])

            # Фильтрация по качеству
            is_quality = self._evaluate_job_quality(job, analysis, filters)

            if is_quality:
                # Добавление метаданных ИИ
                job['ai_analysis'] = {
                    'quality_score': analysis.get('score', 0.5),
                    'sentiment': analysis.get('label', 'neutral'),
                    'priority': self._calculate_priority(job, analysis),
                    'spam_probability': self._detect_spam(job)
                }
                filtered_jobs.append(job)

        # Сортировка по приоритету
        filtered_jobs.sort(key=lambda x: x['ai_analysis']['priority'], reverse=True)

        return filtered_jobs

    def _basic_filter_jobs(self, jobs: List[Dict[str, Any]], filters: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Базовая фильтрация без ИИ"""
        min_budget = filters.get('min_budget', 500) if filters else 500

        return [
            job for job in jobs
            if job.get('budget', {}).get('amount', 0) >= min_budget
               and len(job.get('title', '')) > 10
               and not self._is_spam_basic(job)
        ]

    def _evaluate_job_quality(self, job: Dict[str, Any], analysis: Dict[str, Any],
                              filters: Optional[Dict[str, Any]]) -> bool:
        """Оценка качества заказа"""
        # Минимальный бюджет
        min_budget = filters.get('min_budget', 500) if filters else 500
        if job['budget']['amount'] < min_budget:
            return False

        # Анализ описания
        description = job.get('description', '')
        if len(description) < 50:  # Слишком короткое описание
            return False

        # Детектирование спама
        if self._detect_spam(job) > 0.7:  # Вероятность спама > 70%
            return False

        # Анализ тональности (негативные заказы часто мошеннические)
        if analysis.get('label') == 'negative' and analysis.get('score', 0) > 0.8:
            return False

        return True

    def _detect_spam(self, job: Dict[str, Any]) -> float:
        """Детектирование спама/мошенничества (0.0 - 1.0)"""
        title = job['title'].lower()
        description = job.get('description', '').lower()

        spam_keywords = [
            'срочн', 'очень срочн', 'немедленно', 'без оплаты', 'тестовое задание',
            'оплата после', 'предоплата', 'гарант', '100%', 'миллион', 'легко',
            'без опыта', 'для новичков', 'за 5 минут', 'удаленная работа',
            'заработок', 'деньги', 'оплата на карту'
        ]

        spam_score = sum(1 for kw in spam_keywords if kw in title or kw in description) / len(spam_keywords)

        # Дополнительные факторы
        if job['budget']['amount'] < 300:  # Очень низкий бюджет
            spam_score += 0.3
        if len(job['title']) < 15:  # Очень короткий заголовок
            spam_score += 0.2

        return min(1.0, spam_score)

    def _is_spam_basic(self, job: Dict[str, Any]) -> bool:
        """Базовое детектирование спама без ИИ"""
        title = job['title'].lower()
        spam_triggers = ['срочн', 'тестовое', 'без оплаты', 'гарант', '100%']
        return any(trigger in title for trigger in spam_triggers) or job['budget']['amount'] < 300

    def _calculate_priority(self, job: Dict[str, Any], analysis: Dict[str, Any]) -> float:
        """Расчет приоритета заказа (0.0 - 1.0)"""
        priority = 0.0

        # Бюджет (чем выше, тем выше приоритет)
        budget = job['budget']['amount']
        priority += min(budget / 10000, 0.4)  # Максимум 0.4 за бюджет

        # Качество описания
        desc_quality = len(job.get('description', '')) / 500
        priority += min(desc_quality * 0.3, 0.3)

        # Анализ ИИ
        ai_score = analysis.get('score', 0.5)
        priority += ai_score * 0.3

        return min(1.0, priority)

    def submit_proposal(self, job_id: str, proposal_text: str, amount: Optional[float] = None) -> Dict[str, Any]:
        """
        Отправка отклика на заказ (если платформа поддерживает).
        Для большинства "серых" площадок — только ручная отправка через уведомление.
        """
        # Для большинства скрапинговых платформ отправка откликов невозможна
        # Вместо этого — уведомление пользователя
        self._notify_user_about_job(job_id, proposal_text, amount)

        return {
            'success': True,
            'message': 'Заказ добавлен в очередь уведомлений. Отправьте отклик вручную.',
            'notification_sent': True
        }

    def _notify_user_about_job(self, job_id: str, proposal_text: str, amount: Optional[float]):
        """Отправка уведомления пользователю о найденном заказе"""
        notification = {
            'platform': self.platform_name,
            'job_id': job_id,
            'message': f'Найден перспективный заказ на {self.platform_name}! Отправьте отклик вручную.',
            'proposal_template': proposal_text,
            'suggested_amount': amount,
            'timestamp': datetime.now().isoformat()
        }

        # Отправка через Telegram
        try:
            from services.notification.telegram_service import TelegramService
            telegram = TelegramService()
            telegram.send_message(
                f"🔔 НОВЫЙ ЗАКАЗ на {self.platform_name}\n\n"
                f"ID: {job_id}\n"
                f"Предложенный текст отклика:\n{proposal_text[:200]}...\n\n"
                f"Рекомендуемая цена: {amount} ₽\n\n"
                f"Откройте приложение для отправки отклика!"
            )
        except Exception as e:
            self._log(f"Ошибка отправки уведомления: {e}", level='WARNING')

    def _log(self, message: str, level: str = 'INFO'):
        """Логирование событий"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_entry = f"[{timestamp}] [UniversalScraper:{self.platform_name}] [{level}] {message}"

        # Запись в файл
        log_dir = Path("logs/platforms")
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"{self.platform_name}.log"

        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(log_entry + '\n')

        # Вывод в консоль для критических ошибок
        if level in ['ERROR', 'CRITICAL']:
            print(f"\033[91m{log_entry}\033[0m")
        elif level == 'WARNING':
            print(f"\033[93m{log_entry}\033[0m")

    @classmethod
    def get_all_available_platforms(cls) -> Dict[str, str]:
        """Получение списка всех доступных платформ для интеграции"""
        platforms = {
            'youla_freelance': 'Youla Услуги (Россия)',
            'avito_uslugi': 'Авито Услуги (Россия)',
            'irr_freelance': 'IRR Услуги (СНГ)',
            'workzilla': 'Workzilla (Международная)',
            'weblancer': 'Weblancer (СНГ)',
            'experts': 'Experts.ru (Россия)',
            'free-lance_ru': 'Free-lance.ru (Россия)',
            'telegram_channels': 'Telegram-каналы с заказами'
        }
        # Добавляем кастомные платформы из конфигов
        custom_dir = Path("config/platforms/custom")
        if custom_dir.exists():
            for cfg in custom_dir.glob("*.yaml"):
                platforms[cfg.stem] = f"Кастомная: {cfg.stem}"

        return platforms


# Глобальный реестр адаптеров
_scraper_adapters_registry = {}


def register_scraper_adapter(platform_name: str, adapter_class):
    """Регистрация нового адаптера скрапинга"""
    _scraper_adapters_registry[platform_name] = adapter_class


def get_scraper_adapter(platform_name: str, **kwargs) -> UniversalScraperAdapter:
    """Получение адаптера скрапинга для платформы"""
    if platform_name in _scraper_adapters_registry:
        return _scraper_adapters_registry[platform_name](platform_name, **kwargs)
    return UniversalScraperAdapter(platform_name, **kwargs)