# AI_FREELANCE_AUTOMATION/core/security/encryption_engine.py
"""
Encryption Engine — performs secure encryption/decryption of data at rest and in transit.
Uses AES-256-GCM for symmetric encryption, RSA-4096 for key wrapping, and HMAC-SHA256 for integrity.
Integrates with KeyManager for secure key lifecycle.
"""

import os
import logging
import hashlib
from typing import Optional, Tuple, Union, Any
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.exceptions import InvalidTag, InvalidSignature
from .key_manager import KeyManager

logger = logging.getLogger(__name__)


class EncryptionEngine:
    """
    Secure encryption engine supporting:
    - AES-256-GCM (authenticated encryption)
    - RSA-4096 (asymmetric key wrapping)
    - HMAC-SHA256 (data integrity verification)
    - Secure key derivation (PBKDF2)
    - Context-aware encryption (with associated data)
    """

    def __init__(self, key_manager: KeyManager):
        self.key_manager = key_manager
        self._aes_key_size = 32  # 256 bits
        self._nonce_size = 12    # 96 bits (recommended for GCM)
        logger.info("🔐 EncryptionEngine initialized")

    def _derive_key_from_password(self, password: str, salt: bytes) -> bytes:
        """Derive a strong AES key from a user password using PBKDF2."""
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=self._aes_key_size,
            salt=salt,
            iterations=600_000,  # OWASP recommended as of 2025
        )
        return kdf.derive(password.encode("utf-8"))

    def encrypt_with_password(
        self,
        plaintext: Union[str, bytes],
        password: str,
        associated_data: Optional[bytes] = None
    ) -> dict:
        """
        Encrypt data using a user-provided password (e.g., for config files or backups).
        Returns a dictionary containing: salt, nonce, ciphertext, and optional auth_tag.
        """
        if isinstance(plaintext, str):
            plaintext = plaintext.encode("utf-8")

        salt = os.urandom(16)
        key = self._derive_key_from_password(password, salt)
        nonce = os.urandom(self._nonce_size)

        aesgcm = AESGCM(key)
        ciphertext = aesgcm.encrypt(nonce, plaintext, associated_data)

        result = {
            "version": "1.0",
            "algorithm": "AES-256-GCM-PBKDF2",
            "salt": salt.hex(),
            "nonce": nonce.hex(),
            "ciphertext": ciphertext.hex(),
        }
        if associated_data:
            result["associated_data"] = associated_data.hex()

        logger.debug("🔒 Data encrypted with password")
        return result

    def decrypt_with_password(
        self,
        payload: dict,
        password: str
    ) -> bytes:
        """Decrypt data previously encrypted with a password."""
        try:
            if payload.get("version") != "1.0":
                raise ValueError("Unsupported encryption format version")

            salt = bytes.fromhex(payload["salt"])
            nonce = bytes.fromhex(payload["nonce"])
            ciphertext = bytes.fromhex(payload["ciphertext"])
            associated_data = (
                bytes.fromhex(payload["associated_data"])
                if "associated_data" in payload else None
            )

            key = self._derive_key_from_password(password, salt)
            aesgcm = AESGCM(key)
            plaintext = aesgcm.decrypt(nonce, ciphertext, associated_data)

            logger.debug("🔓 Data decrypted with password")
            return plaintext
        except (InvalidTag, KeyError, ValueError) as e:
            logger.error(f"❌ Decryption failed: {e}")
            raise ValueError("Decryption failed – invalid password or corrupted data") from e

    def encrypt_with_managed_key(
        self,
        plaintext: Union[str, bytes],
        key_id: str,
        associated_data: Optional[bytes] = None
    ) -> dict:
        """
        Encrypt using a system-managed AES key (rotated automatically by KeyManager).
        Ideal for internal data (logs, configs, client messages).
        """
        if isinstance(plaintext, str):
            plaintext = plaintext.encode("utf-8")

        key_info = self.key_manager.get_symmetric_key(key_id)
        if not key_info:
            raise ValueError(f"No active key found for key_id: {key_id}")

        key = key_info["key"]
        nonce = os.urandom(self._nonce_size)

        aesgcm = AESGCM(key)
        ciphertext = aesgcm.encrypt(nonce, plaintext, associated_data)

        result = {
            "version": "1.0",
            "algorithm": "AES-256-GCM",
            "key_id": key_id,
            "nonce": nonce.hex(),
            "ciphertext": ciphertext.hex(),
        }
        if associated_data:
            result["associated_data"] = associated_data.hex()

        logger.debug(f"🔒 Data encrypted with managed key '{key_id}'")
        return result

    def decrypt_with_managed_key(self, payload: dict) -> bytes:
        """Decrypt data encrypted with a managed key."""
        try:
            if payload.get("version") != "1.0":
                raise ValueError("Unsupported encryption format")

            key_id = payload["key_id"]
            nonce = bytes.fromhex(payload["nonce"])
            ciphertext = bytes.fromhex(payload["ciphertext"])
            associated_data = (
                bytes.fromhex(payload["associated_data"])
                if "associated_data" in payload else None
            )

            key_info = self.key_manager.get_symmetric_key(key_id)
            if not key_info:
                raise ValueError(f"Key '{key_id}' not found or expired")

            key = key_info["key"]
            aesgcm = AESGCM(key)
            plaintext = aesgcm.decrypt(nonce, ciphertext, associated_data)

            logger.debug(f"🔓 Data decrypted with managed key '{key_id}'")
            return plaintext
        except (InvalidTag, KeyError, ValueError) as e:
            logger.error(f"❌ Managed-key decryption failed: {e}")
            raise ValueError("Decryption failed – key mismatch or data corruption") from e

    def wrap_key_for_storage(self, key: bytes, public_key_pem: bytes) -> bytes:
        """
        Wrap a symmetric key using an RSA public key (e.g., for secure backup to cloud).
        Uses OAEP padding with SHA-256 and MGF1.
        """
        public_key = serialization.load_pem_public_key(public_key_pem)
        if not isinstance(public_key, rsa.RSAPublicKey):
            raise TypeError("Only RSA public keys are supported for key wrapping")

        wrapped = public_key.encrypt(
            key,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None
            )
        )
        logger.debug("📦 Symmetric key wrapped with RSA public key")
        return wrapped

    def unwrap_key_with_private_key(self, wrapped_key: bytes, private_key_pem: bytes, password: Optional[str] = None) -> bytes:
        """
        Unwrap a symmetric key using an RSA private key.
        Optionally decrypt the private key if it's password-protected.
        """
        try:
            encryption = (
                serialization.BestAvailableEncryption(password.encode("utf-8"))
                if password else serialization.NoEncryption()
            )
            private_key = serialization.load_pem_private_key(private_key_pem, password=password.encode("utf-8") if password else None)
        except (ValueError, TypeError) as e:
            raise ValueError("Failed to load private key – incorrect password or format") from e

        if not isinstance(private_key, rsa.RSAPrivateKey):
            raise TypeError("Only RSA private keys are supported")

        unwrapped = private_key.decrypt(
            wrapped_key,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None
            )
        )
        logger.debug("🔓 Symmetric key unwrapped with RSA private key")
        return unwrapped

    def compute_hmac(self, data: bytes, key_id: str) -> str:
        """Compute HMAC-SHA256 for data integrity verification."""
        key_info = self.key_manager.get_hmac_key(key_id)
        if not key_info:
            raise ValueError(f"HMAC key '{key_id}' not found")

        h = hmac.new(key_info["key"], data, hashlib.sha256)
        return h.hexdigest()

    def verify_hmac(self, data: bytes, expected_hmac: str, key_id: str) -> bool:
        """Verify HMAC to detect tampering."""
        actual = self.compute_hmac(data, key_id)
        return hmac.compare_digest(actual, expected_hmac)


# Utility for HMAC (needed above)
import hmac  # placed here to avoid top-level import issues in some environments