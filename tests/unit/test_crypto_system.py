# AI_FREELANCE_AUTOMATION/tests/unit/test_crypto_system.py
"""
Unit tests for the AdvancedCryptoSystem in core.security.advanced_crypto_system.
Ensures cryptographic operations are secure, reversible, and compliant with system standards.
"""

import os
import tempfile
import pytest
from unittest.mock import patch, MagicMock

# Import the actual system under test
from core.security.advanced_crypto_system import AdvancedCryptoSystem


class TestAdvancedCryptoSystem:
    """Test suite for AdvancedCryptoSystem functionality."""

    def setup_method(self):
        """Set up a clean crypto instance before each test."""
        self.crypto = AdvancedCryptoSystem()

    def teardown_method(self):
        """Clean up any temporary state if needed."""
        pass

    def test_encrypt_decrypt_symmetric(self):
        """Test AES-256-GCM encryption and decryption with authenticated data."""
        plaintext = "Confidential freelance data: client requirements and payment details."
        associated_data = b"freelance_job_12345"

        # Encrypt
        ciphertext, nonce, tag = self.crypto.encrypt_symmetric(
            plaintext.encode('utf-8'),
            associated_data=associated_data
        )

        # Decrypt
        decrypted = self.crypto.decrypt_symmetric(
            ciphertext,
            nonce,
            tag,
            associated_data=associated_data
        )

        assert decrypted.decode('utf-8') == plaintext

    def test_encrypt_decrypt_with_different_associated_data_fails(self):
        """Ensure decryption fails if associated data is tampered with."""
        plaintext = "Secret message"
        ad1 = b"correct_ad"
        ad2 = b"wrong_ad"

        ciphertext, nonce, tag = self.crypto.encrypt_symmetric(
            plaintext.encode('utf-8'),
            associated_data=ad1
        )

        with pytest.raises(ValueError, match="Authentication failed"):
            self.crypto.decrypt_symmetric(ciphertext, nonce, tag, associated_data=ad2)

    def test_hash_password_argon2(self):
        """Test password hashing with Argon2."""
        password = "VerySecureP@ssw0rd!"
        hash1 = self.crypto.hash_password(password)
        hash2 = self.crypto.hash_password(password)

        # Argon2 uses random salt → hashes must differ
        assert hash1 != hash2

        # But both must verify correctly
        assert self.crypto.verify_password(password, hash1) is True
        assert self.crypto.verify_password(password, hash2) is True

        # Wrong password should fail
        assert self.crypto.verify_password("Wrong!", hash1) is False

    def test_generate_and_verify_hmac(self):
        """Test HMAC-SHA256 for data integrity."""
        data = b"Order ID: 98765; Amount: $500"
        key = os.urandom(32)

        hmac1 = self.crypto.generate_hmac(data, key)
        hmac2 = self.crypto.generate_hmac(data, key)

        assert hmac1 == hmac2
        assert self.crypto.verify_hmac(data, hmac1, key) is True

        # Tampered data should fail verification
        tampered = b"Order ID: 98765; Amount: $9999"
        assert self.crypto.verify_hmac(tampered, hmac1, key) is False

    def test_rsa_key_generation_and_asymmetric_encryption(self):
        """Test RSA-4096 key generation and asymmetric encryption/decryption."""
        message = b"Encrypted contract terms."

        # Generate fresh key pair
        private_key, public_key = self.crypto.generate_rsa_keypair(key_size=4096)

        # Encrypt with public key
        ciphertext = self.crypto.encrypt_asymmetric(message, public_key)

        # Decrypt with private key
        decrypted = self.crypto.decrypt_asymmetric(ciphertext, private_key)

        assert decrypted == message

    def test_key_serialization_and_loading(self):
        """Test saving and loading keys securely."""
        private_key, public_key = self.crypto.generate_rsa_keypair()

        with tempfile.TemporaryDirectory() as tmpdir:
            priv_path = os.path.join(tmpdir, "private.pem")
            pub_path = os.path.join(tmpdir, "public.pem")

            # Save
            self.crypto.save_private_key(private_key, priv_path)
            self.crypto.save_public_key(public_key, pub_path)

            # Load
            loaded_private = self.crypto.load_private_key(priv_path)
            loaded_public = self.crypto.load_public_key(pub_path)

            # Verify they work
            test_msg = b"Key persistence test"
            encrypted = self.crypto.encrypt_asymmetric(test_msg, loaded_public)
            decrypted = self.crypto.decrypt_asymmetric(encrypted, loaded_private)
            assert decrypted == test_msg

    def test_secure_random_generation(self):
        """Test secure random byte generation."""
        rand1 = self.crypto.secure_random_bytes(32)
        rand2 = self.crypto.secure_random_bytes(32)

        assert len(rand1) == 32
        assert len(rand2) == 32
        assert isinstance(rand1, bytes)
        assert rand1 != rand2  # Extremely unlikely to be equal

    @patch("core.security.advanced_crypto_system.os.urandom")
    def test_fallback_to_secrets_if_os_urandom_fails(self, mock_urandom):
        """Ensure fallback to secrets module if os.urandom fails (edge case)."""
        mock_urandom.side_effect = OSError("OS urandom unavailable")

        crypto = AdvancedCryptoSystem()
        rand = crypto.secure_random_bytes(16)

        assert len(rand) == 16
        assert isinstance(rand, bytes)

    def test_encrypt_large_data(self):
        """Test encryption of large payloads (e.g., deliverables)."""
        large_data = b"A" * (10 * 1024 * 1024)  # 10 MB
        ad = b"large_file_upload"

        ciphertext, nonce, tag = self.crypto.encrypt_symmetric(large_data, associated_data=ad)
        decrypted = self.crypto.decrypt_symmetric(ciphertext, nonce, tag, associated_data=ad)

        assert decrypted == large_data

    def test_thread_safety_of_crypto_operations(self):
        """Basic check that crypto operations don't share mutable state."""
        from concurrent.futures import ThreadPoolExecutor

        def worker():
            return self.crypto.hash_password("test"), self.crypto.secure_random_bytes(8)

        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(lambda _: worker(), range(10)))

        # All hashes should verify, all randoms should be unique
        for pwd_hash, rand in results:
            assert self.crypto.verify_password("test", pwd_hash)
            assert len(rand) == 8