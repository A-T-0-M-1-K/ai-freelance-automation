# AI_FREELANCE_AUTOMATION/tools/code_analysis/complexity_check.py
"""
Цикломатический анализатор кода (McCabe Complexity Checker).
Используется для оценки сложности функций и методов в кодовой базе.
Поддерживает рекурсивный обход директорий и генерацию отчетов.
Интегрируется с системой логирования и мониторинга.
"""

import ast
import os
import logging
from pathlib import Path
from typing import Dict, List, Tuple, Optional

# Используем глобальный логгер системы
logger = logging.getLogger("CodeAnalysis.ComplexityCheck")


class ComplexityNodeVisitor(ast.NodeVisitor):
    """
    Посетитель AST-дерева для подсчёта цикломатической сложности.
    Сложность увеличивается за каждую точку ветвления:
        - if, elif, else
        - for, while, except
        - and, or (в условиях)
        - case (в match-case, Python 3.10+)
    """

    def __init__(self):
        self.complexity = 1  # Базовая сложность функции = 1
        self._in_condition = False

    def visit_If(self, node: ast.If) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_While(self, node: ast.While) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_Try(self, node: ast.Try) -> None:
        # Каждый except — отдельная ветка
        self.complexity += len(node.handlers)
        self.generic_visit(node)

    def visit_BoolOp(self, node: ast.BoolOp) -> None:
        if isinstance(node.op, (ast.And, ast.Or)):
            # n операндов → n-1 ветвлений
            self.complexity += len(node.values) - 1
        self.generic_visit(node)

    def visit_Match(self, node: ast.Match) -> None:
        # Python 3.10+: каждый case — ветвление
        self.complexity += len(node.cases)
        self.generic_visit(node)

    # Асинхронные конструкции
    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self.complexity += 1
        self.generic_visit(node)


def calculate_complexity_for_function(func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    """Вычисляет цикломатическую сложность одной функции."""
    visitor = ComplexityNodeVisitor()
    visitor.visit(func_node)
    return visitor.complexity


def analyze_file(file_path: Path) -> Dict[str, int]:
    """
    Анализирует один Python-файл и возвращает словарь:
    { "func_name": complexity, ... }
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=str(file_path))
    except SyntaxError as e:
        logger.warning(f"⚠️  Syntax error in {file_path}: {e}")
        return {}
    except Exception as e:
        logger.error(f"💥 Failed to parse {file_path}: {e}")
        return {}

    results: Dict[str, int] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Учитываем вложенные функции через полный путь (например: outer.inner)
            name = node.name
            parent = getattr(node, "parent", None)
            full_name = name
            while parent and hasattr(parent, "name"):
                full_name = f"{parent.name}.{full_name}"
                parent = getattr(parent, "parent", None)
            complexity = calculate_complexity_for_function(node)
            results[full_name] = complexity

    return results


def analyze_directory(
    root_dir: Path,
    exclude_dirs: Optional[List[str]] = None,
    max_complexity: int = 10
) -> Dict[Path, Dict[str, int]]:
    """
    Рекурсивно анализирует все .py файлы в директории.
    Возвращает карту: { file_path: { func_name: complexity } }

    Параметры:
        root_dir: корневая директория анализа
        exclude_dirs: список имен папок для пропуска (например: ['venv', '__pycache__'])
        max_complexity: порог для предупреждений (логирование)
    """
    if exclude_dirs is None:
        exclude_dirs = ["venv", ".venv", "__pycache__", "node_modules", ".git"]

    all_results: Dict[Path, Dict[str, int]] = {}

    for py_file in root_dir.rglob("*.py"):
        if any(part in exclude_dirs for part in py_file.parts):
            continue

        logger.debug(f"🔍 Analyzing {py_file}")
        file_results = analyze_file(py_file)
        if file_results:
            all_results[py_file] = file_results

            # Логируем функции с высокой сложностью
            for func_name, complexity in file_results.items():
                if complexity > max_complexity:
                    logger.warning(
                        f"⚠️ High complexity in {py_file}:{func_name} = {complexity} "
                        f"(threshold: {max_complexity})"
                    )

    return all_results


def generate_complexity_report(
    results: Dict[Path, Dict[str, int]],
    output_path: Optional[Path] = None
) -> str:
    """
    Генерирует читаемый отчёт о сложности.
    Если указан output_path — сохраняет в файл.
    Возвращает строку отчёта.
    """
    report_lines = ["# Code Complexity Report\n"]
    total_funcs = 0
    high_complexity_count = 0

    for file_path, funcs in results.items():
        if not funcs:
            continue
        report_lines.append(f"\n## {file_path.relative_to(Path.cwd())}\n")
        for func, comp in sorted(funcs.items(), key=lambda x: -x[1]):
            total_funcs += 1
            if comp > 10:
                high_complexity_count += 1
            report_lines.append(f"- `{func}`: **{comp}**")

    summary = (
        f"\n---\n"
        f"**Total functions analyzed**: {total_funcs}\n"
        f"**Functions exceeding threshold (10)**: {high_complexity_count}\n"
    )
    report_lines.append(summary)

    full_report = "\n".join(report_lines)

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(full_report)
        logger.info(f"✅ Complexity report saved to {output_path}")

    return full_report


if __name__ == "__main__":
    # Пример использования как standalone-скрипта
    import sys

    logging.basicConfig(level=logging.INFO)

    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    output = Path("reports/complexity_report.md")

    if not target.exists():
        logger.error(f"❌ Path does not exist: {target}")
        sys.exit(1)

    if target.is_file() and target.suffix == ".py":
        results = {target: analyze_file(target)}
    elif target.is_dir():
        results = analyze_directory(target)
    else:
        logger.error("❌ Please provide a .py file or directory")
        sys.exit(1)

    generate_complexity_report(results, output)