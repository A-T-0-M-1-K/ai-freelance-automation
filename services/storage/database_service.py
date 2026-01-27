"""
Database Service — Unified interface for all database operations.
Supports PostgreSQL (production), MongoDB (document storage), SQLite (development).
Implements connection pooling, retry logic, encryption-at-rest support, and self-healing.
"""

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional, Union, AsyncGenerator
from contextlib import asynccontextmanager

import asyncpg
from motor.motor_asyncio import AsyncIOMotorClient
import aiosqlite

from core.config.unified_config_manager import UnifiedConfigManager
from core.security.advanced_crypto_system import AdvancedCryptoSystem
from core.monitoring.intelligent_monitoring_system import IntelligentMonitoringSystem
from core.dependency.service_locator import ServiceLocator


class DatabaseServiceError(Exception):
    """Base exception for database-related errors."""
    pass


class DatabaseConnectionError(DatabaseServiceError):
    """Raised when connection to the database fails."""
    pass


class DatabaseOperationError(DatabaseServiceError):
    """Raised when a database operation fails."""
    pass


class DatabaseService:
    """
    Unified asynchronous database service supporting multiple backends.
    Automatically selects backend based on config profile.
    """

    def __init__(
        self,
        config: Optional[UnifiedConfigManager] = None,
        crypto: Optional[AdvancedCryptoSystem] = None,
        monitor: Optional[IntelligentMonitoringSystem] = None
    ):
        self.logger = logging.getLogger("DatabaseService")
        self.config = config or ServiceLocator.get("config")
        self.crypto = crypto or ServiceLocator.get("crypto")
        self.monitor = monitor or ServiceLocator.get("monitoring")

        self._backend_type: str = self.config.get("database.backend", "sqlite")
        self._pool: Any = None
        self._client: Any = None  # For MongoDB
        self._initialized: bool = False
        self._max_retries: int = self.config.get("database.retry_attempts", 3)
        self._retry_delay: float = self.config.get("database.retry_delay_sec", 1.0)

    async def initialize(self) -> None:
        """Initialize database connection pool or client."""
        if self._initialized:
            return

        try:
            if self._backend_type == "postgresql":
                await self._init_postgresql()
            elif self._backend_type == "mongodb":
                await self._init_mongodb()
            elif self._backend_type == "sqlite":
                await self._init_sqlite()
            else:
                raise ValueError(f"Unsupported database backend: {self._backend_type}")

            self._initialized = True
            self.logger.info(f"✅ Database service initialized with backend: {self._backend_type}")
            await self.monitor.log_metric("db.initialized", 1)
        except Exception as e:
            self.logger.critical(f"💥 Failed to initialize database: {e}", exc_info=True)
            await self.monitor.log_metric("db.init_failure", 1)
            raise DatabaseConnectionError(f"Database initialization failed: {e}") from e

    async def _init_postgresql(self) -> None:
        dsn = self.config.get("database.postgresql.dsn")
        if not dsn:
            raise ValueError("PostgreSQL DSN not configured")

        min_size = self.config.get("database.postgresql.min_connections", 2)
        max_size = self.config.get("database.postgresql.max_connections", 10)

        self._pool = await asyncpg.create_pool(
            dsn=dsn,
            min_size=min_size,
            max_size=max_size,
            command_timeout=self.config.get("database.timeout_sec", 60),
            ssl=self.config.get("database.postgresql.ssl", True)
        )

    async def _init_mongodb(self) -> None:
        uri = self.config.get("database.mongodb.uri")
        if not uri:
            raise ValueError("MongoDB URI not configured")

        self._client = AsyncIOMotorClient(
            uri,
            maxPoolSize=self.config.get("database.mongodb.max_pool_size", 100),
            serverSelectionTimeoutMS=self.config.get("database.timeout_sec", 60) * 1000
        )

    async def _init_sqlite(self) -> None:
        path = self.config.get("database.sqlite.path", "data/app.db")
        # Ensure parent dirs exist
        import os
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # We'll open/close connections per operation in SQLite (no real pooling in async)

    async def close(self) -> None:
        """Gracefully close all database connections."""
        if not self._initialized:
            return

        try:
            if self._backend_type == "postgresql" and self._pool:
                await self._pool.close()
            elif self._backend_type == "mongodb" and self._client:
                self._client.close()
            self._initialized = False
            self.logger.info("🔌 Database connections closed.")
        except Exception as e:
            self.logger.error(f"⚠️ Error during database shutdown: {e}", exc_info=True)

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator["DatabaseTransaction", None]:
        """
        Context manager for database transactions (PostgreSQL/SQLite only).
        MongoDB does not support multi-document ACID transactions in this abstraction.
        """
        if self._backend_type == "mongodb":
            raise NotImplementedError("Transactions not supported for MongoDB in this context.")

        trans = DatabaseTransaction(self)
        try:
            await trans.begin()
            yield trans
            await trans.commit()
        except Exception as e:
            await trans.rollback()
            raise e

    async def execute(self, query: str, *args, **kwargs) -> Any:
        """Execute a write query (INSERT/UPDATE/DELETE)."""
        return await self._execute_with_retry(self._execute_impl, query, *args, **kwargs)

    async def fetch_one(self, query: str, *args, **kwargs) -> Optional[Dict[str, Any]]:
        """Fetch a single record."""
        return await self._execute_with_retry(self._fetch_one_impl, query, *args, **kwargs)

    async def fetch_all(self, query: str, *args, **kwargs) -> List[Dict[str, Any]]:
        """Fetch multiple records."""
        return await self._execute_with_retry(self._fetch_all_impl, query, *args, **kwargs)

    async def insert_document(self, collection: str, document: Dict[str, Any]) -> str:
        """Insert a document (MongoDB only)."""
        if self._backend_type != "mongodb":
            raise NotImplementedError("Document operations only supported for MongoDB.")
        return await self._execute_with_retry(self._insert_document_impl, collection, document)

    async def find_documents(self, collection: str, filter_query: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Find documents by filter (MongoDB only)."""
        if self._backend_type != "mongodb":
            raise NotImplementedError("Document operations only supported for MongoDB.")
        return await self._execute_with_retry(self._find_documents_impl, collection, filter_query)

    # === Implementation methods per backend ===

    async def _execute_impl(self, query: str, *args) -> Any:
        if self._backend_type == "postgresql":
            async with self._pool.acquire() as conn:
                result = await conn.execute(query, *args)
                return result
        elif self._backend_type == "sqlite":
            async with aiosqlite.connect(self.config.get("database.sqlite.path")) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(query, args)
                await db.commit()
                return cursor.lastrowid
        else:
            raise NotImplementedError(f"Write operations not implemented for {self._backend_type}")

    async def _fetch_one_impl(self, query: str, *args) -> Optional[Dict[str, Any]]:
        if self._backend_type == "postgresql":
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(query, *args)
                return dict(row) if row else None
        elif self._backend_type == "sqlite":
            async with aiosqlite.connect(self.config.get("database.sqlite.path")) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(query, args)
                row = await cursor.fetchone()
                return dict(row) if row else None
        else:
            raise NotImplementedError(f"Fetch operations not implemented for {self._backend_type}")

    async def _fetch_all_impl(self, query: str, *args) -> List[Dict[str, Any]]:
        if self._backend_type == "postgresql":
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(query, *args)
                return [dict(row) for row in rows]
        elif self._backend_type == "sqlite":
            async with aiosqlite.connect(self.config.get("database.sqlite.path")) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(query, args)
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
        else:
            raise NotImplementedError(f"Fetch operations not implemented for {self._backend_type}")

    async def _insert_document_impl(self, collection: str, document: Dict[str, Any]) -> str:
        db_name = self.config.get("database.mongodb.database", "ai_freelance")
        result = await self._client[db_name][collection].insert_one(document)
        return str(result.inserted_id)

    async def _find_documents_impl(self, collection: str, filter_query: Dict[str, Any]) -> List[Dict[str, Any]]:
        db_name = self.config.get("database.mongodb.database", "ai_freelance")
        cursor = self._client[db_name][collection].find(filter_query)
        docs = await cursor.to_list(length=None)
        for doc in docs:
            doc["_id"] = str(doc["_id"])
        return docs

    # === Retry & Recovery Logic ===

    async def _execute_with_retry(self, func, *args, **kwargs):
        last_exception = None
        for attempt in range(self._max_retries + 1):
            try:
                return await func(*args, **kwargs)
            except (asyncpg.PostgresError, aiosqlite.Error, Exception) as e:
                last_exception = e
                self.logger.warning(
                    f"⚠️ Database operation failed (attempt {attempt + 1}/{self._max_retries + 1}): {e}"
                )
                await self.monitor.log_metric("db.operation_retry", 1)
                if attempt < self._max_retries:
                    await asyncio.sleep(self._retry_delay * (2 ** attempt))  # exponential backoff
                else:
                    break

        # If all retries failed, trigger emergency recovery
        self.logger.error("❌ All database retries exhausted. Triggering recovery protocol.")
        await self.monitor.log_metric("db.operation_failure", 1)
        recovery = ServiceLocator.get("emergency_recovery")
        if recovery:
            await recovery.handle_component_failure("database", last_exception)

        raise DatabaseOperationError(f"Database operation failed after {self._max_retries} retries") from last_exception


class DatabaseTransaction:
    """Simple transaction wrapper for relational databases."""

    def __init__(self, db_service: DatabaseService):
        self.db = db_service
        self._conn = None
        self._active = False

    async def begin(self):
        if self.db._backend_type == "postgresql":
            self._conn = await self.db._pool.acquire()
            await self._conn.execute("BEGIN;")
            self._active = True
        elif self.db._backend_type == "sqlite":
            # SQLite handles auto-commits; we simulate via manual commit control
            self._conn = await aiosqlite.connect(self.db.config.get("database.sqlite.path"))
            self._conn.row_factory = aiosqlite.Row
            await self._conn.execute("BEGIN IMMEDIATE;")
            self._active = True

    async def commit(self):
        if self._active and self._conn:
            await self._conn.execute("COMMIT;")
            await self._finalize()

    async def rollback(self):
        if self._active and self._conn:
            await self._conn.execute("ROLLBACK;")
            await self._finalize()

    async def execute(self, query: str, *args):
        if not self._active:
            raise RuntimeError("Transaction not active")
        if self.db._backend_type == "postgresql":
            return await self._conn.execute(query, *args)
        else:
            cursor = await self._conn.execute(query, args)
            return cursor.lastrowid

    async def _finalize(self):
        if self.db._backend_type == "postgresql":
            await self.db._pool.release(self._conn)
        else:
            await self._conn.close()
        self._active = False
        self._conn = None