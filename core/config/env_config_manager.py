"""
Унифицированный менеджер конфигурации на основе переменных окружения
Заменяет устаревшую систему профилей (development/staging/production JSON файлы)
"""
import os
import json
import logging
from typing import Any, Dict, Optional, TypeVar, Type
from dataclasses import dataclass, field, asdict
from enum import Enum
import secrets
from pathlib import Path

logger = logging.getLogger(__name__)

T = TypeVar('T')


class EnvironmentType(Enum):
    """Типы окружений"""
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"
    TESTING = "testing"


@dataclass
class DatabaseConfig:
    """Конфигурация базы данных"""
    host: str = "localhost"
    port: int = 5432
    database: str = "ai_freelance"
    user: str = "postgres"
    password: str = ""
    pool_size: int = 20
    max_overflow: int = 40
    echo_sql: bool = False
    ssl_enabled: bool = False


@dataclass
class AIConfig:
    """Конфигурация ИИ моделей"""
    embedding_model: str = "bert-base-multilingual-cased"
    textgen_model: str = "gpt2-medium"
    translation_model: str = "facebook/nllb-200-distilled-600M"
    whisper_model: str = "openai/whisper-medium"
    device: str = "auto"
    quantization: str = "none"  # none, int8, int4, fp16
    cache_dir: str = "ai/models"


@dataclass
class SecurityConfig:
    """Конфигурация безопасности"""
    secret_key: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    cors_origins: list = field(default_factory=lambda: ["http://localhost:3000"])
    rate_limit_requests: int = 100
    rate_limit_window: int = 60  # секунд


@dataclass
class AppConfig:
    """Основная конфигурация приложения"""
    environment: EnvironmentType = EnvironmentType.DEVELOPMENT
    debug: bool = True
    log_level: str = "DEBUG"
    data_dir: str = "data"
    temp_dir: str = "ai/temp"
    backup_dir: str = "backup"
    timezone: str = "UTC"
    default_language: str = "ru"
    supported_languages: list = field(default_factory=lambda: ["ru", "en"])


