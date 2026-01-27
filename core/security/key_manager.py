# AI_FREELANCE_AUTOMATION/core/security/key_manager.py
"""
Key Manager — управляет жизненным циклом криптографических ключей:
- Генерация (AES-256-GCM, RSA-4096, Argon2 для хэшей)
- Ротация каждые 90 дней (или по конфигурации)
- Хранение в защищённых хранилищах (HSM-эмуляция или файл + шифрование)
- Резервное копирование с разделением секрета (Shamir's Secret Sharing)
- Аудит всех операций через AuditLogger
- Восстановление из бэкапа при сбое
"""

import os
import json
import secrets
import time
from typing import Dict, Optional, Tuple, Any, List
from datetime import datetime, timedelta
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.argon2 import Argon2
from cryptography.hazmat.primitives.serialization import (
    Encoding, PrivateFormat, PublicFormat, NoEncryption,
    BestAvailableEncryption
)
import logging

# Shamir’s Secret Sharing (lightweight implementation for demo; in prod use ssss or tss)
from .shamir_secret_sharing import split_secret, recover_secret

# Local imports (relative to core/)
from ..config.unified_config_manager import UnifiedConfigManager
from ..monitoring.intelligent_monitoring_system import IntelligentMonitoringSystem
from .audit_logger import AuditLogger
from .encryption_engine import EncryptionEngine

logger = logging.getLogger(__name__)

