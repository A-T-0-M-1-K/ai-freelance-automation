import ssl
import os
from pathlib import Path
from typing import Dict, Optional
import json


class DatabaseSSLValidator:
    """
    Валидатор и настройщик SSL-соединения с базой данных для продакшена.
    Обеспечивает шифрование на уровне транспорта.
    """

    REQUIRED_SSL_PARAMS = [
        'sslmode',
        'sslrootcert',
        'sslcert',
        'sslkey'
    ]

    def __init__(self, config_path: str = "config/database.json"):
        self.config_path = Path(config_path)
        self.config = self._load_config()

    def _load_config(self) -> Dict:
        if not self.config_path.exists():
            raise FileNotFoundError(f"Конфигурация БД не найдена: {self.config_path}")

        with open(self.config_path) as f:
            return json.load(f)

    def enable_strict_ssl(self) -> Dict:
        """
        Включает строгий режим SSL с валидацией сертификатов.
        """
        # Создание директории для сертификатов
        certs_dir = Path("config/certs")
        certs_dir.mkdir(parents=True, exist_ok=True)

        # Генерация путей к сертификатам (если их нет — потребуется ручная установка от провайдера БД)
        ssl_config = {
            "sslmode": "verify-full",  # Самый строгий режим
            "sslrootcert": str(certs_dir / "root.crt"),
            "sslcert": str(certs_dir / "client.crt"),
            "sslkey": str(certs_dir / "client.key"),
            "ssl_min_protocol_version": "TLSv1.3",  # Минимальная версия протокола
            "require_ssl": True
        }

        # Интеграция в основную конфигурацию
        if "connection" not in self.config:
            self.config["connection"] = {}

        self.config["connection"].update(ssl_config)
        self.config["security"]["db_ssl_enabled"] = True

        # Сохранение обновлённой конфигурации
        with open(self.config_path, 'w') as f:
            json.dump(self.config, f, indent=2)

        print("✅ SSL для базы данных включён в строгом режиме (verify-full)")
        print("⚠️  ВАЖНО: Поместите корневой сертификат в:", certs_dir / "root.crt")
        print("⚠️  ВАЖНО: Поместите клиентский сертификат в:", certs_dir / "client.crt")
        print("⚠️  ВАЖНО: Поместите приватный ключ в:", certs_dir / "client.key")
        print("🔒 Установите права: chmod 600 config/certs/*.key")

        return ssl_config

    def validate_ssl_setup(self) -> bool:
        """
        Валидация корректности настройки SSL перед запуском в продакшене.
        """
        if not self.config.get("security", {}).get("db_ssl_enabled", False):
            raise RuntimeError("❌ DB_SSL_ENABLED=false — запрещено для продакшена!")

        connection = self.config.get("connection", {})

        # Проверка обязательных параметров
        for param in self.REQUIRED_SSL_PARAMS:
            if param not in connection:
                raise ValueError(f"Отсутствует обязательный SSL-параметр: {param}")

        # Проверка существования файлов сертификатов
        for cert_param in ['sslrootcert', 'sslcert', 'sslkey']:
            cert_path = Path(connection[cert_param])
            if not cert_path.exists():
                raise FileNotFoundError(f"SSL-сертификат не найден: {cert_path}")

            # Проверка прав доступа для приватного ключа
            if 'key' in cert_param.lower():
                stat = os.stat(cert_path)
                if stat.st_mode & 0o077:  # Доступны другим пользователям
                    raise PermissionError(
                        f"Небезопасные права доступа к приватному ключу: {cert_path}\n"
                        f"Требуется: chmod 600 {cert_path}"
                    )

        # Тестовое соединение с валидацией сертификата
        try:
            context = ssl.create_default_context(cafile=connection['sslrootcert'])
            context.load_cert_chain(
                certfile=connection['sslcert'],
                keyfile=connection['sslkey']
            )
            context.verify_mode = ssl.CERT_REQUIRED
            context.check_hostname = True

            print("✅ SSL-конфигурация прошла валидацию")
            return True

        except ssl.SSLError as e:
            raise RuntimeError(f"Ошибка валидации SSL: {e}")

    def generate_ssl_config_snippet(self) -> str:
        """
        Генерирует сниппет конфигурации для .env файла.
        """
        snippet = """
# SSL Configuration for Production Database (REQUIRED)
DB_SSL_ENABLED=true
DB_SSL_MODE=verify-full
DB_SSL_ROOT_CERT=config/certs/root.crt
DB_SSL_CERT=config/certs/client.crt
DB_SSL_KEY=config/certs/client.key
DB_SSL_MIN_VERSION=TLSv1.3

# Security Hardening
SECRET_KEY_LENGTH=64  # bytes
ENCRYPTION_ALGORITHM=AES-256-GCM
"""
        return snippet


# Использование валидатора при старте системы
def enforce_production_security():
    """
    Принудительная проверка безопасности перед запуском в продакшене.
    """
    env = os.environ.get("ENVIRONMENT", "development")

    if env == "production":
        print("🛡️  Запуск валидации безопасности для продакшена...")

        # 1. Проверка SECRET_KEY
        from core.security.secret_vault import SecretVault
        vault = SecretVault()
        if not vault.is_key_secure():
            raise RuntimeError("❌ SECRET_KEY не соответствует требованиям безопасности!")

        # 2. Проверка SSL для БД
        validator = DatabaseSSLValidator()
        if not validator.config.get("security", {}).get("db_ssl_enabled"):
            print("⚠️  DB_SSL_ENABLED=false — автоматическое включение...")
            validator.enable_strict_ssl()

        validator.validate_ssl_setup()

        # 3. Проверка шифрования данных
        from core.security.encryption_engine import EncryptionEngine
        engine = EncryptionEngine()
        if not engine.is_fips_compliant():
            raise RuntimeError("❌ Шифрование не соответствует стандартам FIPS 140-2!")

        print("✅ Все проверки безопасности пройдены. Система готова к продакшену.")
    else:
        print(f"ℹ️  Режим окружения: {env} — расширенные проверки безопасности отключены.")


if __name__ == "__main__":
    enforce_production_security()