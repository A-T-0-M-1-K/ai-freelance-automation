"""
UI Themes Package Initialization
================================

This package provides theme management for the AI Freelance Automation UI.
Themes control visual appearance: colors, fonts, spacing, and component styles.

All themes must conform to the BaseTheme interface.
The ThemeManager (in ui/theme_manager.py) loads and applies themes dynamically.

Exports:
- BaseTheme: Abstract base class for all themes
- DarkTheme, LightTheme: Built-in default themes
- register_theme(), get_theme(), list_themes(): Theme registry utilities

Note: This module is intentionally lightweight to avoid circular imports.
Actual theme definitions and logic reside in individual theme modules.
"""

from typing import Dict, Type
from abc import ABC, abstractmethod

# Registry for available themes
_THEME_REGISTRY: Dict[str, Type["BaseTheme"]] = {}


class BaseTheme(ABC):
    """Abstract base class defining the contract for all UI themes."""

    name: str
    display_name: str
    description: str

    @abstractmethod
    def get_stylesheet(self) -> str:
        """Return the complete Qt/CSS-compatible stylesheet as a string."""
        pass

    @abstractmethod
    def get_palette(self) -> dict:
        """Return a dictionary of semantic color roles (e.g., 'primary', 'background')."""
        pass

    @abstractmethod
    def to_dict(self) -> dict:
        """Serialize theme to a JSON-compatible dictionary."""
        pass


def register_theme(theme_class: Type[BaseTheme]) -> None:
    """
    Register a theme class in the global registry.
    Used by individual theme modules on import.
    """
    if not issubclass(theme_class, BaseTheme):
        raise TypeError(f"Only subclasses of BaseTheme can be registered. Got: {theme_class}")
    _THEME_REGISTRY[theme_class.name] = theme_class


def get_theme(name: str) -> BaseTheme:
    """Instantiate and return a theme by its registered name."""
    if name not in _THEME_REGISTRY:
        available = ', '.join(_THEME_REGISTRY.keys())
        raise ValueError(f"Theme '{name}' not found. Available themes: {available}")
    return _THEME_REGISTRY[name]()


def list_themes() -> Dict[str, str]:
    """Return a mapping of theme names to their display names."""
    return {name: cls.display_name for name, cls in _THEME_REGISTRY.items()}


# Optional: Auto-discover built-in themes (safe import)
try:
    from .dark_theme import DarkTheme  # noqa: F401
    from .light_theme import LightTheme  # noqa: F401
except ImportError:
    # Themes may be loaded later via plugins or lazy loading
    pass