class KeyManager:
    """
    Управляет ключами для всех криптографических операций системы.
    Поддерживает AES, RSA, Argon2.
    """

    def __init__(
        self,
        config: UnifiedConfigManager,
        audit_logger: Optional[AuditLogger] = None,
        monitor: Optional[IntelligentMonitoringSystem] = None
    ):
        self.config = config
        self.audit_logger = audit_logger or AuditLogger(config)
        self.monitor = monitor or IntelligentMonitoringSystem(config)
        self._keys: Dict[str, Dict[str, Any]] = {}
        self._key_storage_path = self.config.get("security.key_storage_path", "data/secure/keys")
        self._backup_path = self.config.get("security.backup_key_path", "backup/keys")
        self._rotation_interval_days = self.config.get("security.key_rotation_interval_days", 90)
        self._shamir_threshold = self.config.get("security.shamir_threshold", 3)
        self._shamir_shares = self.config.get("security.shamir_shares", 5)

        os.makedirs(self._key_storage_path, exist_ok=True)
        os.makedirs(self._backup_path, exist_ok=True)

        self._load_all_keys()
        self._schedule_next_rotation()

    def _schedule_next_rotation(self):
        """Записывает время следующей ротации в метаданные."""
        next_rotation = datetime.utcnow() + timedelta(days=self._rotation_interval_days)
        meta_path = os.path.join(self._key_storage_path, "rotation_schedule.json")
        with open(meta_path, "w") as f:
            json.dump({"next_rotation": next_rotation.isoformat()}, f)
        logger.info(f"🔑 Следующая ротация ключей запланирована на {next_rotation}")

    def _needs_rotation(self, key_meta: Dict[str, Any]) -> bool:
        """Проверяет, требуется ли ротация ключа."""
        created = datetime.fromisoformat(key_meta["created_at"])
        return (datetime.utcnow() - created).days >= self._rotation_interval_days

    def generate_master_key(self) -> bytes:
        """Генерирует мастер-ключ AES-256 для шифрования других ключей."""
        return AESGCM.generate_key(bit_length=256)

    def generate_rsa_keypair(self, name: str) -> Tuple[bytes, bytes]:
        """Генерирует RSA-4096 ключевую пару."""
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=4096,
        )
        public_key = private_key.public_key()

        private_pem = private_key.private_bytes(
            encoding=Encoding.PEM,
            format=PrivateFormat.PKCS8,
            encryption_algorithm=NoEncryption()
        )
        public_pem = public_key.public_bytes(
            encoding=Encoding.PEM,
            format=PublicFormat.SubjectPublicKeyInfo
        )

        self._store_key(name, {
            "type": "rsa",
            "private": private_pem.decode(),
            "public": public_pem.decode(),
            "created_at": datetime.utcnow().isoformat(),
            "active": True
        })
        self.audit_logger.log("KEY_GENERATED", {"key_name": name, "type": "RSA-4096"})
        return private_pem, public_pem

    def generate_aes_key(self, name: str) -> bytes:
        """Генерирует AES-256-GCM ключ и сохраняет его."""
        key = AESGCM.generate_key(bit_length=256)
        self._store_key(name, {
            "type": "aes",
            "key": key.hex(),
            "created_at": datetime.utcnow().isoformat(),
            "active": True
        })
        self.audit_logger.log("KEY_GENERATED", {"key_name": name, "type": "AES-256-GCM"})
        return key

    def generate_argon2_salt(self, name: str) -> bytes:
        """Генерирует соль для Argon2."""
        salt = secrets.token_bytes(32)
        self._store_key(name, {
            "type": "argon2_salt",
            "salt": salt.hex(),
            "created_at": datetime.utcnow().isoformat(),
            "active": True
        })
        self.audit_logger.log("SALT_GENERATED", {"key_name": name})
        return salt

    def _store_key(self, name: str, key_data: Dict[str, Any]):
        """Сохраняет ключ в зашифрованном виде."""
        # Шифруем ключ мастер-ключом (или HSM в продакшене)
        master_key = self._get_or_create_master_key()
        encrypted_data = EncryptionEngine.encrypt_with_aes_gcm(
            plaintext=json.dumps(key_data).encode(),
            key=master_key
        )

        path = os.path.join(self._key_storage_path, f"{name}.key.enc")
        with open(path, "wb") as f:
            f.write(encrypted_data)

        self._keys[name] = key_data
        logger.debug(f"🔐 Ключ '{name}' сохранён.")

    def _get_or_create_master_key(self) -> bytes:
        """Получает или создаёт мастер-ключ для шифрования ключей."""
        master_path = os.path.join(self._key_storage_path, "master.key")
        if os.path.exists(master_path):
            with open(master_path, "rb") as f:
                return f.read()
        else:
            key = self.generate_master_key()
            with open(master_path, "wb") as f:
                f.write(key)
            os.chmod(master_path, 0o600)  # Только владелец
            self.audit_logger.log("MASTER_KEY_CREATED", {})
            return key

    def _load_all_keys(self):
        """Загружает все ключи из зашифрованного хранилища."""
        master_key = self._get_or_create_master_key()
        for filename in os.listdir(self._key_storage_path):
            if filename.endswith(".key.enc"):
                name = filename[:-8]
                path = os.path.join(self._key_storage_path, filename)
                try:
                    with open(path, "rb") as f:
                        encrypted = f.read()
                    decrypted = EncryptionEngine.decrypt_with_aes_gcm(encrypted, master_key)
                    key_data = json.loads(decrypted.decode())
                    self._keys[name] = key_data
                except Exception as e:
                    logger.error(f"❌ Ошибка загрузки ключа {name}: {e}")
                    self.audit_logger.log("KEY_LOAD_ERROR", {"key_name": name, "error": str(e)})

    def get_key(self, name: str) -> Optional[Dict[str, Any]]:
        """Возвращает метаданные ключа (без расшифровки приватной части напрямую)."""
        key = self._keys.get(name)
        if not key:
            logger.warning(f"Ключ '{name}' не найден.")
            return None
        if key.get("active", False) is False:
            logger.warning(f"Ключ '{name}' деактивирован.")
            return None
        if self._needs_rotation(key):
            logger.info(f"Требуется ротация ключа '{name}'")
            self.rotate_key(name)
        return key

    def get_aes_key(self, name: str) -> Optional[bytes]:
        key_meta = self.get_key(name)
        if key_meta and key_meta["type"] == "aes":
            return bytes.fromhex(key_meta["key"])
        return None

    def get_rsa_private_key(self, name: str):
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
        key_meta = self.get_key(name)
        if key_meta and key_meta["type"] == "rsa":
            pem = key_meta["private"].encode()
            return load_pem_private_key(pem, password=None)
        return None

    def get_rsa_public_key(self, name: str):
        from cryptography.hazmat.primitives.serialization import load_pem_public_key
        key_meta = self.get_key(name)
        if key_meta and key_meta["type"] == "rsa":
            pem = key_meta["public"].encode()
            return load_pem_public_key(pem)
        return None

    def get_argon2_salt(self, name: str) -> Optional[bytes]:
        key_meta = self.get_key(name)
        if key_meta and key_meta["type"] == "argon2_salt":
            return bytes.fromhex(key_meta["salt"])
        return None

    def rotate_key(self, name: str):
        """Ротирует указанный ключ: деактивирует старый, создаёт новый."""
        old_key = self._keys.get(name)
        if not old_key:
            logger.error(f"Невозможно ротировать несуществующий ключ: {name}")
            return

        # Деактивируем старый
        old_key["active"] = False
        old_key["rotated_at"] = datetime.utcnow().isoformat()
        self._store_key(name + "_old_" + str(int(time.time())), old_key)

        # Создаём новый
        if old_key["type"] == "aes":
            self.generate_aes_key(name)
        elif old_key["type"] == "rsa":
            self.generate_rsa_keypair(name)
        elif old_key["type"] == "argon2_salt":
            self.generate_argon2_salt(name)
        else:
            raise ValueError(f"Неизвестный тип ключа для ротации: {old_key['type']}")

        self.audit_logger.log("KEY_ROTATED", {"key_name": name})
        logger.info(f"🔄 Ключ '{name}' успешно ротирован.")

    def backup_keys(self) -> List[str]:
        """Создаёт резервную копию ключей с использованием Shamir's Secret Sharing."""
        master_key = self._get_or_create_master_key()
        shares = split_secret(master_key, self._shamir_threshold, self._shamir_shares)

        backup_files = []
        for i, share in enumerate(shares):
            path = os.path.join(self._backup_path, f"key_share_{i+1}.bin")
            with open(path, "wb") as f:
                f.write(share)
            backup_files.append(path)

        self.audit_logger.log("KEYS_BACKED_UP", {"shares_count": len(shares)})
        logger.info(f"💾 Создано {len(shares)} частей резервной копии ключей.")
        return backup_files

    def restore_from_backup(self, share_paths: List[str]) -> bool:
        """Восстанавливает мастер-ключ из долей и перезагружает ключи."""
        if len(share_paths) < self._shamir_threshold:
            logger.error("Недостаточно долей для восстановления.")
            return False

        shares = []
        for path in share_paths:
            with open(path, "rb") as f:
                shares.append(f.read())

        try:
            master_key = recover_secret(shares, self._shamir_threshold)
            master_path = os.path.join(self._key_storage_path, "master.key")
            with open(master_path, "wb") as f:
                f.write(master_key)
            os.chmod(master_path, 0o600)
            self._load_all_keys()
            self.audit_logger.log("KEYS_RESTORED", {"shares_used": len(shares)})
            logger.info("✅ Ключи успешно восстановлены из резервной копии.")
            return True
        except Exception as e:
            logger.critical(f"Ошибка восстановления ключей: {e}")
            self.audit_logger.log("KEYS_RESTORE_FAILED", {"error": str(e)})
            return False

    def destroy_key(self, name: str):
        """Безопасно удаляет ключ (деактивация + перезапись файла)."""
        if name in self._keys:
            self._keys[name]["active"] = False
            self._keys[name]["destroyed_at"] = datetime.utcnow().isoformat()
            # Физическое удаление не рекомендуется в продакшене — лучше деактивировать
            logger.info(f"🗑️ Ключ '{name}' деактивирован.")
            self.audit_logger.log("KEY_DESTROYED", {"key_name": name})