"""
AI Freelance Automation — Migrations Package

This package contains database schema migration scripts for persistent storage
used by the autonomous AI freelancer system (e.g., job history, client data,
payment records, AI model logs).

This __init__.py ensures the directory is recognized as a Python package
and provides safe, side-effect-free initialization.

No logic is executed on import to maintain startup performance and avoid
circular dependencies.

Structure follows Alembic-compatible conventions but remains agnostic
to allow integration with custom or alternative migration systems.
"""

# Explicitly define public API (empty by design — migrations are managed externally)
__all__ = []

# Prevent accidental execution of logic on import
# This file is intentionally left minimal for safety and compatibility