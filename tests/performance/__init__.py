"""
Performance Test Suite Initialization
=====================================

This package contains performance benchmarks and stress tests for the AI Freelance Automation system.
All tests are designed to validate:
- System responsiveness under load
- Resource consumption (CPU, memory, I/O)
- Scalability of concurrent job processing
- AI inference latency and throughput
- Recovery time after simulated failures

The __init__.py ensures proper test discovery, namespace isolation,
and integration with the global testing framework without side effects.

No logic is executed on import — only metadata and safe exports.
"""

# Prevent accidental execution of test logic during import
# This file is intentionally left as a namespace package marker

# Optional: Define public API for this subpackage (if needed in future)
__all__ = []

# Metadata for test runner compatibility
__package_metadata__ = {
    "test_type": "performance",
    "supports_parallel_execution": True,
    "requires_gpu": False,
    "min_python_version": "3.10",
}

# Ensure compatibility with pytest, unittest, and custom test orchestrators
# No imports from core/ or services/ to avoid circular dependencies or premature initialization