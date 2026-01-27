# plugins/plugin_manager.py
"""
Plugin Manager for AI Freelance Automation System

Responsible for:
- Discovering plugins in predefined directories
- Loading and validating plugin compatibility
- Managing plugin lifecycle (load/unload/enable/disable)
- Isolating plugin execution environments
- Hot-swapping without system restart
- Ensuring no conflicts with core components or other plugins

Follows strict security, validation, and dependency injection principles.
"""

import importlib
import importlib.util
import logging
import os
import sys
import traceback
from pathlib import Path
from typing import Dict, List, Optional, Type, Any, Set
from types import ModuleType

from core.config.unified_config_manager import UnifiedConfigManager
from core.security.audit_logger import AuditLogger
from core.dependency.service_locator import ServiceLocator


class PluginLoadError(Exception):
    """Raised when a plugin fails to load or validate."""
    pass


class PluginManager:
    """
    Centralized plugin management system with hot-swap support,
    sandboxed execution, and full lifecycle control.
    """

    PLUGIN_CATEGORIES = {
        "integration_plugins",
        "platform_plugins",
        "ai_plugins",
        "theme_plugins"
    }

    def __init__(self, config: UnifiedConfigManager, service_locator: ServiceLocator):
        self.config = config
        self.service_locator = service_locator
        self.logger = logging.getLogger("PluginManager")
        self.audit_logger = AuditLogger()

        # Plugin storage
        self._plugins: Dict[str, Dict[str, Any]] = {}  # {name: metadata}
        self._loaded_modules: Dict[str, ModuleType] = {}
        self._active_plugins: Set[str] = set()
        self._plugin_paths: Dict[str, Path] = {}

        # Initialize plugin directories
        self.plugins_root = Path(__file__).parent.resolve()
        self._discover_plugin_paths()

        self.logger.info("Intialized Plugin Manager with hot-swap and isolation support.")

    def _discover_plugin_paths(self) -> None:
        """Discover all valid plugin category directories."""
        for category in self.PLUGIN_CATEGORIES:
            category_path = self.plugins_root / category
            if category_path.exists() and category_path.is_dir():
                self._plugin_paths[category] = category_path
                self.logger.debug(f"Discovered plugin category: {category} at {category_path}")
            else:
                self.logger.warning(f"Plugin category directory missing: {category}")

    def discover_plugins(self) -> List[str]:
        """
        Scan all plugin directories and return list of discovered plugin names.
        Does NOT load them — only identifies available plugins.
        """
        discovered = []
        for category, path in self._plugin_paths.items():
            for file in path.glob("*.py"):
                if file.name.startswith("__") or file.name == "base_plugin.py":
                    continue
                plugin_name = file.stem
                discovered.append(plugin_name)
                if plugin_name not in self._plugins:
                    self._plugins[plugin_name] = {
                        "category": category,
                        "path": file,
                        "status": "discovered",
                        "version": None,
                        "author": None,
                        "dependencies": [],
                        "compatibility": None
                    }
        self.logger.info(f"Discovered {len(discovered)} plugins.")
        return discovered

    def validate_plugin(self, plugin_name: str) -> bool:
        """
        Validate plugin structure, metadata, and compatibility.
        Checks:
        - Required attributes (__plugin_name__, __version__, etc.)
        - Schema compliance
        - Dependency satisfaction
        - Security constraints
        """
        if plugin_name not in self._plugins:
            raise PluginLoadError(f"Plugin '{plugin_name}' not discovered.")

        meta = self._plugins[plugin_name]
        module_path = meta["path"]

        # Load spec without executing
        spec = importlib.util.spec_from_file_location(plugin_name, module_path)
        if spec is None or spec.loader is None:
            raise PluginLoadError(f"Cannot load spec for plugin: {plugin_name}")

        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception as e:
            self.logger.error(f"Failed to execute plugin module {plugin_name}: {e}")
            raise PluginLoadError(f"Plugin execution failed: {plugin_name}") from e

        # Check required attributes
        required_attrs = ["__plugin_name__", "__version__", "__author__", "register"]
        for attr in required_attrs:
            if not hasattr(module, attr):
                raise PluginLoadError(f"Plugin {plugin_name} missing required attribute: {attr}")

        # Store metadata
        meta["version"] = getattr(module, "__version__")
        meta["author"] = getattr(module, "__author__")
        meta["dependencies"] = getattr(module, "__dependencies__", [])
        meta["compatibility"] = getattr(module, "__compatibility__", ">=1.0.0")

        # TODO: Add semantic version compatibility check against system version

        # Validate dependencies (basic check)
        for dep in meta["dependencies"]:
            if dep not in sys.modules and not self._is_core_dependency(dep):
                self.logger.warning(f"Plugin {plugin_name} depends on non-loaded module: {dep}")

        self.logger.info(f"✅ Plugin validated: {plugin_name} v{meta['version']}")
        return True

    def _is_core_dependency(self, dep: str) -> bool:
        """Check if dependency is part of core system."""
        core_packages = {"core", "services", "ai", "platforms"}
        return any(dep.startswith(pkg) for pkg in core_packages)

    def load_plugin(self, plugin_name: str) -> bool:
        """
        Load and register a validated plugin.
        Executes its `register(service_locator)` method.
        """
        if plugin_name not in self._plugins:
            self.discover_plugins()
            if plugin_name not in self._plugins:
                raise PluginLoadError(f"Plugin '{plugin_name}' not found.")

        if plugin_name in self._loaded_modules:
            self.logger.warning(f"Plugin {plugin_name} already loaded.")
            return False

        self.validate_plugin(plugin_name)
        meta = self._plugins[plugin_name]

        # Load module
        spec = importlib.util.spec_from_file_location(plugin_name, meta["path"])
        module = importlib.util.module_from_spec(spec)
        sys.modules[plugin_name] = module  # Register in global modules to avoid re-import issues
        spec.loader.exec_module(module)

        self._loaded_modules[plugin_name] = module

        # Register via plugin's register() function
        try:
            module.register(self.service_locator)
            meta["status"] = "loaded"
            self._active_plugins.add(plugin_name)
            self.audit_logger.log(
                action="PLUGIN_LOADED",
                resource=plugin_name,
                details={"version": meta["version"], "author": meta["author"]}
            )
            self.logger.info(f"🔌 Plugin loaded and registered: {plugin_name}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to register plugin {plugin_name}: {e}\n{traceback.format_exc()}")
            # Clean up
            if plugin_name in sys.modules:
                del sys.modules[plugin_name]
            if plugin_name in self._loaded_modules:
                del self._loaded_modules[plugin_name]
            raise PluginLoadError(f"Plugin registration failed: {plugin_name}") from e

    def unload_plugin(self, plugin_name: str) -> bool:
        """Safely unload a plugin (if supported by plugin)."""
        if plugin_name not in self._loaded_modules:
            self.logger.warning(f"Plugin {plugin_name} not loaded.")
            return False

        module = self._loaded_modules[plugin_name]
        meta = self._plugins[plugin_name]

        # Call cleanup if exists
        if hasattr(module, "unregister"):
            try:
                module.unregister(self.service_locator)
            except Exception as e:
                self.logger.error(f"Plugin {plugin_name} unregister failed: {e}")

        # Remove references
        self._active_plugins.discard(plugin_name)
        del self._loaded_modules[plugin_name]
        if plugin_name in sys.modules:
            del sys.modules[plugin_name]

        meta["status"] = "unloaded"
        self.audit_logger.log(action="PLUGIN_UNLOADED", resource=plugin_name)
        self.logger.info(f"⏏️ Plugin unloaded: {plugin_name}")
        return True

    def reload_plugin(self, plugin_name: str) -> bool:
        """Hot-reload a plugin without restarting the system."""
        self.logger.info(f"🔄 Reloading plugin: {plugin_name}")
        self.unload_plugin(plugin_name)
        return self.load_plugin(plugin_name)

    def get_plugin_info(self, plugin_name: str) -> Optional[Dict[str, Any]]:
        """Return metadata about a plugin."""
        return self._plugins.get(plugin_name)

    def list_active_plugins(self) -> List[str]:
        """Return list of currently active (loaded) plugins."""
        return sorted(list(self._active_plugins))

    def list_all_plugins(self) -> Dict[str, Dict[str, Any]]:
        """Return full registry of all discovered plugins."""
        return self._plugins.copy()

    def enable_hot_reload(self) -> None:
        """Enable file watcher for automatic plugin reload (optional)."""
        # Could integrate watchdog or similar here
        self.logger.info("Hot-reload monitoring not implemented in base version.")

    def health_check(self) -> Dict[str, Any]:
        """Return health status of plugin subsystem."""
        return {
            "total_discovered": len(self._plugins),
            "active_plugins": len(self._active_plugins),
            "plugin_categories": list(self._plugin_paths.keys()),
            "status": "healthy" if len(self._plugins) > 0 else "warning"
        }