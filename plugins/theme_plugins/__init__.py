# AI_FREELANCE_AUTOMATION/plugins/theme_plugins/__init__.py
"""
Theme Plugins Package Initialization

This package contains pluggable UI theme implementations that can be
dynamically loaded by the ThemeManager without restarting the application.

All theme plugins must:
- Inherit from `plugins.base_plugin.BasePlugin`
- Implement `apply()` and `revert()` methods
- Register themselves via plugin_manager during initialization

This __init__.py ensures clean namespace exposure and prevents import conflicts.
"""

from typing import TYPE_CHECKING

# Prevent circular imports — only import types for type checking
if TYPE_CHECKING:
    from plugins.base_plugin import BasePlugin

# Public API: explicitly list what should be imported with `from theme_plugins import *`
__all__ = [
    # Theme plugins will be dynamically discovered by PluginManager,
    # so no concrete classes are exported here.
]

# Optional: register known theme plugins if needed for static analysis or IDE support
# (not required for runtime, as PluginManager uses file system discovery)
# from .dark_theme_plugin import DarkThemePlugin
# from .light_theme_plugin import LightThemePlugin
# from .custom_theme_plugin import CustomThemePlugin

# Ensure this module is treated as a package and doesn't execute logic on import
def __getattr__(name):
    """Lazy-loading placeholder (optional). Not used in current architecture."""
    raise AttributeError(f"Module 'theme_plugins' has no attribute '{name}'")