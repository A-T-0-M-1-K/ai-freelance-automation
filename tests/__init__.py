"""
AI Freelance Automation — Test Suite Initialization
==================================================

This package contains all automated tests for the AI_FREELANCE_AUTOMATION system.
It ensures correctness, reliability, and regression safety across all components.

Design Principles:
- 100% test isolation using fixtures and mocks
- Full coverage of core logic (target: ≥95%)
- Integration tests for cross-component workflows
- End-to-end simulation of autonomous freelance cycles
- Security and compliance validation
- Performance and stress testing

All tests are structured to run in CI/CD pipelines with zero external dependencies
by default (mocked platforms, in-memory DBs, simulated AI models).

Note: This __init__.py is intentionally empty except for this docstring to:
- Mark the directory as a Python package
- Avoid accidental side effects on import
- Allow pytest autodiscovery
"""

# No imports or executable code here to ensure safe, lazy test discovery.
# Actual test logic resides in submodules (e.g., test_core.py, test_ai_services.py).