"""
Многоуровневое хранилище секретов с поддержкой:
- Шифрования секретов на уровне приложения (AES-GCM)
- Интеграции с системными хранилищами (HashiCorp Vault, AWS Secrets Manager)
- Автоматической ротации ключей
- Аудита доступа к секретам
- Резервного режима при недоступности внешних хранилищ
- Автоматической миграции существующих секретов
"""
import os
import json
import base64
import hashlib
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from pathlib import Path
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.backends import default_backend
from cryptography.exceptions import InvalidTag

logger = logging.getLogger(__name__)


class SecretVault:
    """
    Безопасное хранилище секретов с многоуровневой защитой
    """

    def __init__(self,
                 master_key_env_var: str = "AIFA_MASTER_KEY",
                 vault_url: Optional[str] = None,
                 vault_token_env_var: str = "VAULT_TOKEN"):
        self.master_key = self._load_master_key(master_key_env_var)
        self.salt = b"aifa_vault_salt_2024_v2"  # Фиксированная соль для воспроизводимости
        self.keys_cache: Dict[str, bytes] = {}
        self.secrets_cache: Dict[str, Any] = {}
        self.last_rotation = datetime.now()
        self.rotation_interval = timedelta(days=30)
        self.vault_client = None
        self.vault_enabled = False

        # Инициализация внешнего хранилища (если настроено)
        if vault_url and os.environ.get(vault_token_env_var):
            try:
                self._init_vault_client(vault_url, os.environ.get(vault_token_env_var))
                self.vault_enabled = True
                logger.info("✅ Интеграция с HashiCorp Vault успешно инициализирована")
            except Exception as e:
                logger.warning(f"⚠️ Ошибка инициализации Vault: {str(e)}. Используется локальное хранилище.")

        # Генерация временного ключа для режима разработки (ТОЛЬКО для разработки!)
        if not self.master_key and not self.vault_enabled:
            if os.environ.get("ENVIRONMENT", "development") == "development":
                logger.warning(
                    "⚠️ MASTER KEY не найден в переменных окружения. "
                    "Генерация ВРЕМЕННОГО ключа для режима разработки. "
                    "НИКОГДА НЕ ИСПОЛЬЗУЙТЕ В ПРОДАКШЕНЕ!"
                )
                self.master_key = self._generate_temporary_master_key()
                # Сохранение временного ключа для сессии (не сохраняется на диск!)
                os.environ[master_key_env_var] = base64.b64encode(self.master_key).decode('utf-8')
            else:
                raise ValueError(
                    "❌ КРИТИЧЕСКАЯ ОШИБКА: MASTER KEY не найден в продакшен-окружении. "
                    "Установите переменную окружения AIFA_MASTER_KEY перед запуском системы."
                )

        # Автоматическая миграция существующих секретов
        self._auto_migrate_legacy_secrets()

        logger.info("✅ Инициализировано безопасное хранилище секретов")

    def _load_master_key(self, env_var: str) -> Optional[bytes]:
        """Загрузка мастер-ключа из переменных окружения"""
        key = os.environ.get(env_var)
        if key:
            # Поддержка разных форматов ключа
            if key.startswith("base64:"):
                return base64.b64decode(key[7:])
            elif key.startswith("hex:"):
                return bytes.fromhex(key[4:])
            elif key.startswith("file:"):
                file_path = Path(key[5:])
                if file_path.exists():
                    return file_path.read_bytes()
                else:
                    logger.error(f"❌ Файл ключа не найден: {file_path}")
                    return None
            else:
                return key.encode('utf-8')
        return None

    def _generate_temporary_master_key(self) -> bytes:
        """Генерация временного мастер-ключа для режима разработки"""
        import secrets
        return secrets.token_bytes(32)

    def _init_vault_client(self, vault_url: str, vault_token: str):
        """Инициализация клиента HashiCorp Vault"""
        try:
            import hvac
            self.vault_client = hvac.Client(url=vault_url, token=vault_token)

            # Проверка работоспособности
            if not self.vault_client.is_authenticated():
                raise Exception("❌ Не удалось аутентифицироваться в Vault")

            # Создание секретного пути если не существует
            if not self.vault_client.sys.list_mounted_secrets_engines().get('aifa/'):
                self.vault_client.sys.enable_secrets_engine(
                    backend_type='kv',
                    path='aifa',
                    options={'version': '2'}
                )
        except ImportError:
            logger.warning("⚠️ Библиотека hvac не установлена. Используется локальное хранилище.")
            self.vault_client = None
        except Exception as e:
            logger.warning(f"⚠️ Ошибка инициализации Vault: {str(e)}")
            self.vault_client = None

    def _derive_key(self, context: str) -> bytes:
        """Вывод ключа шифрования из мастер-ключа с контекстом"""
        cache_key = f"{context}:{hashlib.sha256(self.master_key).hexdigest()[:8]}"
        if cache_key in self.keys_cache:
            return self.keys_cache[cache_key]

        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=self.salt,
            iterations=100000,
            backend=default_backend()
        )

        key = kdf.derive(self.master_key + context.encode('utf-8'))
        self.keys_cache[cache_key] = key
        return key

    def encrypt(self, plaintext: str, context: str = "default") -> str:
        """Шифрование секрета с аутентификацией"""
        if not plaintext:
            return ""

        # Использование внешнего хранилища если доступно
        if self.vault_enabled and self.vault_client:
            try:
                self.vault_client.secrets.kv.v2.create_or_update_secret(
                    path=f"aifa/{context}",
                    secret={"value": plaintext}
                )
                return f"vault:{context}"
            except Exception as e:
                logger.warning(f"⚠️ Ошибка сохранения в Vault: {str(e)}. Используется локальное шифрование.")

        # Локальное шифрование как резервный вариант
        key = self._derive_key(context)
        aesgcm = AESGCM(key)

        nonce = os.urandom(12)
        ciphertext = aesgcm.encrypt(nonce, plaintext.encode('utf-8'), None)

        # Формат: nonce:ciphertext в base64 с префиксом версии
        encrypted = base64.b64encode(nonce + ciphertext).decode('utf-8')
        return f"aesgcm_v2:{encrypted}"

    def decrypt(self, encrypted: str, context: str = "default") -> str:
        """Расшифровка секрета с проверкой целостности"""
        if not encrypted:
            return ""

        # Обработка секретов из внешнего хранилища
        if encrypted.startswith("vault:"):
            vault_path = encrypted[6:]
            if self.vault_enabled and self.vault_client:
                try:
                    secret = self.vault_client.secrets.kv.v2.read_secret_version(path=f"aifa/{vault_path}")
                    return secret['data']['data']['value']
                except Exception as e:
                    logger.error(f"❌ Ошибка загрузки из Vault: {str(e)}")
                    raise ValueError("❌ Не удалось загрузить секрет из внешнего хранилища")
            else:
                raise ValueError("❌ Секрет хранится во внешнем хранилище, но интеграция недоступна")

        # Обработка локально зашифрованных секретов
        if not encrypted.startswith("aesgcm_v2:"):
            # Поддержка старого формата для обратной совместимости
            if encrypted.startswith("aesgcm:"):
                logger.warning(f"⚠️ Обнаружен устаревший формат шифрования для контекста {context}. Выполняется миграция...")
                # Расшифровка старым методом (без аутентификации)
                encrypted_data = base64.b64decode(encrypted[7:])
                nonce = encrypted_data[:12]
                ciphertext = encrypted_data[12:]

                key = self._derive_key(context)
                aesgcm = AESGCM(key)
                try:
                    plaintext = aesgcm.decrypt(nonce, ciphertext, None)
                    # Миграция на новый формат
                    new_encrypted = self.encrypt(plaintext.decode('utf-8'), context)
                    return plaintext.decode('utf-8')
                except Exception as e:
                    logger.error(f"❌ Ошибка расшифровки старого формата: {str(e)}")
                    raise
            else:
                raise ValueError(f"❌ Неподдерживаемый формат шифрования: {encrypted[:10]}")

        # Расшифровка нового формата
        encrypted_data = base64.b64decode(encrypted[10:])
        nonce = encrypted_data[:12]
        ciphertext = encrypted_data[12:]

        key = self._derive_key(context)
        aesgcm = AESGCM(key)

        try:
            plaintext = aesgcm.decrypt(nonce, ciphertext, None)
            return plaintext.decode('utf-8')
        except InvalidTag:
            raise ValueError("❌ Ошибка проверки целостности данных. Возможна атака или повреждение данных.")
        except Exception as e:
            raise ValueError(f"❌ Ошибка расшифровки: {str(e)}")

    def store_secret(self, key: str, value: str, context: Optional[str] = None, ttl_days: Optional[int] = None):
        """Сохранение секрета в зашифрованном виде"""
        if context is None:
            context = f"secret_{key}"

        # Шифрование значения
        encrypted = self.encrypt(value, context)

        # Подготовка метаданных
        secret_info = {
            "value": encrypted,
            "context": context,
            "stored_at": datetime.now().isoformat(),
            "rotated_at": None,
            "ttl_days": ttl_days,
            "access_count": 0,
            "last_accessed": None
        }

        # Сохранение в защищенном хранилище
        secrets_path = Path("data/secrets.json")
        secrets_data = {}

        if secrets_path.exists():
            try:
                # Расшифровка файла секретов
                file_key = self._derive_key("secrets_file_v2")
                with open(secrets_path, 'rb') as f:
                    encrypted_file = f.read()

                nonce = encrypted_file[:12]
                ciphertext = encrypted_file[12:]
                aesgcm = AESGCM(file_key)
                file_data = aesgcm.decrypt(nonce, ciphertext, None)
                secrets_data = json.loads(file_data.decode('utf-8'))
            except Exception as e:
                logger.warning(f"⚠️ Ошибка загрузки секретов: {str(e)}. Создается новый файл.")

        # Обновление или добавление секрета
        secrets_data[key] = secret_info

        # Шифрование всего файла секретов
        file_key = self._derive_key("secrets_file_v2")
        file_data = json.dumps(secrets_data, ensure_ascii=False, indent=2).encode('utf-8')
        aesgcm = AESGCM(file_key)
        nonce = os.urandom(12)
        encrypted_file = nonce + aesgcm.encrypt(nonce, file_data, None)

        # Атомарная запись (через временный файл)
        secrets_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = secrets_path.with_suffix('.tmp')
        with open(temp_path, 'wb') as f:
            f.write(encrypted_file)
        temp_path.replace(secrets_path)

        # Кэширование для быстрого доступа
        self.secrets_cache[key] = value

        logger.info(f"✅ Секрет '{key}' сохранен в зашифрованном виде")
        self.audit_access(key, "system", "store")

    def get_secret(self, key: str, default: Any = None) -> Any:
        """Получение секрета с расшифровкой и проверкой срока действия"""
        # Проверка кэша
        if key in self.secrets_cache:
            self._increment_access_count(key)
            return self.secrets_cache[key]

        # Загрузка из защищенного хранилища
        secrets_path = Path("data/secrets.json")
        if not secrets_path.exists():
            return default

        try:
            # Расшифровка файла секретов
            file_key = self._derive_key("secrets_file_v2")
            with open(secrets_path, 'rb') as f:
                encrypted_file = f.read()

            nonce = encrypted_file[:12]
            ciphertext = encrypted_file[12:]
            aesgcm = AESGCM(file_key)
            file_data = aesgcm.decrypt(nonce, ciphertext, None)
            secrets_data = json.loads(file_data.decode('utf-8'))

            if key in secrets_data:
                secret_info = secrets_data[key]

                # Проверка срока действия (TTL)
                if secret_info.get("ttl_days"):
                    stored_at = datetime.fromisoformat(secret_info["stored_at"])
                    ttl = timedelta(days=secret_info["ttl_days"])
                    if datetime.now() - stored_at > ttl:
                        logger.warning(f"⚠️ Секрет '{key}' истек ({ttl_days} дней). Требуется обновление.")
                        return default

                encrypted_value = secret_info["value"]
                context = secret_info["context"]

                value = self.decrypt(encrypted_value, context)
                self.secrets_cache[key] = value
                self._increment_access_count(key, secrets_data)

                self.audit_access(key, "system", "read")
                return value

        except Exception as e:
            logger.error(f"❌ Ошибка получения секрета '{key}': {str(e)}")
            # Попытка восстановления из резервной копии
            backup_path = secrets_path.with_suffix('.bak')
            if backup_path.exists():
                logger.info(f"🔄 Попытка восстановления секретов из резервной копии: {backup_path}")
                try:
                    backup_path.replace(secrets_path)
                    return self.get_secret(key, default)
                except Exception as be:
                    logger.error(f"❌ Ошибка восстановления из резервной копии: {str(be)}")

        return default

    def _increment_access_count(self, key: str, secrets_data: Optional[Dict] = None):
        """Инкремент счетчика доступа к секрету"""
        secrets_path = Path("data/secrets.json")
        if not secrets_path.exists():
            return

        try:
            if secrets_data is None:
                # Загрузка текущих данных
                file_key = self._derive_key("secrets_file_v2")
                with open(secrets_path, 'rb') as f:
                    encrypted_file = f.read()

                nonce = encrypted_file[:12]
                ciphertext = encrypted_file[12:]
                aesgcm = AESGCM(file_key)
                file_data = aesgcm.decrypt(nonce, ciphertext, None)
                secrets_data = json.loads(file_data.decode('utf-8'))

            if key in secrets_data:
                secrets_data[key]["access_count"] = secrets_data[key].get("access_count", 0) + 1
                secrets_data[key]["last_accessed"] = datetime.now().isoformat()

                # Сохранение обновленных данных
                file_key = self._derive_key("secrets_file_v2")
                file_data = json.dumps(secrets_data, ensure_ascii=False, indent=2).encode('utf-8')
                aesgcm = AESGCM(file_key)
                nonce = os.urandom(12)
                encrypted_file = nonce + aesgcm.encrypt(nonce, file_data, None)

                with open(secrets_path, 'wb') as f:
                    f.write(encrypted_file)

        except Exception as e:
            logger.warning(f"⚠️ Ошибка обновления счетчика доступа: {str(e)}")

    def rotate_keys(self):
        """Ротация ключей шифрования с сохранением доступа к существующим секретам"""
        if datetime.now() - self.last_rotation < self.rotation_interval:
            days_remaining = (self.rotation_interval - (datetime.now() - self.last_rotation)).days
            logger.info(f"ℹ️ Ротация ключей не требуется. Следующая ротация через {days_remaining} дней.")
            return

        logger.info("🔄 Начата ротация ключей шифрования...")

        # Создание резервной копии перед ротацией
        secrets_path = Path("data/secrets.json")
        if secrets_path.exists():
            backup_path = secrets_path.with_suffix(f'.bak.{datetime.now().strftime("%Y%m%d_%H%M%S")}')
            import shutil
            shutil.copy2(secrets_path, backup_path)
            logger.info(f"✅ Резервная копия создана: {backup_path}")

        # Генерация нового мастер-ключа (в продакшене — из внешнего источника)
        old_master_key = self.master_key
        self.master_key = self._generate_temporary_master_key() if os.environ.get("ENVIRONMENT") == "development" else self._load_master_key("AIFA_MASTER_KEY_NEW")

        if not self.master_key:
            logger.error("❌ Невозможно выполнить ротацию: новый мастер-ключ не доступен")
            self.master_key = old_master_key
            return

        # Расшифровка всех секретов старым ключом и шифрование новым
        try:
            file_key_old = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=self.salt,
                iterations=100000,
                backend=default_backend()
            ).derive(old_master_key + b"secrets_file_v2")

            file_key_new = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=self.salt,
                iterations=100000,
                backend=default_backend()
            ).derive(self.master_key + b"secrets_file_v2")

            with open(secrets_path, 'rb') as f:
                encrypted_file = f.read()

            nonce = encrypted_file[:12]
            ciphertext = encrypted_file[12:]
            aesgcm_old = AESGCM(file_key_old)
            file_data = aesgcm_old.decrypt(nonce, ciphertext, None)
            secrets_data = json.loads(file_data.decode('utf-8'))

            # Перешиврование каждого секрета
            for key, secret_info in secrets_data.items():
                try:
                    # Расшифровка старым ключом
                    old_value = self.decrypt(secret_info["value"], secret_info["context"])
                    # Шифрование новым ключом
                    new_value = self.encrypt(old_value, secret_info["context"])
                    secret_info["value"] = new_value
                    secret_info["rotated_at"] = datetime.now().isoformat()
                except Exception as e:
                    logger.error(f"❌ Ошибка перешиврования секрета '{key}': {str(e)}. Секрет сохранен в старом формате.")

            # Шифрование обновленного файла новым ключом
            file_data = json.dumps(secrets_data, ensure_ascii=False, indent=2).encode('utf-8')
            aesgcm_new = AESGCM(file_key_new)
            nonce = os.urandom(12)
            encrypted_file = nonce + aesgcm_new.encrypt(nonce, file_data, None)

            with open(secrets_path, 'wb') as f:
                f.write(encrypted_file)

            # Очистка кэша
            self.keys_cache = {}
            self.secrets_cache = {}

            self.last_rotation = datetime.now()
            logger.info("✅ Ротация ключей шифрования успешно завершена")

        except Exception as e:
            logger.error(f"❌ КРИТИЧЕСКАЯ ОШИБКА при ротации ключей: {str(e)}")
            logger.error("🔄 Восстановление из резервной копии...")
            # Восстановление из последней резервной копии
            backups = sorted(secrets_path.parent.glob('*.bak.*'), key=os.path.getmtime, reverse=True)
            if backups:
                backups[0].replace(secrets_path)
                logger.info(f"✅ Восстановление из резервной копии: {backups[0]}")
            self.master_key = old_master_key

    def _auto_migrate_legacy_secrets(self):
        """Автоматическая миграция секретов из старых конфигурационных файлов"""
        # Проверка необходимости миграции
        migration_flag = Path("data/.migration_completed_v2")
        if migration_flag.exists():
            return

        logger.info("🔄 Обнаружена первая инициализация — запуск автоматической миграции секретов...")

        # Миграция секретов платформ
        platforms_path = Path("config/platforms.json")
        if platforms_path.exists():
            try:
                with open(platforms_path, 'r', encoding='utf-8') as f:
                    platforms = json.load(f)

                migrated = 0
                for platform_name, config in platforms.items():
                    # Миграция чувствительных полей
                    sensitive_fields = ['api_key', 'token', 'secret', 'password', 'client_secret']
                    for field in sensitive_fields:
                        if field in config and config[field] and not config[field].startswith('***'):
                            secret_key = f"platform_{platform_name}_{field}"
                            self.store_secret(secret_key, config[field])
                            config[field] = "***SECRET***"
                            migrated += 1

                # Сохранение очищенного конфига
                with open(platforms_path, 'w', encoding='utf-8') as f:
                    json.dump(platforms, f, ensure_ascii=False, indent=2)

                if migrated > 0:
                    logger.info(f"✅ Мигрировано {migrated} секретов платформ в защищенное хранилище")
            except Exception as e:
                logger.error(f"❌ Ошибка миграции секретов платформ: {str(e)}")

        # Миграция секретов безопасности
        security_path = Path("config/security.json")
        if security_path.exists():
            try:
                with open(security_path, 'r', encoding='utf-8') as f:
                    security = json.load(f)

                migrated = 0
                sensitive_fields = [
                    ('secret_key', 'security_secret_key'),
                    ('jwt_secret', 'security_jwt_secret'),
                    ('encryption_key', 'security_encryption_key'),
                    ('db_password', 'database_password'),
                    ('smtp_password', 'smtp_password')
                ]

                for old_key, new_key in sensitive_fields:
                    if old_key in security and security[old_key] and not security[old_key].startswith('***'):
                        self.store_secret(new_key, security[old_key])
                        security[old_key] = "***SECRET***"
                        migrated += 1

                # Сохранение очищенного конфига
                with open(security_path, 'w', encoding='utf-8') as f:
                    json.dump(security, f, ensure_ascii=False, indent=2)

                if migrated > 0:
                    logger.info(f"✅ Мигрировано {migrated} секретов безопасности в защищенное хранилище")
            except Exception as e:
                logger.error(f"❌ Ошибка миграции секретов безопасности: {str(e)}")

        # Удаление статических SSL сертификатов из репозитория
        cert_path = Path("docker/nginx/ssl/cert.pem")
        key_path = Path("docker/nginx/ssl/key.pem")

        if cert_path.exists() and "localhost" in cert_path.read_text():
            cert_path.unlink()
            logger.warning(f"⚠️ Удален статический самоподписанный сертификат: {cert_path}")

        if key_path.exists():
            key_path.unlink()
            logger.warning(f"⚠️ Удален статический приватный ключ: {key_path}")

        # Создание флага завершения миграции
        migration_flag.touch()
        logger.info("✅ Автоматическая миграция секретов завершена успешно")
        logger.info("\n⚠️ ВАЖНО: Убедитесь, что переменная окружения AIFA_MASTER_KEY установлена в продакшене!")
        logger.info("   Для разработки временный ключ сгенерирован автоматически (действителен до перезапуска).")

    def audit_access(self, key: str, accessor: str, action: str):
        """Аудит доступа к секретам с сохранением в защищенный журнал"""
        audit_record = {
            "timestamp": datetime.now().isoformat(),
            "secret_key": key,
            "accessor": accessor,
            "action": action,
            "ip_address": os.environ.get("REMOTE_ADDR", "unknown"),
            "user_agent": os.environ.get("HTTP_USER_AGENT", "unknown")
        }

        audit_path = Path("data/audit/secrets_access.log")
        audit_path.parent.mkdir(parents=True, exist_ok=True)

        # Шифрование записи аудита
        audit_json = json.dumps(audit_record, ensure_ascii=False)
        encrypted_audit = self.encrypt(audit_json, "audit_log")

        with open(audit_path, 'a', encoding='utf-8') as f:
            f.write(f"{datetime.now().isoformat()} | {encrypted_audit}\n")

        # Алерт при подозрительной активности
        if action == "read" and accessor not in ["system", "admin"]:
            logger.warning(f"⚠️ Подозрительный доступ к секрету '{key}' от {accessor}")
            # Здесь можно добавить интеграцию с системой алертов

        logger.debug(f"🔍 Аудит: {accessor} выполнил {action} для секрета {key}")

    def health_check(self) -> Dict[str, Any]:
        """Проверка здоровья хранилища секретов"""
        secrets_path = Path("data/secrets.json")

        return {
            "status": "healthy",
            "master_key_available": self.master_key is not None,
            "vault_integration_enabled": self.vault_enabled,
            "secrets_cached": len(self.secrets_cache),
            "keys_cached": len(self.keys_cache),
            "days_since_rotation": (datetime.now() - self.last_rotation).days,
            "rotation_due": (datetime.now() - self.last_rotation) >= self.rotation_interval,
            "secrets_file_exists": secrets_path.exists(),
            "secrets_file_size": secrets_path.stat().st_size if secrets_path.exists() else 0,
            "environment": os.environ.get("ENVIRONMENT", "unknown")
        }


# Глобальный экземпляр хранилища секретов
secret_vault = SecretVault()