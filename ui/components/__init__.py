"""
UI Components Package Initialization
====================================

This package contains reusable UI components for the AI Freelance Automation dashboard.
All components are designed to be:
- Decoupled from business logic
- Theme-aware (support light/dark/custom themes)
- Responsive and accessible
- Compatible with both desktop and web interfaces

Exports only public component classes to avoid namespace pollution and circular imports.
"""

# Import component classes for convenient access
from .dashboard_widgets import (
    JobStatusWidget,
    PerformanceMetricsWidget,
    IncomeOverviewWidget,
    AlertPanelWidget,
)
from .job_widgets import (
    JobCardWidget,
    JobDetailPanel,
    BidEditorWidget,
    DeliverablePreviewWidget,
)
from .client_widgets import (
    ClientProfileWidget,
    ConversationHistoryWidget,
    SentimentIndicatorWidget,
)
from .finance_widgets import (
    InvoiceListWidget,
    PaymentStatusWidget,
    TaxSummaryWidget,
)
from .monitoring_widgets import (
    SystemHealthWidget,
    AnomalyAlertWidget,
    ResourceUsageWidget,
)
from .settings_widgets import (
    ProfileSettingsWidget,
    PlatformConfigWidget,
    AISettingsPanel,
    NotificationPreferencesWidget,
)

# Define public interface
__all__ = [
    # Dashboard
    'JobStatusWidget',
    'PerformanceMetricsWidget',
    'IncomeOverviewWidget',
    'AlertPanelWidget',

    # Jobs
    'JobCardWidget',
    'JobDetailPanel',
    'BidEditorWidget',
    'DeliverablePreviewWidget',

    # Clients
    'ClientProfileWidget',
    'ConversationHistoryWidget',
    'SentimentIndicatorWidget',

    # Finance
    'InvoiceListWidget',
    'PaymentStatusWidget',
    'TaxSummaryWidget',

    # Monitoring
    'SystemHealthWidget',
    'AnomalyAlertWidget',
    'ResourceUsageWidget',

    # Settings
    'ProfileSettingsWidget',
    'PlatformConfigWidget',
    'AISettingsPanel',
    'NotificationPreferencesWidget',
]

# Optional: register components in a global registry if needed by UI framework
# (e.g., for dynamic loading or plugin-based UI)
_COMPONENT_REGISTRY = {
    cls.__name__: cls for cls in __all__
}

def get_component(name: str):
    """Safely retrieve a UI component by name."""
    return _COMPONENT_REGISTRY.get(name)

# Prevent accidental instantiation or misuse
del cls