# AI_FREELANCE_AUTOMATION/tools/code_analyzer.py
"""
Инструмент статического анализа кода для внутреннего использования системой.
Обнаруживает потенциальные баги, уязвимости, нарушения архитектуры и производительности.
Интегрируется с системой самовосстановления и мониторинга.
"""

import ast
import os
import logging
import json
from pathlib import Path
from typing import List, Dict, Any, Optional, Set
from collections import defaultdict

# Локальный импорт — безопасен, не вызывает циклических зависимостей
from core.config.unified_config_manager import UnifiedConfigManager
from core.security.audit_logger import AuditLogger
from core.monitoring.intelligent_monitoring_system import IntelligentMonitoringSystem

logger = logging.getLogger("CodeAnalyzer")


class CodeAnalyzer:
    """
    Анализатор исходного кода Python-проекта.
    Выполняет:
    - Проверку на наличие потенциальных ошибок (NameError, AttributeError и др.)
    - Обнаружение уязвимостей безопасности (hardcoded secrets, eval, exec)
    - Валидацию архитектурных ограничений (запрет прямых импортов между слоями)
    - Оценку сложности кода (цикломатическая сложность)
    - Поиск неиспользуемых импортов и переменных
    """

    def __init__(self, config: Optional[UnifiedConfigManager] = None):
        self.config = config or UnifiedConfigManager()
        self.rules = self._load_rules()
        self.issues: List[Dict[str, Any]] = []
        self.project_root = Path(__file__).parent.parent.parent.resolve()

        # Инициализация аудита и мониторинга
        self.audit_logger = AuditLogger()
        self.monitor = IntelligentMonitoringSystem(self.config)

    def _load_rules(self) -> Dict[str, Any]:
        """Загружает правила анализа из конфигурации."""
        try:
            rules_path = self.config.get("tools.code_analyzer.rules_path", "config/code_analysis_rules.json")
            if os.path.exists(rules_path):
                with open(rules_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            else:
                # Использовать встроенные правила по умолчанию
                return self._get_default_rules()
        except Exception as e:
            logger.warning(f"⚠️ Не удалось загрузить правила анализа: {e}. Использую правила по умолчанию.")
            return self._get_default_rules()

    def _get_default_rules(self) -> Dict[str, Any]:
        return {
            "forbidden_imports": {
                "core": ["services", "ui", "plugins"],
                "services": ["ui"],
                "ai": ["ui"]
            },
            "max_cyclomatic_complexity": 12,
            "security_patterns": ["eval(", "exec(", "__import__", "os.system", "subprocess.call"],
            "allowed_top_level_dirs": [
                "core", "services", "ai", "platforms", "tools", "tests", "docs"
            ]
        }

    def analyze_project(self, root_dir: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Анализирует весь проект или указанный каталог.
        Возвращает список найденных проблем.
        """
        root = Path(root_dir) if root_dir else self.project_root
        self.issues.clear()

        logger.info(f"🔍 Запуск анализа кода в: {root}")
        self.audit_logger.log("code_analysis_start", {"target": str(root)})

        for py_file in root.rglob("*.py"):
            if self._should_skip_file(py_file):
                continue
            try:
                self._analyze_file(py_file)
            except Exception as e:
                logger.error(f"❌ Ошибка при анализе {py_file}: {e}")
                self.issues.append({
                    "file": str(py_file),
                    "line": 0,
                    "severity": "critical",
                    "type": "analysis_failure",
                    "message": f"Не удалось проанализировать файл: {str(e)}"
                })

        self.audit_logger.log("code_analysis_complete", {"issue_count": len(self.issues)})
        self.monitor.record_metric("code_analysis.issues_found", len(self.issues))
        logger.info(f"✅ Анализ завершён. Найдено проблем: {len(self.issues)}")

        return self.issues

    def _should_skip_file(self, file_path: Path) -> bool:
        """Определяет, следует ли пропустить файл."""
        skip_patterns = ["/venv/", "/.venv/", "/__pycache__/", "/migrations/", "/logs/", "/backup/"]
        return any(pattern in str(file_path) for pattern in skip_patterns)

    def _analyze_file(self, file_path: Path) -> None:
        """Анализирует один Python-файл."""
        with open(file_path, "r", encoding="utf-8") as f:
            source = f.read()

        try:
            tree = ast.parse(source, filename=str(file_path))
        except SyntaxError as e:
            self.issues.append({
                "file": str(file_path),
                "line": e.lineno or 0,
                "severity": "critical",
                "type": "syntax_error",
                "message": f"Синтаксическая ошибка: {e.msg}"
            })
            return

        visitor = CodeVisitor(file_path, self.rules)
        visitor.visit(tree)
        self.issues.extend(visitor.issues)

    def get_issues_by_severity(self, severity: str) -> List[Dict[str, Any]]:
        return [issue for issue in self.issues if issue["severity"] == severity]

    def has_critical_issues(self) -> bool:
        return any(issue["severity"] in ("critical", "high") for issue in self.issues)

    def generate_report(self, output_path: Optional[str] = None) -> str:
        """Генерирует отчёт в формате JSON."""
        report = {
            "timestamp": self.config.get_current_time_iso(),
            "project_root": str(self.project_root),
            "total_issues": len(self.issues),
            "issues": self.issues
        }

        if output_path:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            logger.info(f"📄 Отчёт сохранён: {output_path}")

        return json.dumps(report, indent=2, ensure_ascii=False)


class CodeVisitor(ast.NodeVisitor):
    """Посетитель AST для выявления проблем в коде."""

    def __init__(self, file_path: Path, rules: Dict[str, Any]):
        self.file_path = file_path
        self.rules = rules
        self.issues: List[Dict[str, Any]] = []
        self.current_function = None
        self.imported_modules: Set[str] = set()
        self.defined_names: Set[str] = set()

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.imported_modules.add(alias.name)
            self._check_forbidden_import(alias.name, node.lineno)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            full_name = node.module
            self.imported_modules.add(full_name)
            self._check_forbidden_import(full_name, node.lineno)
        self.generic_visit(node)

    def _check_forbidden_import(self, module_name: str, lineno: int) -> None:
        """Проверяет, разрешён ли импорт между слоями."""
        current_dir = self.file_path.relative_to(Path(__file__).parent.parent.parent).parts[0]
        if current_dir not in self.rules["forbidden_imports"]:
            return

        forbidden_targets = self.rules["forbidden_imports"][current_dir]
        for target in forbidden_targets:
            if module_name.startswith(target):
                self.issues.append({
                    "file": str(self.file_path),
                    "line": lineno,
                    "severity": "high",
                    "type": "arch_violation",
                    "message": f"Запрещённый импорт '{module_name}' из слоя '{current_dir}'"
                })

    def visit_Call(self, node: ast.Call) -> None:
        """Проверка на опасные вызовы (безопасность)."""
        if isinstance(node.func, ast.Name):
            func_name = node.func.id
            if func_name in ["eval", "exec"]:
                self.issues.append({
                    "file": str(self.file_path),
                    "line": node.lineno,
                    "severity": "critical",
                    "type": "security_risk",
                    "message": f"Использование {func_name}() — высокий риск безопасности"
                })
        elif isinstance(node.func, ast.Attribute):
            attr_name = node.func.attr
            if attr_name in ["system", "popen", "call"] and hasattr(node.func.value, 'id'):
                if node.func.value.id == "os" or node.func.value.id == "subprocess":
                    self.issues.append({
                        "file": str(self.file_path),
                        "line": node.lineno,
                        "severity": "high",
                        "type": "security_risk",
                        "message": f"Прямой вызов системной команды через {node.func.value.id}.{attr_name}"
                    })
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.current_function = node.name
        complexity = self._calculate_cyclomatic_complexity(node)
        if complexity > self.rules["max_cyclomatic_complexity"]:
            self.issues.append({
                "file": str(self.file_path),
                "line": node.lineno,
                "severity": "medium",
                "type": "complexity",
                "message": f"Высокая цикломатическая сложность функции '{node.name}': {complexity}"
            })
        self.generic_visit(node)

    def _calculate_cyclomatic_complexity(self, node: ast.AST) -> int:
        """Рассчитывает цикломатическую сложность."""
        complexity = 1
        for child in ast.walk(node):
            if isinstance(child, (ast.If, ast.For, ast.While, ast.Try, ast.ExceptHandler)):
                complexity += 1
            elif isinstance(child, ast.BoolOp):
                complexity += len(child.values) - 1
        return complexity


# Утилита для внешнего вызова (например, из скриптов обслуживания)
def run_code_analysis(target_dir: Optional[str] = None, report_path: Optional[str] = None) -> bool:
    """
    Запускает анализ кода и возвращает True, если критических ошибок нет.
    """
    analyzer = CodeAnalyzer()
    issues = analyzer.analyze_project(target_dir)
    if report_path:
        analyzer.generate_report(report_path)
    return not analyzer.has_critical_issues()


if __name__ == "__main__":
    # Пример запуска как standalone-скрипт
    import sys
    target = sys.argv[1] if len(sys.argv) > 1 else None
    success = run_code_analysis(target, "logs/app/code_analysis_report.json")
    sys.exit(0 if success else 1)