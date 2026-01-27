# setup.py
"""
Setup script for AI_FREELANCE_AUTOMATION — a fully autonomous AI freelancer system.

This file provides backward compatibility with legacy build tools.
Modern builds should use `pyproject.toml` (PEP 621). This script delegates
to setuptools when needed but does not duplicate configuration.

DO NOT edit dependencies or metadata here — manage them in `pyproject.toml`.
"""

import os
from setuptools import setup, find_packages

# Защита от запуска вне корня проекта
if not os.path.exists("pyproject.toml"):
    raise RuntimeError(
        "❌ This setup.py must be run from the root of the AI_FREELANCE_AUTOMATION project.\n"
        "Expected 'pyproject.toml' to be present."
    )

# Автоматическое обнаружение всех подпакетов (включая вложенные)
packages = find_packages(exclude=["tests*", "scripts*", "docs*", "docker*", "backup*"])

# Основной вызов setup()
# Все метаданные и зависимости берутся из pyproject.toml при использовании современных pip/setuptools
setup(
    name="ai-freelance-automation",
    version="0.1.0",  # fallback; лучше управлять через pyproject.toml + dynamic versioning
    packages=packages,
    python_requires=">=3.10",
    include_package_data=True,
    zip_safe=False,
    # NOTE: В современных проектах поля ниже (install_requires, entry_points и т.д.)
    # должны быть определены в pyproject.toml. Этот файл лишь обеспечивает совместимость.
)