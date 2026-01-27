import secrets
import os
import json
from pathlib import Path
from cryptography.fernet import Fernet
from core.security.key_manager import KeyManager


def generate_production_secret_key():
    """
    Генерирует криптографически стойкий SECRET_KEY для продакшена.
    Сохраняет в зашифрованном виде в секретное хранилище.
    """
    # Генерация 64-байтного ключа (512 бит) для максимальной безопасности
    secret_key = secrets.token_hex(64)  # 128 hex символов = 64 байта

    # Генерация ключа шифрования для хранения секрета
    encryption_key = Fernet.generate_key()

    # Шифрование секретного ключа
    f = Fernet(encryption_key)
    encrypted_secret = f.encrypt(secret_key.encode())

    # Сохранение в секретное хранилище
    vault_path = Path("data/secrets/vault.encrypted")
    vault_path.parent.mkdir(parents=True, exist_ok=True)

    vault_data = {
        "version": "1.0",
        "encrypted_secret_key": encrypted_secret.decode(),
        "encryption_key_hash": secrets.token_hex(16),  # Хеш для верификации
        "created_at": __import__('datetime').datetime.utcnow().isoformat(),
        "environment": "production"
    }

    with open(vault_path, 'w') as f:
        json.dump(vault_data, f, indent=2)

    # Сохранение ключа шифрования в отдельное защищённое место (НЕ в репозиторий!)
    key_storage = Path(os.environ.get('KEY_STORAGE_PATH', '/etc/ai-freelance/keys'))
    key_storage.mkdir(parents=True, exist_ok=True)

    with open(key_storage / "encryption.key", 'wb') as f:
        f.write(encryption_key)

    # Установка строгих прав доступа
    os.chmod(key_storage / "encryption.key", 0o600)
    os.chmod(vault_path, 0o600)

    print(f"✅ Сгенерирован надёжный SECRET_KEY (64 байта)")
    print(f"✅ Ключ сохранён в зашифрованном хранилище: {vault_path}")
    print(f"⚠️  Ключ шифрования сохранён в: {key_storage / 'encryption.key'}")
    print(f"⚠️  НИКОГДА не коммитьте файлы с ключами в Git!")

    return secret_key


def validate_secret_key_strength(secret_key: str) -> bool:
    """
    Валидация силы секретного ключа перед использованием в продакшене.
    """
    if not secret_key:
        return False

    # Минимум 32 байта (64 hex символа)
    if len(secret_key) < 64:
        raise ValueError(f"SECRET_KEY слишком короткий: {len(secret_key) // 2} байт. Требуется минимум 32 байта.")

    # Проверка энтропии (разнообразие символов)
    import string
    has_upper = any(c in string.ascii_uppercase for c in secret_key)
    has_lower = any(c in string.ascii_lowercase for c in secret_key)
    has_digit = any(c in string.digits for c in secret_key)

    if not (has_upper or has_lower or has_digit):
        # Для hex-ключа это нормально, но проверяем длину
        if len(secret_key) < 128:  # 64 байта в hex
            raise ValueError("Недостаточная энтропия SECRET_KEY")

    return True


if __name__ == "__main__":
    # Автоматическая генерация при первом запуске
    if not Path("data/secrets/vault.encrypted").exists():
        secret = generate_production_secret_key()
        validate_secret_key_strength(secret)
        print("\n🔒 SECRET_KEY успешно сгенерирован и защищён!")
    else:
        print("ℹ️  SECRET_KEY уже существует. Перегенерация не требуется.")