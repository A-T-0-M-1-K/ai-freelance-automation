# AI_FREELANCE_AUTOMATION/tools/code_analysis/security_scan.py
"""
Security scanner for static code analysis.
Detects common vulnerabilities: hardcoded secrets, unsafe patterns, insecure imports, etc.
Integrates with core.security.audit_logger and config system.
Designed to be used during CI, pre-commit, or runtime self-audit.
"""

import os
import re
import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Set
from dataclasses import dataclass

# Local imports (relative to project root)
from core.config.unified_config_manager import UnifiedConfigManager
from core.security.audit_logger import AuditLogger

# Initialize module logger
logger = logging.getLogger(__name__)


@dataclass
class SecurityIssue:
    """Represents a detected security vulnerability."""
    file_path: str
    line_number: int
    severity: str  # "low", "medium", "high", "critical"
    rule_id: str
    description: str
    suggestion: str


class SecurityScanner:
    """
    Static analysis tool for detecting security anti-patterns in Python code.
    Rules are loaded from config and can be extended via plugins.
    """

    def __init__(self, config_manager: Optional[UnifiedConfigManager] = None):
        self.config = config_manager or UnifiedConfigManager()
        self.audit_logger = AuditLogger()
        self.rules = self._load_rules()
        self.issues: List[SecurityIssue] = []

    def _load_rules(self) -> Dict[str, Dict[str, Any]]:
        """Load security rules from config or fallback to defaults."""
        try:
            rules = self.config.get("security.scan_rules", {})
            if not rules:
                logger.warning("No custom security scan rules found. Using defaults.")
                rules = self._get_default_rules()
            return rules
        except Exception as e:
            logger.error(f"Failed to load security rules: {e}. Using defaults.")
            return self._get_default_rules()

    def _get_default_rules(self) -> Dict[str, Dict[str, Any]]:
        """Return built-in default security rules."""
        return {
            "hardcoded_secret": {
                "pattern": r"(?i)(password|secret|token|key|api[_-]?key)['\"\s]*[=:]['\"]\s*[a-zA-Z0-9+/=]{10,}",
                "severity": "critical",
                "description": "Hardcoded secret detected",
                "suggestion": "Use environment variables or secure vault"
            },
            "eval_usage": {
                "pattern": r"\beval\s*\(",
                "severity": "high",
                "description": "Use of eval() is dangerous",
                "suggestion": "Avoid eval(); use safer alternatives like ast.literal_eval"
            },
            "exec_usage": {
                "pattern": r"\bexec\s*\(",
                "severity": "high",
                "description": "Use of exec() is dangerous",
                "suggestion": "Avoid exec(); refactor logic safely"
            },
            "pickle_usage": {
                "pattern": r"import\s+pickle|from\s+pickle\s+import",
                "severity": "medium",
                "description": "Pickle is insecure for untrusted data",
                "suggestion": "Use JSON or safer serialization"
            },
            "insecure_ssl": {
                "pattern": r"verify\s*=\s*False",
                "severity": "high",
                "description": "SSL certificate verification disabled",
                "suggestion": "Always enable SSL verification"
            },
            "debug_mode": {
                "pattern": r"(?i)debug\s*=\s*True",
                "severity": "medium",
                "description": "Debug mode enabled in production-like code",
                "suggestion": "Disable debug mode in production"
            }
        }

    def scan_file(self, file_path: Path) -> List[SecurityIssue]:
        """Scan a single Python file for security issues."""
        if not file_path.exists() or not file_path.suffix == ".py":
            return []

        issues: List[SecurityIssue] = []
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except Exception as e:
            logger.warning(f"Could not read file {file_path}: {e}")
            return []

        for line_num, line in enumerate(lines, start=1):
            for rule_id, rule in self.rules.items():
                if re.search(rule["pattern"], line):
                    issue = SecurityIssue(
                        file_path=str(file_path),
                        line_number=line_num,
                        severity=rule["severity"],
                        rule_id=rule_id,
                        description=rule["description"],
                        suggestion=rule["suggestion"]
                    )
                    issues.append(issue)
                    self.audit_logger.log_security_event(
                        event_type="code_vulnerability_detected",
                        details={
                            "file": str(file_path),
                            "line": line_num,
                            "rule": rule_id,
                            "severity": rule["severity"]
                        }
                    )

        return issues

    def scan_directory(self, root_dir: Path, exclude_dirs: Optional[Set[str]] = None) -> List[SecurityIssue]:
        """Recursively scan all Python files in a directory."""
        if exclude_dirs is None:
            exclude_dirs = {"__pycache__", ".git", "venv", "env", "node_modules", "logs", "backup"}

        all_issues: List[SecurityIssue] = []
        for py_file in root_dir.rglob("*.py"):
            if any(part in exclude_dirs for part in py_file.parts):
                continue
            issues = self.scan_file(py_file)
            all_issues.extend(issues)

        self.issues = all_issues
        logger.info(f"Security scan completed: {len(all_issues)} issues found in {root_dir}")
        return all_issues

    def get_report(self) -> Dict[str, Any]:
        """Generate a structured JSON report of findings."""
        report = {
            "total_issues": len(self.issues),
            "by_severity": {},
            "details": []
        }

        severity_counts = {"low": 0, "medium": 0, "high": 0, "critical": 0}
        for issue in self.issues:
            severity_counts[issue.severity] += 1
            report["details"].append({
                "file": issue.file_path,
                "line": issue.line_number,
                "severity": issue.severity,
                "rule": issue.rule_id,
                "description": issue.description,
                "suggestion": issue.suggestion
            })

        report["by_severity"] = {k: v for k, v in severity_counts.items() if v > 0}
        return report

    def has_critical_issues(self) -> bool:
        """Check if any critical or high severity issues exist."""
        return any(issue.severity in ("critical", "high") for issue in self.issues)


# Standalone function for CLI or script usage
def run_security_scan(target_path: str = ".", config_path: Optional[str] = None) -> int:
    """
    Run security scan and return exit code (0 = OK, 1 = issues found).
    Used by CI/CD or pre-commit hooks.
    """
    config = UnifiedConfigManager(config_path) if config_path else UnifiedConfigManager()
    scanner = SecurityScanner(config)

    target = Path(target_path).resolve()
    if not target.exists():
        logger.error(f"Target path does not exist: {target}")
        return 1

    if target.is_file():
        issues = scanner.scan_file(target)
    else:
        issues = scanner.scan_directory(target)

    report = scanner.get_report()
    print(json.dumps(report, indent=2, ensure_ascii=False))

    # Log summary
    if issues:
        logger.warning(f"⚠️  Security scan found {len(issues)} issues.")
        if scanner.has_critical_issues():
            logger.critical("🔴 Critical/high severity issues detected!")
            return 1
        else:
            logger.info("🟡 Only low/medium issues found.")
            return 0
    else:
        logger.info("✅ No security issues found.")
        return 0


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    target = sys.argv[1] if len(sys.argv) > 1 else "."
    exit_code = run_security_scan(target)
    sys.exit(exit_code)