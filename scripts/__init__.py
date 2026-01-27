"""
Initialization module for the `scripts` package.

Purpose:
--------
This package contains standalone utility scripts used for:
- One-time setup or migration tasks
- Data backfilling or cleanup
- Manual diagnostics or recovery procedures
- Development or deployment helpers

⚠️ Important:
- Scripts in this package are NOT part of the autonomous runtime.
- They are NOT imported or executed during normal operation.
- They must be idempotent and safe to run manually.
- They should use the same core infrastructure (config, logging, crypto)
  via proper dependency injection to avoid duplication.

Structure Guidelines:
--------------------
- Each script should be a separate `.py` file with clear name (e.g., `migrate_v2_db.py`).
- No script should be auto-executed on import.
- Avoid placing business logic here — delegate to services/core when possible.
- All scripts must respect security policies (e.g., never log secrets).

Example usage:
    python -m scripts.recover_failed_jobs --dry-run

This __init__.py file intentionally contains no executable code.
"""

# Explicitly define public interface (empty by design)
__all__ = []

# Prevent accidental execution
if __name__ == "__main__":
    raise RuntimeError(
        "This is an initialization module for the 'scripts' package. "
        "It is not meant to be executed directly. "
        "Run individual scripts as modules instead (e.g., `python -m scripts.example`)."
    )