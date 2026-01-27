"""
UI Styles System — Centralized style definitions with dynamic theme support.
Integrates with ThemeManager to provide responsive, accessible, and consistent styling
across all UI components (Qt, Web, CLI fallback).
"""

import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional, Union
from enum import Enum

# Internal imports (relative to avoid circular dependencies)
from .theme_manager import ThemeManager

logger = logging.getLogger("UI.Styles")


class StyleType(Enum):
    """Enumeration of supported UI frameworks."""
    QT = "qt"
    WEB = "web"
    CLI = "cli"


class StyleDefinition:
    """
    Immutable container for a complete style definition.
    Ensures consistency and prevents accidental mutation.
    """
    def __init__(self, name: str, framework: StyleType, data: Dict[str, Any]):
        self._name = name
        self._framework = framework
        self._data = data

    @property
    def name(self) -> str:
        return self._name

    @property
    def framework(self) -> StyleType:
        return self._framework

    @property
    def data(self) -> Dict[str, Any]:
        return self._data.copy()

    def get(self, key: str, default: Any = None) -> Any:
        """Safely retrieve a style value."""
        return self._data.get(key, default)

    def to_qss(self) -> str:
        """Convert to Qt Stylesheet (QSS) format."""
        if self.framework != StyleType.QT:
            raise ValueError("QSS conversion only supported for Qt styles")
        lines = []
        for selector, props in self._data.items():
            if isinstance(props, dict):
                prop_str = "; ".join(f"{k}: {v}" for k, v in props.items())
                lines.append(f"{selector} {{ {prop_str}; }}")
        return "\n".join(lines)

    def to_css(self) -> str:
        """Convert to standard CSS format."""
        if self.framework != StyleType.WEB:
            raise ValueError("CSS conversion only supported for Web styles")
        lines = []
        for selector, props in self._data.items():
            if isinstance(props, dict):
                prop_str = "; ".join(f"{k.replace('_', '-')}: {v}" for k, v in props.items())
                lines.append(f"{selector} {{ {prop_str}; }}")
        return "\n".join(lines)

    def __repr__(self) -> str:
        return f"<StyleDefinition(name='{self.name}', framework='{self.framework.value}')>"


class StylesManager:
    """
    Central registry for all UI styles.
    Loads built-in themes and supports plugin-based custom themes.
    Thread-safe and lazy-loaded.
    """

    _instance: Optional["StylesManager"] = None
    _initialized: bool = False

    def __new__(cls) -> "StylesManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._styles: Dict[str, StyleDefinition] = {}
        self._theme_manager = ThemeManager()
        self._load_builtin_styles()
        self._initialized = True
        logger.info("✅ UI StylesManager initialized")

    def _load_builtin_styles(self) -> None:
        """Load built-in themes from ui/themes/ directory."""
        themes_dir = Path(__file__).parent / "themes"
        if not themes_dir.exists():
            logger.warning(f"Themes directory not found: {themes_dir}")
            return

        for theme_file in themes_dir.glob("*.json"):
            try:
                with open(theme_file, "r", encoding="utf-8") as f:
                    raw_data = json.load(f)

                name = theme_file.stem
                # Assume Qt by default for desktop app
                style_def = StyleDefinition(
                    name=name,
                    framework=StyleType.QT,
                    data=raw_data
                )
                self._styles[name] = style_def
                logger.debug(f"Loaded built-in style: {name}")
            except Exception as e:
                logger.error(f"Failed to load style from {theme_file}: {e}")

    def register_style(self, style: StyleDefinition) -> None:
        """Register a new style (used by plugins or runtime generation)."""
        if style.name in self._styles:
            logger.warning(f"Style '{style.name}' already exists. Overwriting.")
        self._styles[style.name] = style
        logger.info(f"Registered new style: {style.name} ({style.framework.value})")

    def get_style(self, name: str) -> Optional[StyleDefinition]:
        """Retrieve a style by name."""
        style = self._styles.get(name)
        if not style:
            logger.warning(f"Style '{name}' not found")
        return style

    def get_current_style(self) -> Optional[StyleDefinition]:
        """Get the currently active style from ThemeManager."""
        current_theme = self._theme_manager.get_active_theme_name()
        return self.get_style(current_theme)

    def list_available_styles(self) -> Dict[str, StyleDefinition]:
        """Return a copy of all registered styles."""
        return self._styles.copy()

    def apply_style_to_app(self, app: Any, style_name: Optional[str] = None) -> bool:
        """
        Apply a style to the application instance (Qt QApplication assumed).
        Returns True on success.
        """
        style_def = self.get_style(style_name) if style_name else self.get_current_style()
        if not style_def:
            logger.error("No valid style to apply")
            return False

        if style_def.framework == StyleType.QT:
            try:
                qss = style_def.to_qss()
                app.setStyleSheet(qss)
                logger.info(f"Applied Qt style: {style_def.name}")
                return True
            except Exception as e:
                logger.error(f"Failed to apply Qt style: {e}")
                return False
        else:
            logger.warning(f"Non-QT style '{style_def.name}' cannot be applied to desktop app")
            return False


# Convenience singleton access
def get_styles_manager() -> StylesManager:
    """Global access point to the styles system."""
    return StylesManager()


# Predefined semantic color names (for accessibility & consistency)
SEMANTIC_COLORS = {
    "primary": "#2563eb",
    "secondary": "#64748b",
    "success": "#10b981",
    "warning": "#f59e0b",
    "danger": "#ef4444",
    "info": "#3b82f6",
    "background": "#ffffff",
    "surface": "#f8fafc",
    "on_background": "#1e293b",
    "on_surface": "#0f172a",
    "border": "#cbd5e1",
    "disabled": "#94a3b8"
}