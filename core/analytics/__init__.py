"""
AI Freelance Automation — Core Analytics Module
================================================

This package provides predictive analytics, market intelligence,
and data-driven decision support for autonomous freelance operations.

Modules:
- predictive_analytics: Forecasts job success, pricing, and demand
- market_analyzer: Monitors platform trends and competitor behavior
- price_predictor: Dynamically sets optimal bid prices
- success_predictor: Estimates likelihood of winning and client satisfaction

All components are designed for:
✅ Thread-safe operation
✅ Dependency injection compatibility
✅ Seamless integration with DecisionEngine and MonitoringSystem
✅ Hot-reload via config changes
✅ Zero side effects on import
"""

# Prevent accidental top-level imports that could cause circular dependencies
# Only expose public interfaces

from .predictive_analytics import PredictiveAnalytics
from .market_analyzer import MarketAnalyzer
from .price_predictor import PricePredictor
from .success_predictor import SuccessPredictor

# Public API
__all__ = [
    "PredictiveAnalytics",
    "MarketAnalyzer",
    "PricePredictor",
    "SuccessPredictor",
]

# Optional: module-level logger for diagnostics (not used unless needed)
import logging
logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())