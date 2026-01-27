#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
System Configuration Script
===========================

Automatically configures the AI Freelance Automation system:
- Creates missing directories
- Generates default config files from templates
- Validates configs against JSON schemas
- Initializes cryptographic keys if needed
- Sets secure file permissions

This script is idempotent and safe to run multiple times.
"""

import os
import json
import sys
import logging
import shutil
from pathlib import Path
from typing import List, Dict, Any

# Add project root to path for imports
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

# Import core components
try:
    from core.config.unified_config_manager import UnifiedConfigManager
    from core.security.key_manager import KeyManager
    from core.config.config_validator import ConfigValidator
except ImportError as e:
    print(f"❌ Critical import failed: {e}")
    print("Ensure you're running from the project root or virtual environment is activated.")
    sys.exit(1)

# Setup logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(PROJECT_ROOT / "logs" / "app" / "setup.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("ConfigureSystem")


class SystemConfigurer:
    """Handles full system configuration initialization."""

    def __init__(self):
        self.project_root = PROJECT_ROOT
        self.config_dir = self.project_root / "config"
        self.data_dir = self.project_root / "data"
        self.logs_dir = self.project_root / "logs"
        self.backup_dir = self.project_root / "backup"
        self.required_dirs = [
            self.data_dir / "clients",
            self.data_dir / "jobs",
            self.data_dir / "projects",
            self.data_dir / "finances",
            self.data_dir / "conversations",
            self.data_dir / "exports" / "reports",
            self.data_dir / "exports" / "invoices",
            self.logs_dir / "ai",
            self.logs_dir / "app",
            self.logs_dir / "errors",
            self.logs_dir / "monitoring",
            self.backup_dir / "automatic" / "daily",
            self.backup_dir / "automatic" / "weekly",
            self.backup_dir / "manual",
        ]

    def run(self) -> bool:
        """Execute full system configuration."""
        logger.info("🚀 Starting system configuration...")
        try:
            self._create_directories()
            self._initialize_config_files()
            self._validate_all_configs()
            self._initialize_crypto_keys()
            self._set_secure_permissions()
            logger.info("✅ System configuration completed successfully!")
            return True
        except Exception as e:
            logger.exception(f"💥 Configuration failed: {e}")
            return False

    def _create_directories(self):
        """Create all required directories if they don't exist."""
        logger.info("📁 Creating required directories...")
        for dir_path in self.required_dirs:
            dir_path.mkdir(parents=True, exist_ok=True)
            logger.debug(f"  → {dir_path}")

    def _initialize_config_files(self):
        """Generate missing config files from defaults or templates."""
        logger.info("⚙️ Initializing configuration files...")

        # Default config values
        defaults = {
            "settings.json": {
                "language": "en",
                "timezone": "UTC",
                "auto_update": True,
                "max_concurrent_jobs": 50,
                "enable_self_healing": True,
                "log_level": "INFO"
            },
            "security.json": {
                "encryption_enabled": True,
                "key_rotation_days": 90,
                "store_keys_in_hsm": False,
                "audit_log_retention_days": 180
            },
            "automation.json": {
                "bid_frequency_minutes": 5,
                "min_acceptable_rating": 4.0,
                "auto_accept_recurring_clients": True,
                "risk_tolerance": "medium"
            },
            "platforms.json": {
                "enabled_platforms": ["upwork", "freelance_ru", "kwork"],
                "upwork": {"enabled": True},
                "freelance_ru": {"enabled": True},
                "kwork": {"enabled": True}
            }
        }

        for filename, default_content in defaults.items():
            config_path = self.config_dir / filename
            if not config_path.exists():
                logger.info(f"  → Generating {filename}")
                with open(config_path, 'w', encoding='utf-8') as f:
                    json.dump(default_content, f, indent=4, ensure_ascii=False)

        # Ensure .env exists
        env_path = self.project_root / ".env"
        if not env_path.exists():
            example_path = self.project_root / ".env.example"
            if example_path.exists():
                shutil.copy(example_path, env_path)
                logger.info("  → Created .env from .env.example")
            else:
                logger.warning("  ⚠️ .env.example not found — please create .env manually")

    def _validate_all_configs(self):
        """Validate all config files against JSON schemas."""
        logger.info("🔍 Validating configuration files...")
        validator = ConfigValidator(str(self.config_dir))
        invalid = validator.validate_all()
        if invalid:
            logger.error(f"❌ Invalid config files: {invalid}")
            raise RuntimeError("Configuration validation failed")
        logger.info("  → All configurations are valid")

    def _initialize_crypto_keys(self):
        """Initialize cryptographic keys if not present."""
        logger.info("🔐 Initializing cryptographic keys...")
        key_manager = KeyManager(config_dir=str(self.config_dir))
        if not key_manager.keys_exist():
            logger.info("  → Generating new encryption keys...")
            key_manager.generate_keys()
            logger.info("  → Keys generated and stored securely")
        else:
            logger.info("  → Keys already exist — skipping generation")

    def _set_secure_permissions(self):
        """Set secure file permissions on sensitive directories."""
        logger.info("🔒 Setting secure file permissions...")
        sensitive_dirs = [self.data_dir, self.config_dir, self.backup_dir]
        for d in sensitive_dirs:
            if os.name != 'nt':  # Skip on Windows
                os.chmod(d, 0o700)
                for root, dirs, files in os.walk(d):
                    for dd in dirs:
                        os.chmod(os.path.join(root, dd), 0o700)
                    for ff in files:
                        os.chmod(os.path.join(root, ff), 0o600)
        logger.info("  → Secure permissions applied")


def main():
    """Entry point for the configuration script."""
    configurer = SystemConfigurer()
    success = configurer.run()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()