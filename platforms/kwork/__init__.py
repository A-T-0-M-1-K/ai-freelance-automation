# AI_FREELANCE_AUTOMATION/platforms/kwork/__init__.py
"""
Kwork platform integration package.
Provides unified access to Kwork-specific components: client, scraper, and API wrapper.
Ensures clean module import structure and avoids circular dependencies.
"""

from .client import KworkClient
from .scraper import KworkScraper
from .api_wrapper import KworkAPIWrapper

# Public API — only expose stable, tested interfaces
__all__ = [
    "KworkClient",
    "KworkScraper",
    "KworkAPIWrapper",
]

# Optional: package-level metadata
__version__ = "1.0.0"
__platform_name__ = "kwork"