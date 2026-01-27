# AI_FREELANCE_AUTOMATION/tests/integration/__init__.py
"""
Integration test package initializer.

This module ensures proper namespace packaging for integration tests
and provides shared utilities or fixtures that may be used across
multiple integration test modules.

It does NOT contain test logic itself — that belongs in individual test files.
"""

# Указывает Python, что это пакет (особенно важно при использовании namespace packages)
# Никаких импортов верхнего уровня, чтобы избежать побочных эффектов при сборке тестов

# Опционально: можно экспортировать общие утилиты, если они будут добавлены позже
# Например:
# from .shared_fixtures import setup_test_environment
# __all__ = ["setup_test_environment"]

# Пока оставляем чистым — соответствует best practices pytest и модульной архитектуре