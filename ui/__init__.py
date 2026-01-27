# AI_FREELANCE_AUTOMATION/ui/__init__.py
"""
User Interface (UI) Module — Entry Point

This package provides both desktop and optional web-based interfaces
for monitoring and managing the autonomous AI freelancer system.

It supports:
- Adaptive layouts (desktop, tablet, mobile)
- Multiple themes (dark, light, custom)
- Drag-and-drop customizable widgets
- Real-time data binding to core services
- Zero-dependency lazy loading of heavy components

All UI components are isolated from business logic via service registry
and communicate through well-defined interfaces only.
"""

import logging
from typing import Optional

# Lazy imports to avoid circular dependencies and speed up startup
from core.dependency.service_locator import ServiceLocator

# Public API exports
__all__ = [
    "initialize_ui",
    "get_main_window",
    "ThemeManager",
    "UI_COMPONENTS_LOADED"
]

# Module-level state
UI_COMPONENTS_LOADED: bool = False
_logger = logging.getLogger(__name__)


def initialize_ui(
    service_locator: Optional[ServiceLocator] = None,
    enable_web: bool = False,
    headless: bool = False
) -> bool:
    """
    Initialize the UI subsystem safely and idempotently.

    Args:
        service_locator: Optional pre-configured service locator.
                         If not provided, will attempt to use global instance.
        enable_web: Whether to initialize the optional web interface.
        headless: If True, initializes only backend bindings (no GUI).

    Returns:
        bool: True if initialization succeeded or was already done.
    """
    global UI_COMPONENTS_LOADED
    if UI_COMPONENTS_LOADED:
        _logger.debug("UI already initialized. Skipping re-initialization.")
        return True

    try:
        _logger.info("BeginInit UI subsystem...")

        # Validate service locator
        if service_locator is None:
            from core.dependency.service_locator import get_global_service_locator
            service_locator = get_global_service_locator()

        # Register UI-related services if not already present
        if not service_locator.has("theme_manager"):
            from .theme_manager import ThemeManager
            service_locator.register("theme_manager", ThemeManager())

        if not service_locator.has("ui_config"):
            from core.config.unified_config_manager import UnifiedConfigManager
            config = service_locator.get("config") or UnifiedConfigManager()
            ui_config = config.get_section("ui") or {}
            service_locator.register("ui_config", ui_config)

        # Only load heavy GUI components if not in headless mode
        if not headless:
            from .main_window import MainWindow
            service_locator.register("main_window_class", MainWindow)

        if enable_web:
            try:
                from .web.app import WebUIApp
                service_locator.register("web_ui_app", WebUIApp())
            except ImportError as e:
                _logger.warning(f"Web UI not available: {e}")

        UI_COMPONENTS_LOADED = True
        _logger.info("✅ UI subsystem initialized successfully.")
        return True

    except Exception as e:
        _logger.critical(f"❌ Failed to initialize UI: {e}", exc_info=True)
        return False


def get_main_window() -> Optional["MainWindow"]:
    """
    Retrieve the main window instance (if initialized in non-headless mode).

    Returns:
        MainWindow instance or None if not available.
    """
    if not UI_COMPONENTS_LOADED:
        _logger.warning("UI not initialized. Call `initialize_ui()` first.")
        return None

    try:
        from core.dependency.service_locator import get_global_service_locator
        locator = get_global_service_locator()
        MainWindowClass = locator.get("main_window_class")
        if MainWindowClass:
            # Note: Actual instance should be created by app lifecycle manager
            # This is a factory reference, not a singleton instance
            return MainWindowClass
    except Exception as e:
        _logger.error(f"Error retrieving main window: {e}")
    return None


# Optional: Preload lightweight theme definitions
from .theme_manager import ThemeManager  # noqa: F401