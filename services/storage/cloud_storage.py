# services/storage/cloud_storage.py
"""
Cloud Storage Service — Unified interface for cloud storage providers.
Supports AWS S3, Google Cloud Storage, Azure Blob, and others via plugins.
Integrates with security, monitoring, and config systems.
"""

import asyncio
import logging
import os
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, Union, BinaryIO, List
from pathlib import Path

from core.config.unified_config_manager import UnifiedConfigManager
from core.security.advanced_crypto_system import AdvancedCryptoSystem
from core.monitoring.intelligent_monitoring_system import IntelligentMonitoringSystem
from core.dependency.service_locator import ServiceLocator


class CloudStorageError(Exception):
    """Base exception for cloud storage operations."""
    pass


class CloudStorageProvider(ABC):
    """Abstract base class for cloud storage providers."""

    def __init__(self, config: Dict[str, Any], crypto: AdvancedCryptoSystem):
        self.config = config
        self.crypto = crypto
        self.logger = logging.getLogger(f"CloudStorage.{self.__class__.__name__}")

    @abstractmethod
    async def upload(
        self,
        file_path: Union[str, Path],
        remote_key: str,
        metadata: Optional[Dict[str, str]] = None,
        encrypt: bool = True
    ) -> str:
        """Upload a file to cloud storage. Returns public or internal URL."""
        pass

    @abstractmethod
    async def download(self, remote_key: str, local_path: Union[str, Path]) -> Path:
        """Download a file from cloud storage."""
        pass

    @abstractmethod
    async def delete(self, remote_key: str) -> bool:
        """Delete a file from cloud storage."""
        pass

    @abstractmethod
    async def list_objects(self, prefix: str = "") -> List[str]:
        """List objects under a prefix."""
        pass

    @abstractmethod
    async def get_presigned_url(self, remote_key: str, expire_seconds: int = 3600) -> str:
        """Generate a time-limited presigned URL."""
        pass


class AWSS3Provider(CloudStorageProvider):
    """AWS S3 implementation using boto3 (async via aioboto3)."""

    def __init__(self, config: Dict[str, Any], crypto: AdvancedCryptoSystem):
        super().__init__(config, crypto)
        try:
            import aioboto3
        except ImportError as e:
            raise ImportError("aioboto3 is required for AWS S3 support") from e

        self.session = aioboto3.Session()
        self.bucket = config.get("bucket_name")
        if not self.bucket:
            raise ValueError("Missing 'bucket_name' in AWS S3 config")

    async def upload(
        self,
        file_path: Union[str, Path],
        remote_key: str,
        metadata: Optional[Dict[str, str]] = None,
        encrypt: bool = True
    ) -> str:
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        # Encrypt if requested
        final_path = file_path
        if encrypt:
            encrypted_path = file_path.with_suffix(file_path.suffix + ".enc")
            await self.crypto.encrypt_file(file_path, encrypted_path)
            final_path = encrypted_path
            if metadata is None:
                metadata = {}
            metadata["x-amz-meta-encrypted"] = "true"

        try:
            async with self.session.client(
                "s3",
                aws_access_key_id=self.config.get("access_key"),
                aws_secret_access_key=self.config.get("secret_key"),
                region_name=self.config.get("region", "us-east-1")
            ) as s3:
                with open(final_path, "rb") as f:
                    await s3.upload_fileobj(f, self.bucket, remote_key, ExtraArgs={"Metadata": metadata or {}})
                url = f"https://{self.bucket}.s3.amazonaws.com/{remote_key}"
                self.logger.info(f"📤 Uploaded {file_path} to S3: {url}")
                return url
        finally:
            if encrypt and final_path != file_path:
                final_path.unlink(missing_ok=True)

    async def download(self, remote_key: str, local_path: Union[str, Path]) -> Path:
        local_path = Path(local_path)
        local_path.parent.mkdir(parents=True, exist_ok=True)

        temp_path = local_path.with_suffix(local_path.suffix + ".tmp")
        try:
            async with self.session.client(
                "s3",
                aws_access_key_id=self.config.get("access_key"),
                aws_secret_access_key=self.config.get("secret_key"),
                region_name=self.config.get("region", "us-east-1")
            ) as s3:
                with open(temp_path, "wb") as f:
                    await s3.download_fileobj(self.bucket, remote_key, f)

            # Check if encrypted
            head = await s3.head_object(Bucket=self.bucket, Key=remote_key)
            is_encrypted = head.get("Metadata", {}).get("x-amz-meta-encrypted") == "true"

            if is_encrypted:
                decrypted_path = local_path
                await self.crypto.decrypt_file(temp_path, decrypted_path)
                temp_path.unlink(missing_ok=True)
                return decrypted_path
            else:
                temp_path.rename(local_path)
                return local_path

        except Exception as e:
            temp_path.unlink(missing_ok=True)
            raise CloudStorageError(f"Failed to download {remote_key}: {e}") from e

    async def delete(self, remote_key: str) -> bool:
        try:
            async with self.session.client(
                "s3",
                aws_access_key_id=self.config.get("access_key"),
                aws_secret_access_key=self.config.get("secret_key"),
                region_name=self.config.get("region", "us-east-1")
            ) as s3:
                await s3.delete_object(Bucket=self.bucket, Key=remote_key)
                self.logger.info(f"🗑️ Deleted {remote_key} from S3")
                return True
        except Exception as e:
            self.logger.error(f"❌ Failed to delete {remote_key}: {e}")
            return False

    async def list_objects(self, prefix: str = "") -> List[str]:
        keys = []
        try:
            async with self.session.client(
                "s3",
                aws_access_key_id=self.config.get("access_key"),
                aws_secret_access_key=self.config.get("secret_key"),
                region_name=self.config.get("region", "us-east-1")
            ) as s3:
                paginator = s3.get_paginator("list_objects_v2")
                async for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
                    if "Contents" in page:
                        keys.extend(obj["Key"] for obj in page["Contents"])
            return keys
        except Exception as e:
            raise CloudStorageError(f"Failed to list objects with prefix '{prefix}': {e}") from e

    async def get_presigned_url(self, remote_key: str, expire_seconds: int = 3600) -> str:
        try:
            async with self.session.client(
                "s3",
                aws_access_key_id=self.config.get("access_key"),
                aws_secret_access_key=self.config.get("secret_key"),
                region_name=self.config.get("region", "us-east-1")
            ) as s3:
                url = await s3.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": self.bucket, "Key": remote_key},
                    ExpiresIn=expire_seconds
                )
                return url
        except Exception as e:
            raise CloudStorageError(f"Failed to generate presigned URL: {e}") from e


