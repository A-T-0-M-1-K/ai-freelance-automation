# Файл: scripts/tools/migrate_secrets_v2.py
# !/usr/bin/env python3
"""
Скрипт миграции существующих секретов в новое защищенное хранилище
с поддержкой автоматического обнаружения и безопасной миграции
"""
import sys
import os
from pathlib import Path

# Добавление пути к проекту
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.security.secret_vault import secret_vault
import json


def main():
    print("=" * 70)
    print("МИГРАЦИЯ СЕКРЕТОВ В ЗАЩИЩЕННОЕ ХРАНИЛИЩЕ v2")
    print("=" * 70)

    # Проверка наличия мастер-ключа
    master_key = os.environ.get("AIFA_MASTER_KEY")
    environment = os.environ.get("ENVIRONMENT", "development")

    if not master_key and environment != "development":
        print("\n❌ КРИТИЧЕСКАЯ ОШИБКА: Переменная окружения AIFA_MASTER_KEY не установлена")
        print("   Для продакшена ОБЯЗАТЕЛЬНО установите надежный мастер-ключ перед миграцией!")
        print("\n   Пример генерации ключа (Linux/Mac):")
        print("   openssl rand -base64 32")
        print("\n   Установка переменной окружения:")
        print("   export AIFA_MASTER_KEY='ваш_сгенерированный_ключ'")
        sys.exit(1)

    if not master_key and environment == "development":
        print("\n⚠️  ВНИМАНИЕ: Режим разработки — будет использован временный мастер-ключ")
        print("   ВРЕМЕННЫЙ КЛЮЧ БУДЕТ УТЕРЯН ПОСЛЕ ПЕРЕЗАПУСКА СИСТЕМЫ!")
        print("   Для постоянного использования установите AIFA_MASTER_KEY")
        response = input("\nПродолжить с временным ключом? (yes/no): ")
        if response.lower() != 'yes':
            print("Миграция отменена")
            sys.exit(0)

    print("\n1. Анализ текущей конфигурации...")

    # Анализ файлов конфигурации
    platforms_path = Path("config/platforms.json")
    security_path = Path("config/security.json")

    secrets_found = 0
    files_to_migrate = []

    if platforms_path.exists():
        with open(platforms_path, 'r', encoding='utf-8') as f:
            platforms = json.load(f)

        for platform_name, config in platforms.items():
            sensitive_fields = ['api_key', 'token', 'secret', 'password', 'client_secret']
            for field in sensitive_fields:
                if field in config and config[field] and not config[field].startswith('***'):
                    secrets_found += 1
        files_to_migrate.append(("platforms", platforms_path))

    if security_path.exists():
        with open(security_path, 'r', encoding='utf-8') as f:
            security = json.load(f)

        sensitive_fields = ['secret_key', 'jwt_secret', 'encryption_key', 'db_password', 'smtp_password']
        for field in sensitive_fields:
            if field in security and security[field] and not security[field].startswith('***'):
                secrets_found += 1
        files_to_migrate.append(("security", security_path))

    print(f"   Найдено секретов для миграции: {secrets_found}")
    print(f"   Файлы для обработки: {', '.join([f[0] for f in files_to_migrate])}")

    if secrets_found == 0:
        print("\nℹ️  Миграция не требуется — все секреты уже защищены")
        sys.exit(0)

    print("\n2. Создание резервных копий...")

    # Создание резервных копий
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = Path(f"backup/migration_backup_{timestamp}")
    backup_dir.mkdir(parents=True, exist_ok=True)

    for file_type, file_path in files_to_migrate:
        backup_path = backup_dir / f"{file_path.name}.bak"
        import shutil
        shutil.copy2(file_path, backup_path)
        print(f"   Резервная копия создана: {backup_path}")

    print(f"\n   Все резервные копии сохранены в: {backup_dir}")

    print("\n3. Выполнение миграции секретов...")

    # Миграция секретов платформ
    if platforms_path.exists():
        with open(platforms_path, 'r', encoding='utf-8') as f:
            platforms = json.load(f)

        migrated = 0
        for platform_name, config in platforms.items():
            sensitive_fields = ['api_key', 'token', 'secret', 'password', 'client_secret']
            for field in sensitive_fields:
                if field in config and config[field] and not config[field].startswith('***'):
                    secret_key = f"platform_{platform_name}_{field}"
                    secret_vault.store_secret(secret_key, config[field])
                    config[field] = "***SECRET***"
                    migrated += 1

        with open(platforms_path, 'w', encoding='utf-8') as f:
            json.dump(platforms, f, ensure_ascii=False, indent=2)

        print(f"   Мигрировано секретов платформ: {migrated}")

    # Миграция секретов безопасности
    if security_path.exists():
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
                secret_vault.store_secret(new_key, security[old_key])
                security[old_key] = "***SECRET***"
                migrated += 1

        with open(security_path, 'w', encoding='utf-8') as f:
            json.dump(security, f, ensure_ascii=False, indent=2)

        print(f"   Мигрировано секретов безопасности: {migrated}")

    # Удаление статических SSL сертификатов
    cert_path = Path("docker/nginx/ssl/cert.pem")
    key_path = Path("docker/nginx/ssl/key.pem")

    removed = 0
    if cert_path.exists() and "localhost" in cert_path.read_text():
        cert_path.unlink()
        removed += 1
        print(f"   Удален статический самоподписанный сертификат")

    if key_path.exists():
        key_path.unlink()
        removed += 1
        print(f"   Удален статический приватный ключ")

    if removed > 0:
        print("\n   ⚠️  ВАЖНО: Для разработки запустите ./docker/nginx/init-ssl.sh для генерации новых сертификатов")
        print("   Для продакшена настройте Let's Encrypt или корпоративный CA")

    print("\n4. Проверка целостности миграции...")

    # Проверка возможности чтения мигрированных секретов
    test_secret = secret_vault.get_secret("security_secret_key", "not_found")
    if test_secret != "not_found":
        print("   ✅ Проверка чтения секретов: УСПЕШНО")
    else:
        print("   ⚠️  Проверка чтения секретов: ЧАСТИЧНО (некоторые секреты могут отсутствовать)")

    # Создание файла флага миграции
    migration_flag = Path("data/.migration_completed_v2")
    migration_flag.touch()

    print("\n" + "=" * 70)
    print("МИГРАЦИЯ ЗАВЕРШЕНА УСПЕШНО!")
    print("=" * 70)
    print("\nСледующие шаги:")
    print("1. Убедитесь, что переменная окружения AIFA_MASTER_KEY установлена в .env файле")
    print("   Пример: AIFA_MASTER_KEY=base64:ваш_закодированный_ключ")
    print("\n2. Добавьте в .gitignore (если еще не добавлено):")
    print("   data/secrets.json")
    print("   data/.migration_completed_v2")
    print("   .env")
    print("\n3. Для продакшена рекомендуется настроить интеграцию с HashiCorp Vault:")
    print("   VAULT_ENABLED=true")
    print("   VAULT_URL=https://your-vault-server:8200")
    print("   VAULT_TOKEN=ваш_токен")
    print("\n4. Резервные копии сохранены в:")
    print(f"   {backup_dir}")
    print("\n⚠️  ВНИМАНИЕ: Удалите резервные копии после проверки работоспособности системы!")


if __name__ == "__main__":
    main()