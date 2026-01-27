# AI_FREELANCE_AUTOMATION/ui/components/settings_widgets.py
"""
Settings Widgets Module

Provides reusable, theme-aware UI components for application settings.
Supports dynamic configuration updates, validation, and real-time preview.
Integrates with core.config.unified_config_manager and ui.theme_manager.
"""

import logging
from typing import Any, Dict, Optional, Callable, List
from pathlib import Path

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel,
    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QCheckBox,
    QPushButton, QFileDialog, QMessageBox, QScrollArea, QFrame
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QPalette

from core.dependency.service_locator import ServiceLocator
from core.config.unified_config_manager import UnifiedConfigManager
from ui.theme_manager import ThemeManager

logger = logging.getLogger("SettingsWidgets")


class SettingsWidgetBase(QWidget):
    """Base class for all settings widgets with common functionality."""
    valueChanged = pyqtSignal(str, object)  # key, new_value

    def __init__(self, config_key: str, label_text: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.config_key = config_key
        self.label_text = label_text
        self._config_manager: Optional[UnifiedConfigManager] = None
        self._theme_manager: Optional[ThemeManager] = None
        self._setup_managers()
        self._init_ui()

    def _setup_managers(self):
        """Initialize service dependencies safely."""
        try:
            self._config_manager = ServiceLocator.get_service("config_manager")
            self._theme_manager = ServiceLocator.get_service("theme_manager")
        except Exception as e:
            logger.warning(f"Failed to load services in {self.__class__.__name__}: {e}")
            # Fallback: allow widget to work in design mode

    def _init_ui(self):
        raise NotImplementedError("Subclasses must implement _init_ui")

    def get_value(self) -> Any:
        raise NotImplementedError

    def set_value(self, value: Any):
        raise NotImplementedError

    def apply_theme(self):
        """Apply current theme to this widget."""
        if self._theme_manager:
            palette = self._theme_manager.get_palette()
            self.setPalette(palette)


class LabeledLineEdit(SettingsWidgetBase):
    def __init__(self, config_key: str, label_text: str, placeholder: str = "", parent: Optional[QWidget] = None):
        self.placeholder = placeholder
        super().__init__(config_key, label_text, parent)

    def _init_ui(self):
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        label = QLabel(self.label_text)
        self.line_edit = QLineEdit()
        self.line_edit.setPlaceholderText(self.placeholder)
        self.line_edit.textChanged.connect(lambda text: self.valueChanged.emit(self.config_key, text))

        layout.addWidget(label, 1)
        layout.addWidget(self.line_edit, 2)
        self.setLayout(layout)

        # Load initial value
        if self._config_manager:
            val = self._config_manager.get(self.config_key, "")
            self.line_edit.setText(str(val))

        self.apply_theme()

    def get_value(self) -> str:
        return self.line_edit.text().strip()

    def set_value(self, value: str):
        self.line_edit.setText(str(value))


class LabeledComboBox(SettingsWidgetBase):
    def __init__(
        self,
        config_key: str,
        label_text: str,
        options: List[str],
        option_values: Optional[List[Any]] = None,
        parent: Optional[QWidget] = None
    ):
        self.options = options
        self.option_values = option_values or options
        super().__init__(config_key, label_text, parent)

    def _init_ui(self):
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        label = QLabel(self.label_text)
        self.combo = QComboBox()
        self.combo.addItems(self.options)
        self.combo.currentIndexChanged.connect(
            lambda idx: self.valueChanged.emit(self.config_key, self.option_values[idx])
        )

        layout.addWidget(label, 1)
        layout.addWidget(self.combo, 2)
        self.setLayout(layout)

        # Set initial value
        if self._config_manager:
            current_val = self._config_manager.get(self.config_key)
            if current_val in self.option_values:
                idx = self.option_values.index(current_val)
                self.combo.setCurrentIndex(idx)

        self.apply_theme()

    def get_value(self) -> Any:
        idx = self.combo.currentIndex()
        return self.option_values[idx] if 0 <= idx < len(self.option_values) else None

    def set_value(self, value: Any):
        if value in self.option_values:
            self.combo.setCurrentIndex(self.option_values.index(value))


class LabeledSpinBox(SettingsWidgetBase):
    def __init__(
        self,
        config_key: str,
        label_text: str,
        min_val: int = 0,
        max_val: int = 100,
        step: int = 1,
        parent: Optional[QWidget] = None
    ):
        self.min_val = min_val
        self.max_val = max_val
        self.step = step
        super().__init__(config_key, label_text, parent)

    def _init_ui(self):
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        label = QLabel(self.label_text)
        self.spin = QSpinBox()
        self.spin.setRange(self.min_val, self.max_val)
        self.spin.setSingleStep(self.step)
        self.spin.valueChanged.connect(lambda v: self.valueChanged.emit(self.config_key, v))

        layout.addWidget(label, 1)
        layout.addWidget(self.spin, 2)
        self.setLayout(layout)

        if self._config_manager:
            val = self._config_manager.get(self.config_key, self.min_val)
            self.spin.setValue(int(val))

        self.apply_theme()

    def get_value(self) -> int:
        return self.spin.value()

    def set_value(self, value: int):
        self.spin.setValue(int(value))


class LabeledDoubleSpinBox(SettingsWidgetBase):
    def __init__(
        self,
        config_key: str,
        label_text: str,
        min_val: float = 0.0,
        max_val: float = 1.0,
        step: float = 0.01,
        decimals: int = 2,
        parent: Optional[QWidget] = None
    ):
        self.min_val = min_val
        self.max_val = max_val
        self.step = step
        self.decimals = decimals
        super().__init__(config_key, label_text, parent)

    def _init_ui(self):
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        label = QLabel(self.label_text)
        self.spin = QDoubleSpinBox()
        self.spin.setRange(self.min_val, self.max_val)
        self.spin.setSingleStep(self.step)
        self.spin.setDecimals(self.decimals)
        self.spin.valueChanged.connect(lambda v: self.valueChanged.emit(self.config_key, v))

        layout.addWidget(label, 1)
        layout.addWidget(self.spin, 2)
        self.setLayout(layout)

        if self._config_manager:
            val = self._config_manager.get(self.config_key, self.min_val)
            self.spin.setValue(float(val))

        self.apply_theme()

    def get_value(self) -> float:
        return self.spin.value()

    def set_value(self, value: float):
        self.spin.setValue(float(value))


class LabeledCheckBox(SettingsWidgetBase):
    def __init__(self, config_key: str, label_text: str, parent: Optional[QWidget] = None):
        super().__init__(config_key, label_text, parent)

    def _init_ui(self):
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        self.checkbox = QCheckBox(self.label_text)
        self.checkbox.stateChanged.connect(
            lambda state: self.valueChanged.emit(self.config_key, bool(state))
        )

        layout.addWidget(self.checkbox)
        layout.addStretch()
        self.setLayout(layout)

        if self._config_manager:
            val = self._config_manager.get(self.config_key, False)
            self.checkbox.setChecked(bool(val))

        self.apply_theme()

    def get_value(self) -> bool:
        return self.checkbox.isChecked()

    def set_value(self, value: bool):
        self.checkbox.setChecked(bool(value))


class FilePathSelector(SettingsWidgetBase):
    def __init__(
        self,
        config_key: str,
        label_text: str,
        file_filter: str = "All Files (*)",
        is_directory: bool = False,
        parent: Optional[QWidget] = None
    ):
        self.file_filter = file_filter
        self.is_directory = is_directory
        super().__init__(config_key, label_text, parent)

    def _init_ui(self):
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        label = QLabel(self.label_text)
        self.path_display = QLineEdit()
        self.path_display.setReadOnly(True)
        self.browse_btn = QPushButton("Browse…")
        self.browse_btn.clicked.connect(self._browse)

        layout.addWidget(label, 1)
        layout.addWidget(self.path_display, 3)
        layout.addWidget(self.browse_btn)

        self.setLayout(layout)

        if self._config_manager:
            path = self._config_manager.get(self.config_key, "")
            self.path_display.setText(str(path))

        self.apply_theme()

    def _browse(self):
        if self.is_directory:
            path = QFileDialog.getExistingDirectory(self, "Select Directory")
        else:
            path, _ = QFileDialog.getOpenFileName(self, "Select File", "", self.file_filter)

        if path:
            self.path_display.setText(path)
            self.valueChanged.emit(self.config_key, path)

    def get_value(self) -> str:
        return self.path_display.text()

    def set_value(self, value: str):
        self.path_display.setText(str(value))


class SettingsSection(QGroupBox):
    """A themed, collapsible section for grouping related settings."""
    def __init__(self, title: str, parent: Optional[QWidget] = None):
        super().__init__(title, parent)
        self._theme_manager: Optional[ThemeManager] = None
        try:
            self._theme_manager = ServiceLocator.get_service("theme_manager")
        except:
            pass
        self._init_ui()

    def _init_ui(self):
        self.setLayout(QVBoxLayout())
        self.apply_theme()

    def apply_theme(self):
        if self._theme_manager:
            palette = self._theme_manager.get_palette()
            self.setPalette(palette)
            # Optional: style title font, border, etc.

    def add_widget(self, widget: QWidget):
        self.layout().addWidget(widget)


class ScrollableSettingsContainer(QScrollArea):
    """Container that makes settings scrollable and responsive."""
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.container = QFrame()
        self.container.setLayout(QVBoxLayout())
        self.setWidget(self.container)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

    def add_section(self, section: QGroupBox):
        self.container.layout().addWidget(section)

    def add_stretch(self):
        self.container.layout().addStretch()


# Example usage helper (not part of production logic, but useful for testing)
def create_demo_settings_panel() -> ScrollableSettingsContainer:
    """Create a demo panel showing all widget types."""
    container = ScrollableSettingsContainer()

    # General section
    general = SettingsSection("General Settings")
    general.add_widget(LabeledLineEdit("user.name", "Full Name", "John Doe"))
    general.add_widget(LabeledComboBox("ui.language", "Language", ["English", "Русский"], ["en", "ru"]))
    general.add_widget(LabeledCheckBox("automation.enabled", "Enable Full Automation"))
    container.add_section(general)

    # Performance section
    perf = SettingsSection("Performance")
    perf.add_widget(LabeledSpinBox("ai.max_concurrent_jobs", "Max Concurrent Jobs", 1, 50, 1))
    perf.add_widget(LabeledDoubleSpinBox("ai.confidence_threshold", "Confidence Threshold", 0.0, 1.0, 0.01, 2))
    container.add_section(perf)

    # Paths
    paths = SettingsSection("Storage")
    paths.add_widget(FilePathSelector("data.root_path", "Data Directory", is_directory=True))
    container.add_section(paths)

    container.add_stretch()
    return container


if __name__ == "__main__":
    import sys
    from PyQt5.QtWidgets import QApplication
    app = QApplication(sys.argv)
    demo = create_demo_settings_panel()
    demo.show()
    sys.exit(app.exec_())