# AI_FREELANCE_AUTOMATION/ui/components/client_widgets.py
"""
Client Widgets Module
Provides UI components for client management, communication history,
and relationship analytics in the autonomous freelancer system.
"""

import logging
from typing import Dict, Any, Optional, List
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel,
    QTextEdit, QPushButton, QScrollArea, QFrame, QTabWidget
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont

from core.config.unified_config_manager import UnifiedConfigManager
from core.security.audit_logger import AuditLogger
from services.notification.email_service import EmailService
from ui.theme_manager import ThemeManager

# Configure module-specific logger
logger = logging.getLogger(__name__)


class ClientProfileWidget(QWidget):
    """
    Displays and manages a client's profile: name, reputation, preferences,
    communication history, and active projects.
    Emits signals for user-initiated actions (e.g., send message).
    """
    send_message_requested = pyqtSignal(str, str)  # client_id, message
    request_review = pyqtSignal(str)               # client_id

    def __init__(
        self,
        client_id: str,
        parent: Optional[QWidget] = None,
        config_manager: Optional[UnifiedConfigManager] = None,
        theme_manager: Optional[ThemeManager] = None
    ):
        super().__init__(parent)
        self.client_id = client_id
        self.config = config_manager or UnifiedConfigManager.get_instance()
        self.theme = theme_manager or ThemeManager.get_instance()
        self._init_ui()
        self._load_client_data()
        logger.info(f"Intialized ClientProfileWidget for client {client_id}")

    def _init_ui(self):
        """Initialize the widget layout and styling."""
        self.setStyleSheet(self.theme.get_stylesheet("client_profile"))
        main_layout = QVBoxLayout()
        main_layout.setSpacing(12)

        # Header
        header = QLabel(f"Client: {self.client_id}")
        header.setFont(QFont("Segoe UI", 14, QFont.Bold))
        header.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(header)

        # Profile Group
        profile_group = QGroupBox("Profile & Preferences")
        profile_layout = QVBoxLayout()
        self.profile_text = QTextEdit()
        self.profile_text.setReadOnly(True)
        profile_layout.addWidget(self.profile_text)
        profile_group.setLayout(profile_layout)
        main_layout.addWidget(profile_group)

        # Communication History
        comm_group = QGroupBox("Recent Messages")
        comm_layout = QVBoxLayout()
        self.comm_history = QTextEdit()
        self.comm_history.setReadOnly(True)
        comm_layout.addWidget(self.comm_history)
        profile_group.setLayout(profile_layout)

        # Action Buttons
        button_layout = QHBoxLayout()
        self.send_btn = QPushButton("Send Message")
        self.review_btn = QPushButton("Request Review")
        self.send_btn.clicked.connect(self._on_send_message)
        self.review_btn.clicked.connect(self._on_request_review)
        button_layout.addWidget(self.send_btn)
        button_layout.addWidget(self.review_btn)
        main_layout.addLayout(button_layout)

        self.setLayout(main_layout)

    def _load_client_data(self):
        """Load client data from persistent storage (mocked here)."""
        try:
            # In real implementation, this would read from data/clients/{client_id}/
            profile_data = {
                "name": "John Doe",
                "reputation": 4.9,
                "preferred_language": "en",
                "response_time_avg": "2h",
                "active_projects": 2
            }
            history = [
                "[2026-01-20] Hi! Ready to start?",
                "[2026-01-21] Yes, please transcribe this file.",
                "[2026-01-22] Done! Here is your transcript."
            ]
            self.profile_text.setPlainText(
                "\n".join(f"{k}: {v}" for k, v in profile_data.items())
            )
            self.comm_history.setPlainText("\n".join(history))
        except Exception as e:
            logger.error(f"Failed to load client data for {self.client_id}: {e}")
            self.profile_text.setPlainText("⚠️ Error loading client data")

    def _on_send_message(self):
        """Emit signal to open message composer."""
        # In full app, this would open a dialog or use communicator service
        message = "Hello! How can I assist you today?"
        self.send_message_requested.emit(self.client_id, message)
        AuditLogger.log("ui_action", f"User initiated message to {self.client_id}")

    def _on_request_review(self):
        """Emit signal to request client review."""
        self.request_review.emit(self.client_id)
        AuditLogger.log("ui_action", f"Review requested from {self.client_id}")


class ClientListWidget(QScrollArea):
    """
    Scrollable list of all known clients with quick access to profiles.
    """
    client_selected = pyqtSignal(str)  # client_id

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        config_manager: Optional[UnifiedConfigManager] = None
    ):
        super().__init__(parent)
        self.config = config_manager or UnifiedConfigManager.get_instance()
        self.setWidgetResizable(True)
        self._init_ui()
        self._load_clients()

    def _init_ui(self):
        container = QWidget()
        self.layout = QVBoxLayout(container)
        self.layout.setAlignment(Qt.AlignTop)
        self.setWidget(container)

    def _load_clients(self):
        """Load client IDs from index (mocked)."""
        # Real: read data/clients/clients_index.json
        mock_clients = ["client_001", "client_002", "client_003"]
        for cid in mock_clients:
            btn = QPushButton(cid)
            btn.clicked.connect(lambda _, c=cid: self.client_selected.emit(c))
            self.layout.addWidget(btn)


class ClientDashboardWidget(QWidget):
    """
    Main tab for client-related UI: combines list and profile.
    """
    def __init__(
        self,
        parent: Optional[QWidget] = None,
        config_manager: Optional[UnifiedConfigManager] = None,
        theme_manager: Optional[ThemeManager] = None
    ):
        super().__init__(parent)
        self.config = config_manager or UnifiedConfigManager.get_instance()
        self.theme = theme_manager or ThemeManager.get_instance()
        self.current_client_widget: Optional[ClientProfileWidget] = None
        self._init_ui()

    def _init_ui(self):
        layout = QHBoxLayout()

        # Left: Client list
        self.client_list = ClientListWidget(config_manager=self.config)
        self.client_list.setFixedWidth(200)
        self.client_list.client_selected.connect(self._show_client_profile)
        layout.addWidget(self.client_list)

        # Right: Dynamic profile area
        self.profile_area = QVBoxLayout()
        placeholder = QLabel("Select a client to view details")
        placeholder.setAlignment(Qt.AlignCenter)
        self.profile_area.addWidget(placeholder)
        layout.addLayout(self.profile_area)

        self.setLayout(layout)

    def _show_client_profile(self, client_id: str):
        """Replace current profile view with new client."""
        # Clear previous widget
        while self.profile_area.count():
            item = self.profile_area.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Create new profile widget
        self.current_client_widget = ClientProfileWidget(
            client_id=client_id,
            config_manager=self.config,
            theme_manager=self.theme
        )
        self.profile_area.addWidget(self.current_client_widget)

        # Connect signals
        self.current_client_widget.send_message_requested.connect(self._handle_send_message)
        self.current_client_widget.request_review.connect(self._handle_review_request)

    def _handle_send_message(self, client_id: str, message: str):
        """Forward message to communication system (stub)."""
        logger.info(f"UI: Sending message to {client_id}: {message[:50]}...")
        # In real app: call IntelligentCommunicator via service locator

    def _handle_review_request(self, client_id: str):
        """Trigger review request workflow."""
        logger.info(f"UI: Requesting review from {client_id}")
        # In real app: trigger post-service automation


# Optional: Register widget for plugin/theme system
def register_client_widgets():
    """Hook for plugin system to register additional client widgets."""
    return {
        "profile": ClientProfileWidget,
        "list": ClientListWidget,
        "dashboard": ClientDashboardWidget
    }