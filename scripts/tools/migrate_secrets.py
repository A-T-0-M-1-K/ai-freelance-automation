# Файл: scripts/tools/migrate_secrets.py
"""
Скрипт миграции существующих секретов в защищенное хранилище
"""
import json
import os
import sys
from pathlib import Path

# Добавление пути к проекту
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.security.secret_vault import secret_vault


def migrate_platform_secrets():
    """Миграция секретов платформ"""
    platforms_path = "config/platforms.json"

    if not os.path.exists(platforms_path):
        print(f"Файл {platforms_path} не найден")
        return

    with open(platforms_path, 'r', encoding='utf-8') as f:
        platforms = json.load(f)

    migrated = 0
    for platform_name, config in platforms.items():
        # Миграция API ключей
        if 'api_key' in config:
            secret_vault.store_secret(f"platform_{platform_name}_api_key", config['api_key'])
            del config['api_key']
            migrated += 1

        # Миграция токенов
        if 'token' in config:
            secret_vault.store_secret(f"platform_{platform_name}_token", config['token'])
            del config['token']
            migrated += 1

        # Миграция паролей
        if 'password' in config:
            secret_vault.store_secret(f"platform_{platform_name}_password", config['password'])
            del config['password']
            migrated += 1

    # Сохранение очищенного конфига
    with open(platforms_path, 'w', encoding='utf-8') as f:
        json.dump(platforms, f, ensure_ascii=False, indent=2)

    print(f"Мигрировано {migrated} секретов платформ")
    print(f"Очищенный конфиг сохранен в {platforms_path}")
    print("ВАЖНО: Убедитесь, что переменная окружения AIFA_MASTER_KEY установлена перед запуском системы!")


def migrate_security_secrets():
    """Миграция секретов безопасности"""
    security_path = "config/security.json"

    if not os.path.exists(security_path):
        print(f"Файл {security_path} не найден")
        return

    with open(security_path, 'r', encoding='utf-8') as f:
        security = json.load(f)

    migrated = 0
    secrets_to_migrate = [
        ('secret_key', 'security_secret_key'),
        ('jwt_secret', 'security_jwt_secret'),
        ('encryption_key', 'security_encryption_key'),
        ('db_password', 'database_password')
    ]

    for old_key, new_key in secrets_to_migrate:
        if old_key in security:
            secret_vault.store_secret(new_key, security[old_key])
            del security[old_key]
            migrated += 1

    # Сохранение очищенного конфига
    with open(security_path, 'w', encoding='utf-8') as f:
        json.dump(security, f, ensure_ascii=False, indent=2)

    print(f"Мигрировано {migrated} секретов безопасности")
    print(f"Очищенный конфиг сохранен в {security_path}")


def remove_static_ssl_certs():
    """Удаление статических SSL сертификатов из репозитория"""
    cert_path = "docker/nginx/ssl/cert.pem"
    key_path = "docker/nginx/ssl/key.pem"

    if os.path.exists(cert_path):
        os.remove(cert_path)
        print(f"Удален статический сертификат: {cert_path}")

    if os.path.exists(key_path):
        os.remove(key_path)
        print(f"Удален статический ключ: {key_path}")

    print("\nВАЖНО: Для продакшена используйте Let's Encrypt или корпоративный CA!")
    print("Для разработки запустите: ./docker/nginx/init-ssl.sh")


def main():
    print("=" * 60)
    print("Миграция секретов в защищенное хранилище")
    print("=" * 60)

    # Проверка наличия мастер-ключа
    master_key = os.environ.get("AIFA_MASTER_KEY")
    if not master_key:
        print("\n⚠️  ВНИМАНИЕ: Переменная окружения AIFA_MASTER_KEY не установлена")
        print("Будет использован временный ключ для разработки.")
        print("Для продакшена УСТАНОВИТЕ надежный мастер-ключ перед миграцией!")
        response = input("\nПродолжить с временным ключом? (yes/no): ")
        if response.lower() != 'yes':
            print("Миграция отменена")
            return

    print("\n1. Миграция секретов платформ...")
    migrate_platform_secrets()

    print("\n2. Миграция секретов безопасности...")
    migrate_security_secrets()

    print("\n3. Удаление статических SSL сертификатов...")
    remove_static_ssl_certs()

    print("\n" + "=" * 60)
    print("Миграция завершена успешно!")
    print("=" * 60)
    print("\nСледующие шаги:")
    print("1. Установите переменную окружения AIFA_MASTER_KEY в production")
    print("2. Добавьте .env файл в .gitignore если еще не добавлен")
    print("3. Убедитесь, что data/secrets.json добавлен в .gitignore")
    print("4. Для продакшена настройте интеграцию с HashiCorp Vault или AWS Secrets Manager")


if __name__ == "__main__":
    main()