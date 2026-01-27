# AI_FREELANCE_AUTOMATION/services/storage/file_storage.py
"""
Local file storage service with encryption, versioning, and metadata support.
Integrates with core security, config, and monitoring systems.
"""

import os
import json
import shutil
import hashlib
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List, Union
from datetime import datetime, timezone

from core.config.unified_config_manager import UnifiedConfigManager
from core.security.advanced_crypto_system import AdvancedCryptoSystem
from core.monitoring.intelligent_monitoring_system import IntelligentMonitoringSystem


class FileStorageService:
    """
    Secure local file storage with:
    - AES-256-GCM encryption
    - Automatic versioning
    - Metadata tracking
    - Integrity verification (SHA-256)
    - Integration with backup & monitoring
    """

    def __init__(
        self,
        config: Optional[UnifiedConfigManager] = None,
        crypto: Optional[AdvancedCryptoSystem] = None,
        monitor: Optional[IntelligentMonitoringSystem] = None,
    ):
        self.config = config or UnifiedConfigManager()
        self.crypto = crypto or AdvancedCryptoSystem()
        self.monitor = monitor or IntelligentMonitoringSystem(self.config)

        # Load storage-specific settings
        storage_cfg = self.config.get("storage.file", {})
        self.base_path = Path(storage_cfg.get("base_path", "./data/storage/files")).resolve()
        self.versions_enabled = storage_cfg.get("enable_versions", True)
        self.encrypt_files = storage_cfg.get("encrypt", True)
        self.max_versions = storage_cfg.get("max_versions", 5)
        self.metadata_dir = self.base_path / ".metadata"
        self.versions_dir = self.base_path / ".versions"

        # Ensure directories exist
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.metadata_dir.mkdir(parents=True, exist_ok=True)
        if self.versions_enabled:
            self.versions_dir.mkdir(parents=True, exist_ok=True)

        self.logger = logging.getLogger("FileStorageService")
        self.logger.info(f"Intialized FileStorageService at {self.base_path}")

    def _get_metadata_path(self, file_id: str) -> Path:
        """Return path to metadata JSON file."""
        return self.metadata_dir / f"{file_id}.meta.json"

    def _get_file_path(self, file_id: str, version: Optional[str] = None) -> Path:
        """Return actual file path on disk."""
        if version:
            return self.versions_dir / f"{file_id}.{version}"
        return self.base_path / file_id

    def _generate_version_tag(self) -> str:
        """Generate ISO timestamp for versioning."""
        return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    def _compute_sha256(self, data: bytes) -> str:
        """Compute SHA-256 hash of data."""
        return hashlib.sha256(data).hexdigest()

    def store(
        self,
        file_id: str,
        data: Union[bytes, str],
        metadata: Optional[Dict[str, Any]] = None,
        overwrite: bool = False,
    ) -> Dict[str, Any]:
        """
        Store a file securely with optional encryption and versioning.

        Args:
            file_id: Unique identifier for the file (e.g., job_123/transcript.txt)
            data: Content to store (bytes or string)
            metadata: Optional metadata dict (will be merged with system metadata)
            overwrite: If False and file exists, creates new version (if enabled)

        Returns:
            Dict with storage info: path, hash, size, version, encrypted
        """
        if isinstance(data, str):
            data = data.encode("utf-8")

        file_path = self._get_file_path(file_id)
        exists = file_path.exists()

        # Handle versioning
        current_version = None
        if exists and not overwrite and self.versions_enabled:
            # Archive current file as version
            current_version = self._generate_version_tag()
            version_path = self._get_file_path(file_id, current_version)
            shutil.move(str(file_path), str(version_path))
            self.logger.debug(f"Archived existing file as version: {current_version}")

        # Encrypt if needed
        encrypted = False
        stored_data = data
        if self.encrypt_files:
            stored_data = self.crypto.encrypt_bytes(data)
            encrypted = True

        # Write new file
        file_path.write_bytes(stored_data)

        # Compute integrity hash (on original data)
        file_hash = self._compute_sha256(data)
        file_size = len(data)

        # Prepare metadata
        system_meta = {
            "file_id": file_id,
            "stored_at": datetime.now(timezone.utc).isoformat(),
            "size_bytes": file_size,
            "sha256": file_hash,
            "encrypted": encrypted,
            "version": current_version,
            "path": str(file_path),
        }
        if metadata:
            system_meta.update(metadata)

        # Save metadata
        meta_path = self._get_metadata_path(file_id)
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(system_meta, f, indent=2, ensure_ascii=False)

        # Prune old versions
        if self.versions_enabled and current_version:
            self._prune_versions(file_id)

        # Log & monitor
        self.logger.info(f"Stored file: {file_id} ({file_size} bytes)")
        self.monitor.record_metric("file_storage.bytes_written", file_size)
        self.monitor.record_metric("file_storage.files_stored", 1)

        return system_meta

    def retrieve(self, file_id: str, version: Optional[str] = None) -> Optional[bytes]:
        """
        Retrieve file content by ID (and optional version).

        Returns:
            Original bytes (decrypted if needed), or None if not found.
        """
        file_path = self._get_file_path(file_id, version)
        if not file_path.exists():
            self.logger.warning(f"File not found: {file_id} (version={version})")
            return None

        raw_data = file_path.read_bytes()

        # Check if encrypted via metadata
        meta = self.get_metadata(file_id)
        if meta and meta.get("encrypted", False):
            try:
                raw_data = self.crypto.decrypt_bytes(raw_data)
            except Exception as e:
                self.logger.error(f"Decryption failed for {file_id}: {e}")
                return None

        self.monitor.record_metric("file_storage.bytes_read", len(raw_data))
        return raw_data

    def get_metadata(self, file_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve metadata for a file."""
        meta_path = self._get_metadata_path(file_id)
        if not meta_path.exists():
            return None
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            self.logger.error(f"Failed to load metadata for {file_id}: {e}")
            return None

    def list_files(self, prefix: Optional[str] = None) -> List[str]:
        """List all stored file IDs (optionally filtered by prefix)."""
        ids = []
        for item in self.base_path.iterdir():
            if item.is_file():
                fid = item.name
                if prefix is None or fid.startswith(prefix):
                    ids.append(fid)
        return sorted(ids)

    def delete(self, file_id: str, keep_versions: bool = True) -> bool:
        """Delete a file (and optionally its versions)."""
        success = True

        # Delete main file
        main_path = self._get_file_path(file_id)
        if main_path.exists():
            try:
                main_path.unlink()
                self.logger.info(f"Deleted main file: {file_id}")
            except OSError as e:
                self.logger.error(f"Failed to delete {file_id}: {e}")
                success = False

        # Delete metadata
        meta_path = self._get_metadata_path(file_id)
        if meta_path.exists():
            meta_path.unlink()

        # Delete versions if requested
        if not keep_versions and self.versions_enabled:
            for ver_path in self.versions_dir.glob(f"{file_id}.*"):
                try:
                    ver_path.unlink()
                    self.logger.debug(f"Deleted version: {ver_path.name}")
                except OSError as e:
                    self.logger.warning(f"Failed to delete version {ver_path}: {e}")

        return success

    def _prune_versions(self, file_id: str):
        """Keep only the last N versions."""
        version_files = sorted(self.versions_dir.glob(f"{file_id}.*"))
        if len(version_files) > self.max_versions:
            to_delete = version_files[: len(version_files) - self.max_versions]
            for vf in to_delete:
                vf.unlink()
                self.logger.debug(f"Pruned old version: {vf.name}")

    def backup_to(self, destination: Union[str, Path]) -> bool:
        """Perform full backup of storage directory."""
        try:
            dest = Path(destination)
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copytree(self.base_path, dest / "files", dirs_exist_ok=True)
            shutil.copytree(self.metadata_dir, dest / "metadata", dirs_exist_ok=True)
            if self.versions_enabled:
                shutil.copytree(self.versions_dir, dest / "versions", dirs_exist_ok=True)
            self.logger.info(f"Backup completed to {destination}")
            return True
        except Exception as e:
            self.logger.error(f"Backup failed: {e}")
            return False


# Singleton-like access (optional)
__instance: Optional[FileStorageService] = None


def get_file_storage() -> FileStorageService:
    """Global access point (use only if DI not available)."""
    global __instance
    if __instance is None:
        __instance = FileStorageService()
    return __instance