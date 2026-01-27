# AI_FREELANCE_AUTOMATION/services/storage/service_registry.py
"""
Central registry for all storage services.
Manages lifecycle, configuration, health, and failover of:
- DatabaseService
- FileStorage
- CloudStorage

Supports lazy loading, hot-reload, dependency injection,
and automatic recovery via core monitoring & security systems.
"""

import logging
from typing import Dict, Optional, Type, Any, cast
from pathlib import Path

from core.config.unified_config_manager import UnifiedConfigManager
from core.security.advanced_crypto_system import AdvancedCryptoSystem
from core.monitoring.intelligent_monitoring_system import IntelligentMonitoringSystem
from core.dependency.service_locator import ServiceLocator
from core.emergency_recovery import EmergencyRecovery

# Local storage service interfaces
from .database_service import DatabaseService
from .file_storage import FileStorage
from .cloud_storage import CloudStorage

logger = logging.getLogger("StorageServiceRegistry")


class StorageServiceRegistry:
    """
    Singleton-like registry that manages all storage-related services.
    Ensures consistent configuration, secure credential handling,
    and fault tolerance across all storage backends.
    """

    _instance: Optional["StorageServiceRegistry"] = None
    _initialized: bool = False

    def __new__(cls) -> "StorageServiceRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True

        # Dependencies injected via service locator or config
        self.config_manager: UnifiedConfigManager = ServiceLocator.get("config_manager")
        self.crypto: AdvancedCryptoSystem = ServiceLocator.get("crypto_system")
        self.monitor: IntelligentMonitoringSystem = ServiceLocator.get("monitoring_system")
        self.recovery: EmergencyRecovery = ServiceLocator.get("emergency_recovery")

        # Internal registry
        self._services: Dict[str, Any] = {}
        self._configs: Dict[str, Dict[str, Any]] = {}
        self._active: Dict[str, bool] = {}

        # Load and validate configs
        self._load_configs()
        self._validate_configs()

        logger.info("✅ StorageServiceRegistry initialized.")

    def _load_configs(self) -> None:
        """Load storage configurations from unified config."""
        storage_config = self.config_manager.get_section("storage")
        if not storage_config:
            raise ValueError("Missing 'storage' section in configuration.")

        self._configs = {
            "database": storage_config.get("database", {}),
            "file": storage_config.get("file", {}),
            "cloud": storage_config.get("cloud", {}),
        }

    def _validate_configs(self) -> None:
        """Validate each storage config against schema."""
        from core.config.config_validator import ConfigValidator

        schemas = {
            "database": "schemas/database.schema.json",
            "file": "schemas/file_storage.schema.json",
            "cloud": "schemas/cloud_storage.schema.json",
        }

        for name, config in self._configs.items():
            schema_path = schemas.get(name)
            if schema_path:
                ConfigValidator.validate(config, schema_path)
            else:
                logger.warning(f"⚠️ No schema for {name} storage config.")

    def get_service(self, service_name: str) -> Any:
        """
        Get a storage service by name. Lazy-initializes if not active.
        Supported names: 'database', 'file', 'cloud'
        """
        if service_name not in {"database", "file", "cloud"}:
            raise ValueError(f"Unknown storage service: {service_name}")

        if not self._active.get(service_name, False):
            self._initialize_service(service_name)

        service = self._services.get(service_name)
        if service is None:
            raise RuntimeError(f"Failed to initialize {service_name} service.")

        return service

    def _initialize_service(self, name: str) -> None:
        """Initialize a specific storage service securely."""
        logger.info(f"🔧 Initializing '{name}' storage service...")

        config = self._configs[name]
        encrypted_secrets = config.get("secrets", {})
        decrypted_secrets = {}

        # Decrypt credentials if present
        if encrypted_secrets:
            try:
                decrypted_secrets = {
                    k: self.crypto.decrypt(v) for k, v in encrypted_secrets.items()
                }
            except Exception as e:
                logger.error(f"🔐 Failed to decrypt secrets for {name}: {e}")
                raise

        full_config = {**config, **decrypted_secrets}

        service_map: Dict[str, Type] = {
            "database": DatabaseService,
            "file": FileStorage,
            "cloud": CloudStorage,
        }

        try:
            service_class = service_map[name]
            service_instance = service_class(config=full_config)
            self._services[name] = service_instance
            self._active[name] = True

            # Register with monitoring
            self.monitor.register_component(
                name=f"storage.{name}",
                instance=service_instance,
                metrics_callback=self._get_metrics_callback(name)
            )

            logger.info(f"🟢 '{name}' storage service ready.")
        except Exception as e:
            logger.critical(f"💥 Failed to initialize {name} service: {e}", exc_info=True)
            self.recovery.handle_component_failure(f"storage.{name}", e)
            raise

    def _get_metrics_callback(self, name: str):
        """Return a callback for collecting service-specific metrics."""
        def callback():
            svc = self._services.get(name)
            if hasattr(svc, "get_health_metrics"):
                return svc.get_health_metrics()
            return {"status": "unknown"}
        return callback

    def reload_config(self) -> None:
        """Hot-reload storage configuration without restart."""
        logger.info("🔄 Reloading storage configuration...")
        old_configs = self._configs.copy()
        self._load_configs()
        self._validate_configs()

        # Reinitialize services if config changed
        for name in self._configs:
            if self._configs[name] != old_configs.get(name, {}):
                logger.info(f"🔁 Reinitializing '{name}' due to config change.")
                self._active[name] = False
                # Force re-init on next get_service()
        logger.info("✅ Storage config reloaded.")

    def shutdown(self) -> None:
        """Gracefully shut down all storage services."""
        logger.info("🛑 Shutting down storage services...")
        for name, service in self._services.items():
            if hasattr(service, "close"):
                try:
                    service.close()
                    logger.info(f"CloseOperation completed for '{name}'.")
                except Exception as e:
                    logger.error(f"CloseOperation failed for '{name}': {e}")
        self._services.clear()
        self._active.clear()
        logger.info("⏹️ All storage services shut down.")


# Convenience global access (optional, but safe due to singleton)
def get_storage_registry() -> StorageServiceRegistry:
    return StorageServiceRegistry()