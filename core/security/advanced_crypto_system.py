# AI_FREELANCE_AUTOMATION/core/security/advanced_crypto_system.py
"""
Advanced cryptographic system implementing:
- AES-256-GCM for data encryption
- Argon2id for password hashing
- RSA-4096 for asymmetric operations
- HMAC-SHA256 for data integrity

Designed for GDPR, PCI DSS, HIPAA compliance.
All secrets are handled via KeyManager to avoid leakage.
"""

import base64
import hashlib
import hmac
import logging
import os
from typing import Optional, Tuple, Union, Any
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import hashes
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

# Local imports (relative to core)
from .key_manager import KeyManager
from .audit_logger import AuditLogger

logger = logging.getLogger(__name__)


class AdvancedCryptoSystem:
    """
    Unified cryptographic engine for the entire application.
    All cryptographic operations must go through this class.
    """

    def __init__(self, key_manager: Optional[KeyManager] = None):
        """
        Initialize crypto system with optional KeyManager.
        If not provided, creates a default one (not recommended in production).
        """
        self.key_manager = key_manager or KeyManager()
        self.audit_logger = AuditLogger()
        self._argon2_hasher = PasswordHasher(
            time_cost=3,
            memory_cost=65536,  # 64 MB
            parallelism=2,
            hash_len=32,
            salt_len=16
        )
        logger.info("🔐 AdvancedCryptoSystem initialized.")

    # === SYMMETRIC ENCRYPTION (AES-256-GCM) ===

    def encrypt_data(self, plaintext: Union[str, bytes], context: str = "") -> str:
        """
        Encrypt data using AES-256-GCM.
        Returns base64-encoded string: nonce + ciphertext + tag.

        Args:
            plaintext: Data to encrypt (str or bytes)
            context: Human-readable context for audit log (e.g., 'client_profile')

        Returns:
            Base64-encoded encrypted payload
        """
        if isinstance(plaintext, str):
            data = plaintext.encode('utf-8')
        else:
            data = plaintext

        key = self.key_manager.get_symmetric_key("aes_gcm_256")
        aesgcm = AESGCM(key)
        nonce = os.urandom(12)  # 96-bit nonce per NIST SP 800-38D

        ciphertext_and_tag = aesgcm.encrypt(nonce, data, None)
        payload = nonce + ciphertext_and_tag
        encoded = base64.b64encode(payload).decode('ascii')

        self.audit_logger.log_crypto_operation(
            operation="encrypt",
            algorithm="AES-256-GCM",
            context=context,
            success=True
        )
        return encoded

    def decrypt_data(self, encrypted_b64: str, context: str = "") -> str:
        """
        Decrypt AES-256-GCM encrypted data.

        Args:
            encrypted_b64: Base64-encoded payload from encrypt_data()
            context: Context for audit

        Returns:
            Decrypted UTF-8 string

        Raises:
            ValueError: If decryption fails (tampering or wrong key)
        """
        try:
            payload = base64.b64decode(encrypted_b64)
            if len(payload) < 12:
                raise ValueError("Invalid payload length")

            nonce = payload[:12]
            ciphertext_and_tag = payload[12:]

            key = self.key_manager.get_symmetric_key("aes_gcm_256")
            aesgcm = AESGCM(key)
            plaintext = aesgcm.decrypt(nonce, ciphertext_and_tag, None)

            self.audit_logger.log_crypto_operation(
                operation="decrypt",
                algorithm="AES-256-GCM",
                context=context,
                success=True
            )
            return plaintext.decode('utf-8')

        except Exception as e:
            self.audit_logger.log_crypto_operation(
                operation="decrypt",
                algorithm="AES-256-GCM",
                context=context,
                success=False,
                error=str(e)
            )
            raise ValueError(f"Decryption failed: {e}") from e

    # === PASSWORD HASHING (Argon2id) ===

    def hash_password(self, password: str) -> str:
        """Hash password using Argon2id."""
        hashed = self._argon2_hasher.hash(password)
        self.audit_logger.log_crypto_operation(
            operation="hash_password",
            algorithm="Argon2id",
            success=True
        )
        return hashed

    def verify_password(self, password: str, hashed: str) -> bool:
        """Verify password against Argon2id hash."""
        try:
            self._argon2_hasher.verify(hashed, password)
            self.audit_logger.log_crypto_operation(
                operation="verify_password",
                algorithm="Argon2id",
                success=True
            )
            return True
        except VerifyMismatchError:
            self.audit_logger.log_crypto_operation(
                operation="verify_password",
                algorithm="Argon2id",
                success=False,
                error="Password mismatch"
            )
            return False

    # === ASYMMETRIC CRYPTOGRAPHY (RSA-4096) ===

    def generate_rsa_keypair(self, name: str) -> None:
        """Generate and store RSA-4096 key pair under given name."""
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=4096,
        )
        self.key_manager.store_rsa_keypair(name, private_key)
        self.audit_logger.log_crypto_operation(
            operation="generate_rsa_keypair",
            algorithm="RSA-4096",
            context=name,
            success=True
        )

    def sign_data(self, data: Union[str, bytes], key_name: str) -> str:
        """Sign data using RSA private key (PSS + SHA-256)."""
        if isinstance(data, str):
            data = data.encode('utf-8')

        private_key = self.key_manager.get_rsa_private_key(key_name)
        signature = private_key.sign(
            data,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH
            ),
            hashes.SHA256()
        )
        encoded = base64.b64encode(signature).decode('ascii')
        self.audit_logger.log_crypto_operation(
            operation="sign",
            algorithm="RSA-4096-PSS-SHA256",
            context=key_name,
            success=True
        )
        return encoded

    def verify_signature(self, data: Union[str, bytes], signature_b64: str, key_name: str) -> bool:
        """Verify RSA signature using stored public key."""
        if isinstance(data, str):
            data = data.encode('utf-8')
        signature = base64.b64decode(signature_b64)

        public_key = self.key_manager.get_rsa_public_key(key_name)
        try:
            public_key.verify(
                signature,
                data,
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.MAX_LENGTH
                ),
                hashes.SHA256()
            )
            self.audit_logger.log_crypto_operation(
                operation="verify_signature",
                algorithm="RSA-4096-PSS-SHA256",
                context=key_name,
                success=True
            )
            return True
        except Exception as e:
            self.audit_logger.log_crypto_operation(
                operation="verify_signature",
                algorithm="RSA-4096-PSS-SHA256",
                context=key_name,
                success=False,
                error=str(e)
            )
            return False

    # === DATA INTEGRITY (HMAC-SHA256) ===

    def compute_hmac(self, data: Union[str, bytes], context: str = "") -> str:
        """Compute HMAC-SHA256 using a secret key."""
        if isinstance(data, str):
            data = data.encode('utf-8')
        key = self.key_manager.get_hmac_key("hmac_sha256")
        mac = hmac.new(key, data, hashlib.sha256).digest()
        encoded = base64.b64encode(mac).decode('ascii')

        self.audit_logger.log_crypto_operation(
            operation="compute_hmac",
            algorithm="HMAC-SHA256",
            context=context,
            success=True
        )
        return encoded

    def verify_hmac(self, data: Union[str, bytes], expected_hmac_b64: str, context: str = "") -> bool:
        """Verify HMAC in constant-time to prevent timing attacks."""
        if isinstance(data, str):
            data = data.encode('utf-8')
        key = self.key_manager.get_hmac_key("hmac_sha256")
        computed = hmac.new(key, data, hashlib.sha256).digest()
        expected = base64.b64decode(expected_hmac_b64)

        is_valid = hmac.compare_digest(computed, expected)
        self.audit_logger.log_crypto_operation(
            operation="verify_hmac",
            algorithm="HMAC-SHA256",
            context=context,
            success=is_valid
        )
        return is_valid

    # === UTILITY ===

    def rotate_keys(self) -> None:
        """Trigger key rotation via KeyManager."""
        self.key_manager.rotate_all_keys()
        logger.info("🔄 Cryptographic keys rotated.")
        self.audit_logger.log_crypto_operation(
            operation="rotate_keys",
            algorithm="N/A",
            success=True
        )