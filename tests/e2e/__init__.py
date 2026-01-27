"""
End-to-End (E2E) Tests Package Initialization
=============================================

This package contains high-level integration tests that simulate real-world
scenarios of the AI Freelance Automation system operating autonomously:

- Job discovery → bidding → communication → execution → delivery → payment
- Cross-platform interactions (Upwork, Fiverr, etc.)
- AI service orchestration (transcription, translation, copywriting)
- Payment processing and client follow-up
- Self-healing and anomaly recovery under failure conditions

All E2E tests:
- Run in isolated environments (via pytest fixtures or Docker)
- Use mocked external APIs by default (configurable to real endpoints in CI/CD)
- Validate system behavior against business SLAs (e.g., 99.9% success rate)
- Capture full logs, metrics, and audit trails for forensic analysis

This __init__.py ensures proper namespace packaging and prevents accidental
execution of test logic during import.
"""

# Ensure this package is treated as a namespace package if needed (optional)
# Not required in modern Python (3.3+), but explicit is better than implicit.
__path__ = __import__('pkgutil').extend_path(__path__, __name__)

# Prevent unintended side effects on import
def _ensure_test_safety():
    """Guard against accidental production execution."""
    import os
    env = os.getenv("APP_ENV", "development").lower()
    if env not in ("test", "testing", "ci"):
        raise RuntimeError(
            "E2E test modules must only be imported in test environments. "
            "Set APP_ENV=test to proceed."
        )

# Optional: enable safety check in strict mode (disabled by default for flexibility)
# _ensure_test_safety()

# Public API of the e2e test package (empty by design — tests are discovered by filename)
__all__ = []