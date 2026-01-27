"""
Unit test package initialization for AI_FREELANCE_AUTOMATION.

This file ensures:
- Proper Python package structure for test discovery.
- Isolation from production code during testing.
- Safe import paths without side effects.
- Compatibility with pytest, unittest, and coverage tools.

DO NOT add business logic here. Keep it empty or minimal.
"""

# This file intentionally left nearly empty to comply with Python packaging standards.
# It enables `tests.unit` to be recognized as a proper package.

# Optional: Prevent accidental execution as main
if __name__ == "__main__":
    raise RuntimeError("This is a test package module and should not be executed directly.")

# Optional: Enable relative imports in test modules (not required in modern Python, but safe)
# No imports are performed here to avoid test contamination or circular dependencies.