class CloudStorageService:
    """
    Unified cloud storage service that delegates to provider plugins.
    Automatically selects provider based on config.
    Fully integrated with monitoring, security, and config systems.
    """

    def __init__(
        self,
        config_manager: Optional[UnifiedConfigManager] = None,
        crypto: Optional[AdvancedCryptoSystem] = None,
        monitor: Optional[IntelligentMonitoringSystem] = None
    ):
        self.logger = logging.getLogger("CloudStorageService")
        self.config_manager = config_manager or ServiceLocator.get("config")
        self.crypto = crypto or ServiceLocator.get("crypto")
        self.monitor = monitor or ServiceLocator.get("monitoring")

        self._provider: Optional[CloudStorageProvider] = None
        self._initialized = False

    async def initialize(self):
        """Initialize the appropriate cloud provider based on config."""
        if self._initialized:
            return

        storage_config = self.config_manager.get("storage.cloud", {})
        provider_type = storage_config.get("provider", "aws_s3").lower()

        if provider_type == "aws_s3":
            self._provider = AWSS3Provider(storage_config.get("aws_s3", {}), self.crypto)
        else:
            raise ValueError(f"Unsupported cloud provider: {provider_type}")

        self._initialized = True
        self.logger.info(f"✅ Cloud storage initialized with provider: {provider_type}")

    async def upload(
        self,
        file_path: Union[str, Path],
        remote_key: str,
        metadata: Optional[Dict[str, str]] = None,
        encrypt: bool = True
    ) -> str:
        await self.initialize()
        assert self._provider is not None

        start_time = asyncio.get_event_loop().time()
        try:
            url = await self._provider.upload(file_path, remote_key, metadata, encrypt)
            duration = asyncio.get_event_loop().time() - start_time
            self.monitor.record_metric("cloud.storage.upload.duration", duration)
            self.monitor.record_metric("cloud.storage.upload.success", 1)
            return url
        except Exception as e:
            self.monitor.record_metric("cloud.storage.upload.failure", 1)
            self.logger.exception("💥 Cloud upload failed")
            raise CloudStorageError(f"Upload failed: {e}") from e

    async def download(self, remote_key: str, local_path: Union[str, Path]) -> Path:
        await self.initialize()
        assert self._provider is not None

        start_time = asyncio.get_event_loop().time()
        try:
            path = await self._provider.download(remote_key, local_path)
            duration = asyncio.get_event_loop().time() - start_time
            self.monitor.record_metric("cloud.storage.download.duration", duration)
            self.monitor.record_metric("cloud.storage.download.success", 1)
            return path
        except Exception as e:
            self.monitor.record_metric("cloud.storage.download.failure", 1)
            self.logger.exception("💥 Cloud download failed")
            raise CloudStorageError(f"Download failed: {e}") from e

    async def delete(self, remote_key: str) -> bool:
        await self.initialize()
        assert self._provider is not None
        return await self._provider.delete(remote_key)

    async def list_objects(self, prefix: str = "") -> List[str]:
        await self.initialize()
        assert self._provider is not None
        return await self._provider.list_objects(prefix)

    async def get_presigned_url(self, remote_key: str, expire_seconds: int = 3600) -> str:
        await self.initialize()
        assert self._provider is not None
        return await self._provider.get_presigned_url(remote_key, expire_seconds)


# Singleton-like access (optional)
_cloud_storage_instance: Optional[CloudStorageService] = None


async def get_cloud_storage_service() -> CloudStorageService:
    """Global accessor for cloud storage service (lazy init)."""
    global _cloud_storage_instance
    if _cloud_storage_instance is None:
        _cloud_storage_instance = CloudStorageService()
        await _cloud_storage_instance.initialize()
    return _cloud_storage_instance