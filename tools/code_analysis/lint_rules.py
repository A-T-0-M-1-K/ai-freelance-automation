# tools/code_analysis/lint_rules.py
"""
Lint Rules Configuration for AI Freelance Automation System

This module defines custom linting rules and configurations used by the
code quality analysis pipeline. It integrates with standard linters (flake8,
pylint, ruff, etc.) and enforces project-specific coding standards aligned
with enterprise-grade reliability, security, and maintainability.

Key Features:
- Enforces strict type safety (PEP 484, PEP 526)
- Blocks unsafe patterns (e.g., eval(), exec(), bare excepts)
- Enforces docstring standards (Google style)
- Ensures secure coding practices (no hardcoded secrets, safe subprocess usage)
- Compatible with pre-commit hooks and CI/CD pipelines

Author: AI Freelance Automation System
License: MIT
"""

from typing import Dict, List, Set, Tuple, Optional
import re


# ==============================
# CORE LINTING RULES
# ==============================

class LintRuleSet:
    """Encapsulates a set of linting rules for different contexts."""

    def __init__(self) -> None:
        self._rules: Dict[str, dict] = self._build_rules()

    def get_rule(self, rule_id: str) -> Optional[dict]:
        """Retrieve a lint rule by its ID."""
        return self._rules.get(rule_id)

    def get_all_rule_ids(self) -> List[str]:
        """Return all defined rule IDs."""
        return list(self._rules.keys())

    def _build_rules(self) -> Dict[str, dict]:
        """Construct the full rule dictionary."""
        return {
            # --- Type Safety ---
            "TYP001": {
                "description": "All function arguments and return types must be annotated",
                "severity": "error",
                "category": "types",
                "pattern": None,  # Handled by mypy/pyright, not regex
            },
            "TYP002": {
                "description": "Variables in global scope must have type annotations",
                "severity": "warning",
                "category": "types",
            },

            # --- Security ---
            "SEC001": {
                "description": "Hardcoded credentials or API keys detected",
                "severity": "critical",
                "category": "security",
                "pattern": re.compile(
                    r"(?i)(password|api[_-]?key|secret|token|auth|bearer)\s*[:=]\s*[\"'][^\"']{4,}[\"']"
                ),
            },
            "SEC002": {
                "description": "Use of eval() or exec() is forbidden",
                "severity": "critical",
                "category": "security",
                "pattern": re.compile(r"\b(eval|exec)\s*\("),
            },
            "SEC003": {
                "description": "Unsafe subprocess call without shell=False",
                "severity": "high",
                "category": "security",
                "pattern": re.compile(r"subprocess\.\w+\([^)]*shell\s*=\s*True"),
            },

            # --- Error Handling ---
            "ERR001": {
                "description": "Bare except: clause detected (use specific exceptions)",
                "severity": "error",
                "category": "errors",
                "pattern": re.compile(r"except\s*:\s*$"),
            },
            "ERR002": {
                "description": "Exception must be logged or re-raised in except block",
                "severity": "warning",
                "category": "errors",
                # Heuristic: except block without 'log', 'raise', or 'return'
                "pattern": re.compile(
                    r"except\s+\w+\s+as\s+\w+:\s*\n(?:\s{4}|\t)[^\n]*\n(?!\s*(logging|logger|raise|return))"
                ),
            },

            # --- Documentation ---
            "DOC001": {
                "description": "Public function missing Google-style docstring",
                "severity": "warning",
                "category": "docs",
                # Note: Full validation requires AST parsing (handled externally)
            },
            "DOC002": {
                "description": "Module-level docstring missing",
                "severity": "info",
                "category": "docs",
            },

            # --- Performance & Best Practices ---
            "PERF001": {
                "description": "Use of time.sleep() in async context (use asyncio.sleep)",
                "severity": "error",
                "category": "performance",
                "pattern": re.compile(r"\btime\.sleep\s*\("),
            },
            "BP001": {
                "description": "Global mutable state (list/dict) at module level",
                "severity": "warning",
                "category": "best_practice",
                "pattern": re.compile(r"^\w+\s*=\s*(\[|\{)"),
            },
            "BP002": {
                "description": "Magic numbers detected (use named constants)",
                "severity": "info",
                "category": "best_practice",
                # Simple heuristic: unassigned numeric literals > 999 or < -999
                "pattern": re.compile(r"[^a-zA-Z_]\b\d{4,}\b"),
            },

            # --- AI & Autonomy Specific ---
            "AI001": {
                "description": "AI service called without timeout or retry policy",
                "severity": "error",
                "category": "ai_reliability",
                # Example: detect openai.ChatCompletion.create without timeout
                "pattern": re.compile(
                    r"(openai|anthropic|google_ai)\.\w+\.\w+\([^)]*(?!timeout)[^)]*\)"
                ),
            },
            "AI002": {
                "description": "No fallback model specified for critical AI operation",
                "severity": "warning",
                "category": "ai_reliability",
            },
        }

    def validate_code_snippet(self, code: str, rule_ids: Optional[List[str]] = None) -> List[Dict]:
        """
        Validate a code snippet against selected rules.

        Args:
            code: Source code as string
            rule_ids: Subset of rules to apply (None = all regex-based rules)

        Returns:
            List of violations, each with 'rule_id', 'line', 'message', 'severity'
        """
        violations = []
        lines = code.splitlines()

        rule_subset = (
            {rid: self._rules[rid] for rid in rule_ids if rid in self._rules}
            if rule_ids
            else self._rules
        )

        for line_num, line in enumerate(lines, start=1):
            for rule_id, rule in rule_subset.items():
                pattern = rule.get("pattern")
                if not pattern:
                    continue
                if pattern.search(line):
                    violations.append({
                        "rule_id": rule_id,
                        "line": line_num,
                        "message": rule["description"],
                        "severity": rule["severity"],
                        "category": rule["category"]
                    })

        return violations


# ==============================
# PREDEFINED RULE SETS
# ==============================

STRICT_RULE_SET: Set[str] = {
    "TYP001", "SEC001", "SEC002", "SEC003", "ERR001", "PERF001", "AI001"
}

PRODUCTION_RULE_SET: Set[str] = STRICT_RULE_SET | {
    "TYP002", "ERR002", "DOC001", "AI002"
}

DEVELOPMENT_RULE_SET: Set[str] = PRODUCTION_RULE_SET | {
    "DOC002", "BP001", "BP002"
}

# ==============================
# EXPORTED INSTANCE
# ==============================

LINT_RULES = LintRuleSet()

# ==============================
# USAGE EXAMPLE (for testing)
# ==============================

if __name__ == "__main__":
    test_code = '''
import time
import subprocess
def bad_func():
    password = "12345"
    eval("print('hack')")
    try:
        pass
    except:
        pass
    subprocess.run("ls", shell=True)
    time.sleep(1)
    '''

    violations = LINT_RULES.validate_code_snippet(test_code, list(STRICT_RULE_SET))
    for v in violations:
        print(f"[{v['severity'].upper()}] {v['rule_id']}:{v['line']} - {v['message']}")