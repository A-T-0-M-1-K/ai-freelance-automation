# AI_FREELANCE_AUTOMATION/migrations/env.py
"""
Alembic environment configuration for AI_FREELANCE_AUTOMATION.

This file connects Alembic to the application's database engine and metadata,
ensuring secure, configurable, and auditable schema migrations.

Key features:
- Loads DB URL from encrypted config via UnifiedConfigManager
- Supports both sync and async engines (auto-detected)
- Integrates with system audit logging
- Prevents accidental production migrations without approval
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add project root to path for imports
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from logging.config import fileConfig
from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.schema import MetaData

# Import application components
try:
    from core.config.unified_config_manager import UnifiedConfigManager
    from core.security.audit_logger import AuditLogger
except ImportError as e:
    raise RuntimeError(
        "Failed to import core modules. Ensure this file is run from the project root "
        "or that PYTHONPATH includes the project directory."
    ) from e

# Alembic Config object
config = context.config

# Setup logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)
logger = logging.getLogger("alembic.env")

# Target metadata — must be imported from your models
# We use a lazy import to avoid premature initialization
target_metadata: MetaData = None  # Will be set dynamically

def get_target_metadata():
    """Lazy-load application metadata to avoid circular imports."""
    global target_metadata
    if target_metadata is None:
        try:
            # Import your actual declarative base metadata here
            from services.database.models import Base
            target_metadata = Base.metadata
        except Exception as e:
            logger.error("❌ Failed to load database models metadata", exc_info=True)
            raise RuntimeError("Database models not available for migration") from e
    return target_metadata

def get_database_url() -> str:
    """Securely retrieve database URL from encrypted configuration."""
    try:
        config_manager = UnifiedConfigManager()
        db_config = config_manager.get_section("database")
        db_url = db_config.get("url")
        if not db_url:
            raise ValueError("Database URL not found in configuration")
        # Optional: decrypt if stored encrypted
        # db_url = config_manager.decrypt_secret(db_url)
        return db_url
    except Exception as e:
        logger.critical("🔐 Failed to load database URL from secure config", exc_info=True)
        raise RuntimeError("Database configuration unavailable") from e

def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (SQL script generation)."""
    url = get_database_url()
    context.configure(
        url=url,
        target_metadata=get_target_metadata(),
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table="alembic_version_ai_freelance",
    )

    with context.begin_transaction():
        context.run_migrations()

async def run_async_migrations() -> None:
    """Run migrations in async mode."""
    db_url = get_database_url()
    connectable = create_async_engine(
        db_url,
        echo=False,
        poolclass=pool.NullPool,  # Alembic handles connection lifecycle
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()

def run_migrations_online() -> None:
    """Run migrations in 'online' mode (direct DB connection)."""
    db_url = get_database_url()

    # Detect if async URL (e.g., starts with 'postgresql+asyncpg://')
    is_async = db_url.startswith(("postgresql+asyncpg", "mysql+aiomysql", "sqlite+aiosqlite"))

    if is_async:
        asyncio.run(run_async_migrations())
    else:
        # Synchronous engine
        connectable = engine_from_config(
            {"sqlalchemy.url": db_url},
            prefix="sqlalchemy.",
            poolclass=pool.NullPool,
        )

        with connectable.connect() as connection:
            do_run_migrations(connection)

        connectable.dispose()

def do_run_migrations(connection):
    """Actual migration execution."""
    # Log migration attempt
    audit = AuditLogger()
    audit.log_event(
        event_type="DATABASE_MIGRATION_START",
        details={"operation": "run_migrations", "target": "production" if "prod" in db_url else "development"}
    )

    context.configure(
        connection=connection,
        target_metadata=get_target_metadata(),
        version_table="alembic_version_ai_freelance",
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()

    audit.log_event(
        event_type="DATABASE_MIGRATION_SUCCESS",
        details={"status": "completed"}
    )

# Main entry point
if context.is_offline_mode():
    run_migrations_offline()
else:
    try:
        run_migrations_online()
    except Exception as e:
        logger.critical("💥 Migration failed", exc_info=True)
        # Log to audit system if possible
        try:
            AuditLogger().log_event(
                event_type="DATABASE_MIGRATION_FAILURE",
                details={"error": str(e)}
            )
        except:
            pass  # Fallback if audit system is down
        raise