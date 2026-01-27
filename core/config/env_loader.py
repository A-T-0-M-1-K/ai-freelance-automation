# AI_FREELANCE_AUTOMATION/core/config/env_loader.py
"""
Secure environment variables loader with type conversion and validation.
Supports .env files, encrypted .env, and system environment precedence.
Integrates with UnifiedConfigManager for seamless configuration flow.
"""

import os
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Union, cast
from dotenv import load_dotenv, dotenv_values
from ..security.advanced_crypto_system import AdvancedCryptoSystem

logger = logging.getLogger(__name__)


class EnvLoader:
    """
    Secure and intelligent environment variable loader.

    Features:
    - Loads from .env, .env.local, .env.{profile}
    - Supports encrypted .env.enc files (AES-256-GCM)
    - Type-safe conversion (bool, int, float, list, dict)
    - Respects OS environment precedence
    - Integrates with security subsystem for decryption
    """

    def __init__(
            self,
            base_path: Union[str, Path] = ".",
            profile: Optional[str] = None,
            crypto_system: Optional["AdvancedCryptoSystem"] = None
    ):
        self.base_path = Path(base_path).resolve()
        self.profile = profile
        self.crypto = crypto_system
        self._cache: Dict[str, Any] = {}
        self._loaded = False

    def load(self) -> Dict[str, Any]:
        """Load and parse all environment variables securely."""
        if self._loaded:
            return self._cache.copy()

        logger.info("🔐 Loading environment variables...")

        # 1. Load from system environment (highest precedence)
        env_vars: Dict[str, str] = dict(os.environ)

        # 2. Load from .env files in order of precedence
        env_files = self._get_env_file_paths()
        for file_path in reversed(env_files):  # .env.local overrides .env
            if not file_path.exists():
                continue

            if file_path.name.endswith(".enc"):
                if not self.crypto:
                    logger.warning(f"Encrypted env file {file_path} found but no crypto system provided. Skipping.")
                    continue
                decrypted_content = self._decrypt_env_file(file_path)
                if decrypted_content:
                    parsed = self._parse_env_content(decrypted_content)
                    env_vars.update(parsed)
            else:
                # Standard .env file
                values = dotenv_values(file_path, encoding="utf-8")
                # Filter out None values (dotenv returns None for empty lines)
                clean_values = {k: v for k, v in values.items() if v is not None}
                env_vars.update(clean_values)

        # 3. Convert types safely
        typed_vars = self._convert_types(env_vars)

        # 4. Cache and mark as loaded
        self._cache = typed_vars
        self._loaded = True

        logger.info(f"✅ Successfully loaded {len(typed_vars)} environment variables.")
        return typed_vars.copy()

    def _get_env_file_paths(self) -> list[Path]:
        """Return ordered list of possible .env file paths (lowest to highest precedence)."""
        files = [
            self.base_path / ".env",
            self.base_path / ".env.default",
        ]
        if self.profile:
            files.append(self.base_path / f".env.{self.profile}")
        files.append(self.base_path / ".env.local")
        if self.profile:
            files.append(self.base_path / f".env.{self.profile}.local")
        return files

    def _decrypt_env_file(self, path: Path) -> Optional[str]:
        """Decrypt .env.enc file using the crypto system."""
        try:
            with open(path, "rb") as f:
                encrypted_data = f.read()
            decrypted = self.crypto.decrypt(encrypted_data)
            return decrypted.decode("utf-8")
        except Exception as e:
            logger.error(f"❌ Failed to decrypt {path}: {e}")
            return None

    def _parse_env_content(self, content: str) -> Dict[str, str]:
        """Parse raw .env content into key-value pairs."""
        values = {}
        for line_num, line in enumerate(content.strip().splitlines(), 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                logger.warning(f"⚠️ Invalid line in env content at line {line_num}: {line}")
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip("\"'")  # Remove quotes
            values[key] = value
        return values

    def _convert_types(self, raw_vars: Dict[str, str]) -> Dict[str, Any]:
        """Convert string values to appropriate types with safety."""
        converted = {}
        for key, value in raw_vars.items():
            if not isinstance(value, str):
                converted[key] = value
                continue

            # Boolean
            if value.lower() in ("true", "1", "yes", "on"):
                converted[key] = True
            elif value.lower() in ("false", "0", "no", "off"):
                converted[key] = False
            # Integer
            elif value.isdigit() or (value.startswith("-") and value[1:].isdigit()):
                converted[key] = int(value)
            # Float
            elif self._is_float(value):
                converted[key] = float(value)
            # List (comma-separated)
            elif "," in value and "[" not in value and "{" not in value:
                converted[key] = [item.strip() for item in value.split(",") if item.strip()]
            # Keep as string otherwise
            else:
                converted[key] = value
        return converted

    @staticmethod
    def _is_float(value: str) -> bool:
        try:
            float(value)
            return True
        except ValueError:
            return False

    def get(self, key: str, default: Any = None) -> Any:
        """Get a single environment variable with fallback."""
        if not self._loaded:
            self.load()
        return self._cache.get(key, default)

    def reload(self) -> None:
        """Force reload environment variables."""
        self._loaded = False
        self._cache.clear()
        self.load()


# Singleton instance for global use (optional, but safe)
_env_loader_instance: Optional[EnvLoader] = None


def get_env_loader(
        base_path: Union[str, Path] = ".",
        profile: Optional[str] = None,
        crypto_system: Optional["AdvancedCryptoSystem"] = None
) -> EnvLoader:
    """Factory function to get or create a shared EnvLoader instance."""
    global _env_loader_instance
    if _env_loader_instance is None:
        _env_loader_instance = EnvLoader(
            base_path=base_path,
            profile=profile,
            crypto_system=crypto_system
        )
    return _env_loader_instance