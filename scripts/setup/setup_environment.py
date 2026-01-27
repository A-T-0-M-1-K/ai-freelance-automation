# AI_FREELANCE_AUTOMATION/scripts/setup/setup_environment.py
"""
Environment Setup Script for AI Freelance Automation System

This script:
- Creates required directories
- Initializes .env file from .env.example if missing
- Sets up logging directories
- Validates Python version and critical dependencies
- Ensures proper file permissions (POSIX systems)
- Prepares the runtime environment for first launch

Designed to be idempotent and safe to run multiple times.
"""

import os
import sys
import shutil
import logging
import platform
from pathlib import Path
from typing import List, Optional

# Configure minimal logging before full system init
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger("SetupEnvironment")

# Project root detection
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent.resolve()
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
    "ai/logs",
    "ai/temp",
    "backup/automatic/daily",
    "backup/automatic/weekly",
    "backup/automatic/monthly",
]

MIN_PYTHON_VERSION = (3, 10)


def check_python_version() -> None:
    """Ensure compatible Python version."""
    if sys.version_info < MIN_PYTHON_VERSION:
        raise RuntimeError(
            f"Python {'.'.join(map(str, MIN_PYTHON_VERSION))} or higher is required. "
            f"Current version: {sys.version}"
        )
    logger.info(f"✅ Python version OK: {sys.version}")


def create_directories() -> None:
    """Create all required directory structures."""
    for rel_path in REQUIRED_DIRS:
        full_path = PROJECT_ROOT / rel_path
        full_path.mkdir(parents=True, exist_ok=True)
        logger.debug(f"📁 Created/verified directory: {full_path}")
    logger.info("✅ All required directories are ready.")


def setup_env_file() -> None:
    """Initialize .env from .env.example if not exists."""
    env_path = PROJECT_ROOT / ".env"
    example_path = PROJECT_ROOT / ".env.example"

    if not example_path.exists():
        logger.warning("⚠️  .env.example not found — skipping .env setup")
        return

    if not env_path.exists():
        shutil.copy(example_path, env_path)
        logger.info("✅ .env file created from .env.example")
    else:
        logger.info("✅ .env file already exists — skipping")


def set_permissions() -> None:
    """Set secure permissions on sensitive directories (Unix-like only)."""
    if platform.system() == "Windows":
        return

    sensitive_dirs = ["data", "logs", "backup", "ai/models"]
    for d in sensitive_dirs:
        path = PROJECT_ROOT / d
        if path.exists():
            # rwx for owner only (700)
            os.chmod(path, 0o700)
            logger.debug(f"🔒 Set secure permissions on: {path}")
    logger.info("✅ File permissions secured (where applicable)")


def validate_critical_dependencies() -> None:
    """Check that essential packages are available."""
    critical_deps = ["pydantic", "cryptography", "aiohttp", "psutil"]
    missing: List[str] = []

    for dep in critical_deps:
        try:
            __import__(dep)
        except ImportError:
            missing.append(dep)

    if missing:
        logger.error(
            f"❌ Missing critical dependencies: {', '.join(missing)}\n"
            "Please run: pip install -r requirements.txt"
        )
        sys.exit(1)
    logger.info("✅ Critical dependencies are installed.")


def main() -> int:
    """
    Main setup routine.
    Returns exit code (0 = success).
    """
    logger.info("🚀 Starting environment setup for AI Freelance Automation...")

    try:
        check_python_version()
        create_directories()
        setup_env_file()
        set_permissions()
        validate_critical_dependencies()

        logger.info("🎉 Environment setup completed successfully!")
        logger.info("👉 Next steps: configure your .env file and run 'python main.py'")
        return 0

    except Exception as e:
        logger.exception(f"💥 Setup failed: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())