class EnvConfigManager:
    """
    Менеджер конфигурации с приоритетом:
    1. Переменные окружения
    2. Файл .env
    3. Значения по умолчанию из датаклассов
    """

    def __init__(self, env_file: str = ".env"):
        self.env_file = env_file
        self._loaded = False
        self._config_cache: Dict[str, Any] = {}

        # Загрузка .env файла если существует
        self._load_env_file()

        # Определение типа окружения
        env_str = self._get_env_var("ENVIRONMENT", "development").lower()
        try:
            self.environment = EnvironmentType(env_str)
        except ValueError:
            logger.warning(f"Неизвестный тип окружения '{env_str}', используется 'development'")
            self.environment = EnvironmentType.DEVELOPMENT

        logger.info(f"Инициализирован менеджер конфигурации для окружения: {self.environment.value}")

    def _load_env_file(self):
        """Загрузка переменных из .env файла"""
        if not os.path.exists(self.env_file):
            logger.debug(f"Файл {self.env_file} не найден, используются только системные переменные окружения")
            return

        try:
            with open(self.env_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        key = key.strip()
                        value = value.strip().strip('"').strip("'")

                        # Установка только если переменная не определена в системном окружении
                        if key not in os.environ:
                            os.environ[key] = value

            logger.info(f"Загружено переменных из {self.env_file}: {len(os.environ)}")
        except Exception as e:
            logger.error(f"Ошибка загрузки {self.env_file}: {str(e)}")

    def _get_env_var(self, key: str, default: Any = None) -> Any:
        """Получение переменной окружения с преобразованием типов"""
        value = os.environ.get(key, default)

        if value is None:
            return None

        # Автоматическое преобразование типов
        if isinstance(default, bool):
            return str(value).lower() in ('true', '1', 'yes', 'on')
        elif isinstance(default, int):
            try:
                return int(value)
            except (ValueError, TypeError):
                return default
        elif isinstance(default, float):
            try:
                return float(value)
            except (ValueError, TypeError):
                return default
        elif isinstance(default, list):
            # Списки в формате: "item1,item2,item3"
            return [v.strip() for v in str(value).split(',')] if value else []

        return str(value)

    def get_database_config(self) -> DatabaseConfig:
        """Получение конфигурации БД"""
        cache_key = "database_config"
        if cache_key in self._config_cache:
            return self._config_cache[cache_key]

        config = DatabaseConfig(
            host=self._get_env_var("DB_HOST", "localhost"),
            port=self._get_env_var("DB_PORT", 5432),
            database=self._get_env_var("DB_NAME", "ai_freelance"),
            user=self._get_env_var("DB_USER", "postgres"),
            password=self._get_env_var("DB_PASSWORD", ""),
            pool_size=self._get_env_var("DB_POOL_SIZE", 20),
            max_overflow=self._get_env_var("DB_MAX_OVERFLOW", 40),
            echo_sql=self._get_env_var("DB_ECHO_SQL", self.environment == EnvironmentType.DEVELOPMENT),
            ssl_enabled=self._get_env_var("DB_SSL_ENABLED", self.environment == EnvironmentType.PRODUCTION)
        )

        self._config_cache[cache_key] = config
        return config

    def get_ai_config(self) -> AIConfig:
        """Получение конфигурации ИИ"""
        cache_key = "ai_config"
        if cache_key in self._config_cache:
            return self._config_cache[cache_key]

        config = AIConfig(
            embedding_model=self._get_env_var("AI_EMBEDDING_MODEL", "bert-base-multilingual-cased"),
            textgen_model=self._get_env_var("AI_TEXTGEN_MODEL", "gpt2-medium"),
            translation_model=self._get_env_var("AI_TRANSLATION_MODEL", "facebook/nllb-200-distilled-600M"),
            whisper_model=self._get_env_var("AI_WHISPER_MODEL", "openai/whisper-medium"),
            device=self._get_env_var("AI_DEVICE", "auto"),
            quantization=self._get_env_var("AI_QUANTIZATION", "none"),
            cache_dir=self._get_env_var("AI_CACHE_DIR", "ai/models")
        )

        self._config_cache[cache_key] = config
        return config

    def get_security_config(self) -> SecurityConfig:
        """Получение конфигурации безопасности"""
        cache_key = "security_config"
        if cache_key in self._config_cache:
            return self._config_cache[cache_key]

        # Секретный ключ из окружения или генерация нового
        secret_key = self._get_env_var("SECRET_KEY")
        if not secret_key:
            if self.environment == EnvironmentType.PRODUCTION:
                raise ValueError("SECRET_KEY обязателен для production окружения!")
            secret_key = secrets.token_urlsafe(32)
            logger.warning("Сгенерирован временный SECRET_KEY (только для разработки!)")

        config = SecurityConfig(
            secret_key=secret_key,
            algorithm=self._get_env_var("JWT_ALGORITHM", "HS256"),
            access_token_expire_minutes=self._get_env_var("JWT_ACCESS_EXPIRE_MINUTES", 30),
            refresh_token_expire_days=self._get_env_var("JWT_REFRESH_EXPIRE_DAYS", 7),
            cors_origins=self._get_env_var("CORS_ORIGINS", ["http://localhost:3000"]),
            rate_limit_requests=self._get_env_var("RATE_LIMIT_REQUESTS", 100),
            rate_limit_window=self._get_env_var("RATE_LIMIT_WINDOW", 60)
        )

        self._config_cache[cache_key] = config
        return config

    def get_app_config(self) -> AppConfig:
        """Получение основной конфигурации приложения"""
        cache_key = "app_config"
        if cache_key in self._config_cache:
            return self._config_cache[cache_key]

        config = AppConfig(
            environment=self.environment,
            debug=self._get_env_var("DEBUG", self.environment != EnvironmentType.PRODUCTION),
            log_level=self._get_env_var("LOG_LEVEL",
                                        "DEBUG" if self.environment == EnvironmentType.DEVELOPMENT else "INFO"),
            data_dir=self._get_env_var("DATA_DIR", "data"),
            temp_dir=self._get_env_var("TEMP_DIR", "ai/temp"),
            backup_dir=self._get_env_var("BACKUP_DIR", "backup"),
            timezone=self._get_env_var("TIMEZONE", "UTC"),
            default_language=self._get_env_var("DEFAULT_LANGUAGE", "ru"),
            supported_languages=self._get_env_var("SUPPORTED_LANGUAGES", ["ru", "en"])
        )

        self._config_cache[cache_key] = config
        return config

    def get_all_configs(self) -> Dict[str, Any]:
        """Получение всех конфигураций в виде словаря"""
        return {
            "environment": self.environment.value,
            "database": asdict(self.get_database_config()),
            "ai": asdict(self.get_ai_config()),
            "security": asdict(self.get_security_config()),
            "app": asdict(self.get_app_config())
        }

    def save_to_file(self, path: str = "config/current_config.json"):
        """Сохранение текущей конфигурации в файл (для отладки/аудита)"""
        Path(path).parent.mkdir(parents=True, exist_ok=True)

        with open(path, 'w', encoding='utf-8') as f:
            json.dump(self.get_all_configs(), f, ensure_ascii=False, indent=2)

        logger.info(f"Конфигурация сохранена в {path}")

    def validate_production_ready(self) -> Dict[str, Any]:
        """
        Валидация конфигурации для продакшена
        Возвращает словарь с ошибками и предупреждениями
        """
        errors = []
        warnings = []

        if self.environment == EnvironmentType.PRODUCTION:
            # Проверка обязательных настроек для продакшена
            sec_config = self.get_security_config()
            if sec_config.secret_key == secrets.token_urlsafe(32)[:len(sec_config.secret_key)]:
                errors.append("SECRET_KEY не задан — сгенерирован временный ключ")

            db_config = self.get_database_config()
            if db_config.host == "localhost":
                warnings.append("DB_HOST установлен в 'localhost' — для продакшена используйте реальный хост")

            if db_config.password == "":
                errors.append("DB_PASSWORD не задан — обязателен для продакшена")

            if not db_config.ssl_enabled:
                warnings.append("DB_SSL_ENABLED отключен — рекомендуется включить для продакшена")

        return {
            "environment": self.environment.value,
            "errors": errors,
            "warnings": warnings,
            "is_production_ready": len(errors) == 0
        }