# AI_FREELANCE_AUTOMATION/platforms/upwork/__init__.py
"""
Upwork Platform Integration Module
==================================

This package provides a complete integration layer for the Upwork freelance platform.
It includes:
- API client for authenticated requests
- Job scraper with intelligent filtering
- Bid automation and contract management
- Platform-specific configuration loader

All components are designed to work within the unified platform abstraction
defined in `platforms/platform_factory.py` and respect dependency injection,
logging, security, and monitoring standards of the core system.

Exports only public interfaces to avoid tight coupling.
"""

from .client import UpworkClient
from .scraper import UpworkJobScraper
from .api_wrapper import UpworkAPIWrapper

# Public API — used by platform_factory and automation modules
__all__ = [
    "UpworkClient",
    "UpworkJobScraper",
    "UpworkAPIWrapper"
]