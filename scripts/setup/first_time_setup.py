#!/usr/bin/env python3
"""
First-time setup script for AI Freelance Automation System.
Idempotent: safe to run multiple times.
Performs:
  - Directory structure validation/creation
  - Environment setup (.env from .env.example)
  - Initial config generation & validation
  - Log/cache/backup directories initialization
  - Security key generation (if missing)
  - Model download prompts (optional)
"""

import os
import sys
import shutil
import logging
import secrets
from pathlib import Path
from typing import List, Set

# Add project root to path for internal imports
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

from core.config.unified_config_manager import UnifiedConfigManager
from core.security.advanced_crypto_system import AdvancedCryptoSystem
from scripts.setup.setup_environment import _ensure_directory

# Configure minimal logging before full system init
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [SETUP] %(levelname)s: %(message)s",
    handlers=[
        logging.FileHandler(PROJECT_ROOT / "logs" / "app" / "setup.log", mode="a"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("FirstTimeSetup")


class FirstTimeSetup:
    REQUIRED_DIRS = [
        "logs/app",
        "logs/ai",
        "logs/errors",
        "logs/monitoring",
        "data/backup",
        "data/cache",
        "data/clients",
        "data/conversations",
        "data/jobs",
        "data/projects",
        "data/finances",
        "data/settings",
        "data/stats",
        "ai/temp",
        "ai/logs",
        "backup/automatic/daily",
        "backup/automatic/weekly",
        "backup/automatic/monthly",
        "backup/manual",
    ]

    def __init__(self):
        self.project_root = PROJECT_ROOT
        self.env_path = self.project_root / ".env"
        self.env_example_path = self.project_root / ".env.example"

    def run(self) -> bool:
        """Execute full first-time setup."""
        logger.info("🚀 Starting first-time setup for AI Freelance Automation System...")

        try:
            self._create_directory_structure()
            self._setup_environment_file()
            self._initialize_security_keys()
            self._validate_and_generate_configs()
            self._ensure_log_rotation()
            self._prompt_optional_steps()

            logger.info("✅ First-time setup completed successfully!")
            return True

        except Exception as e:
            logger.critical(f"💥 Setup failed: {e}", exc_info=True)
            return False

    def _create_directory_structure(self):
        """Create all required directories if they don't exist."""
        logger.info("📁 Creating directory structure...")
        for rel_path in self.REQUIRED_DIRS:
            full_path = self.project_root / rel_path
            _ensure_directory(full_path)
        logger.info(f"✅ Created {len(self.REQUIRED_DIRS)} directories.")

    def _setup_environment_file(self):
        """Copy .env.example to .env if not exists."""
        if not self.env_path.exists():
            if not self.env_example_path.exists():
                raise FileNotFoundError("Missing .env.example — cannot initialize environment.")
            shutil.copy(self.env_example_path, self.env_path)
            logger.info("🔐 Generated .env from .env.example")
        else:
            logger.info("🔑 .env already exists — skipping generation.")

    def _initialize_security_keys(self):
        """Generate master encryption key if missing."""
        key_path = self.project_root / "data" / "settings" / "master.key"
        if not key_path.exists():
            key_path.parent.mkdir(parents=True, exist_ok=True)
            # Generate cryptographically secure 256-bit key (32 bytes)
            key = secrets.token_bytes(32)
            with open(key_path, "wb") as f:
                f.write(key)
            # Restrict permissions (owner-only read/write)
            os.chmod(key_path, 0o600)
            logger.info("🔐 Generated master encryption key at data/settings/master.key")
        else:
            logger.info("🔑 Master encryption key already exists.")

    def _validate_and_generate_configs(self):
        """Initialize and validate all system configurations."""
        logger.info("⚙️ Initializing configuration system...")
        try:
            config_manager = UnifiedConfigManager()
            # Trigger validation and migration if needed
            config_manager.validate_all()
            config_manager.migrate_if_needed()
            logger.info("✅ All configurations validated and ready.")
        except Exception as e:
            logger.error(f"⚠️ Config validation issue (non-fatal): {e}")
            # Still proceed — user can fix later

    def _ensure_log_rotation(self):
        """Ensure log rotation config exists."""
        log_config = self.project_root / "logs" / "log_rotation_config.json"
        if not log_config.exists():
            default_config = {
                "version": 1,
                "disable_existing_loggers": False,
                "formatters": {
                    "standard": {
                        "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
                    }
                },
                "handlers": {
                    "rotating_file": {
                        "class": "logging.handlers.RotatingFileHandler",
                        "filename": "logs/app/application.log",
                        "maxBytes": 10485760,  # 10 MB
                        "backupCount": 5,
                        "formatter": "standard"
                    }
                },
                "root": {
                    "level": "INFO",
                    "handlers": ["rotating_file"]
                }
            }
            import json
            with open(log_config, "w") as f:
                json.dump(default_config, f, indent=2)
            logger.info("📄 Created default log rotation config.")

    def _prompt_optional_steps(self):
        """Prompt user for optional post-setup actions."""
        logger.info("\n💡 Optional next steps:")
        logger.info("  - Run `python scripts/tools/model_downloader.py` to download AI models")
        logger.info("  - Review and edit .env for API keys and platform credentials")
        logger.info("  - Run `python main.py --test-mode` to verify installation")
        logger.info("  - Execute `make install-dev` if using development dependencies\n")


def main():
    setup = FirstTimeSetup()
    success = setup.run()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()