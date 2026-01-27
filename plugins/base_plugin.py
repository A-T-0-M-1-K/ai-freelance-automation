# AI_FREELANCE_AUTOMATION/plugins/base_plugin.py
"""
Base Plugin Class for AI Freelance Automation System.
All plugins must inherit from this class to ensure compatibility,
security, and lifecycle management.
"""

import abc
import logging
import asyncio
from typing import Dict, Any, Optional, TYPE_CHECKING
from pathlib import Path

if TYPE_CHECKING:
    from core.config.unified_config_manager import UnifiedConfigManager
    from core.security.advanced_crypto_system import AdvancedCryptoSystem
    from core.monitoring.intelligent_monitoring_system import IntelligentMonitoringSystem


class BasePlugin(abc.ABC):
    """
    Abstract base class for all plugins in the system.

    Plugins are isolated, hot-swappable components that extend functionality
    without modifying core logic. Examples: platform integrations, AI models,
    notification channels, UI themes.

    Each plugin must implement:
        - `initialize()`
        - `shutdown()`
        - `get_metadata()`

    Optional hooks:
        - `on_load()`
        - `on_unload()`
        - `validate_config()`
    """

    def __init__(
        self,
        plugin_id: str,
        config: Optional["UnifiedConfigManager"] = None,
        crypto: Optional["AdvancedCryptoSystem"] = None,
        monitor: Optional["IntelligentMonitoringSystem"] = None,
        plugin_path: Optional[Path] = None,
    ):
        if not plugin_id or not isinstance(plugin_id, str):
            raise ValueError("plugin_id must be a non-empty string")

        self.plugin_id = plugin_id
        self._config = config
        self._crypto = crypto
        self._monitor = monitor
        self._plugin_path = plugin_path or Path(__file__).parent
        self._logger = logging.getLogger(f"Plugin.{self.plugin_id}")
        self._initialized = False
        self._enabled = True  # Can be toggled externally

        self._logger.info(f"🔌 Plugin '{self.plugin_id}' instantiated.")

    @property
    def config(self) -> "UnifiedConfigManager":
        if self._config is None:
            raise RuntimeError("Plugin was not provided with a config manager")
        return self._config

    @property
    def crypto(self) -> "AdvancedCryptoSystem":
        if self._crypto is None:
            raise RuntimeError("Plugin was not provided with a crypto system")
        return self._crypto

    @property
    def monitor(self) -> "IntelligentMonitoringSystem":
        if self._monitor is None:
            raise RuntimeError("Plugin was not provided with a monitoring system")
        return self._monitor

    @property
    def initialized(self) -> bool:
        return self._initialized

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        if not isinstance(value, bool):
            raise TypeError("enabled must be a boolean")
        self._enabled = value
        self._logger.info(f"Plugin '{self.plugin_id}' {'enabled' if value else 'disabled'}.")

    @abc.abstractmethod
    def get_metadata(self) -> Dict[str, Any]:
        """
        Return plugin metadata.

        Required fields:
            - name: str
            - version: str (semver)
            - author: str
            - description: str
            - compatible_core_version: str (e.g., ">=1.0.0,<2.0.0")
            - dependencies: List[str] (other plugin IDs)
            - capabilities: List[str] (e.g., ["transcription", "platform:upwork"])

        Example:
            {
                "name": "Upwork Integration",
                "version": "1.2.0",
                "author": "AI Freelance Team",
                "description": "Connects to Upwork API",
                "compatible_core_version": ">=1.0.0,<2.0.0",
                "dependencies": [],
                "capabilities": ["platform:upwork", "bid_automation"]
            }
        """
        pass

    async def validate_config(self) -> bool:
        """
        Optional: Validate plugin-specific configuration.
        Called during initialization.
        Should log errors and return False on failure.
        """
        return True

    async def initialize(self) -> bool:
        """
        Initialize the plugin (load models, connect to APIs, etc.).
        Must be idempotent and safe to call multiple times.
        Returns True on success, False on failure.
        """
        if self._initialized:
            self._logger.debug("Plugin already initialized. Skipping re-initialization.")
            return True

        if not self._enabled:
            self._logger.warning("Plugin is disabled. Skipping initialization.")
            return False

        try:
            self._logger.info("BeginInit plugin...")
            metadata = self.get_metadata()
            self._logger.info(f"Plugin metadata: {metadata['name']} v{metadata['version']}")

            if not await self.validate_config():
                self._logger.error("❌ Plugin configuration validation failed.")
                return False

            await self._internal_initialize()
            self._initialized = True
            self._logger.info("✅ Plugin initialized successfully.")
            return True

        except Exception as e:
            self._logger.exception(f"💥 Failed to initialize plugin: {e}")
            if self._monitor:
                await self._monitor.log_anomaly(
                    source=self.plugin_id,
                    anomaly_type="plugin_initialization_failure",
                    details={"error": str(e)},
                    severity="critical"
                )
            return False

    @abc.abstractmethod
    async def _internal_initialize(self) -> None:
        """
        Internal initialization logic. Implement in subclasses.
        Called only once during `initialize()`.
        """
        pass

    async def shutdown(self) -> None:
        """
        Gracefully shut down the plugin (close connections, save state, etc.).
        Must be safe to call even if not initialized.
        """
        if not self._initialized:
            return

        try:
            self._logger.info("CloseOperation plugin...")
            await self._internal_shutdown()
            self._initialized = False
            self._logger.info("🔌 Plugin shut down successfully.")
        except Exception as e:
            self._logger.exception(f"⚠️ Error during plugin shutdown: {e}")

    async def _internal_shutdown(self) -> None:
        """
        Internal shutdown logic. Override in subclasses if needed.
        """
        pass

    async def on_load(self) -> None:
        """
        Hook called immediately after plugin is loaded into PluginManager.
        Useful for registration or early setup.
        """
        pass

    async def on_unload(self) -> None:
        """
        Hook called before plugin is removed from PluginManager.
        """
        pass

    def __repr__(self) -> str:
        return f"<BasePlugin(id='{self.plugin_id}', initialized={self._initialized}, enabled={self._enabled})>"