# AI_FREELANCE_AUTOMATION/tools/testing/coverage_check.py
"""
Coverage Check Tool — Анализирует покрытие кода тестами.
Интегрируется с системой мониторинга и CI/CD.
Поддерживает настройку через unified config, логирование и безопасность.
"""

import os
import sys
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import dataclass

# Добавляем корень проекта в PYTHONPATH для корректного импорта core-модулей
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

from core.config.unified_config_manager import UnifiedConfigManager
from core.security.audit_logger import AuditLogger
from core.monitoring.intelligent_monitoring_system import IntelligentMonitoringSystem


@dataclass
class CoverageThresholds:
    """Пороговые значения покрытия по категориям."""
    critical: float  # Ядро, безопасность, платежи
    high: float      # Автоматизация, AI, коммуникация
    medium: float    # Сервисы, UI, плагины
    low: float       # Вспомогательные модули


class CoverageChecker:
    """
    Инструмент анализа покрытия кода тестами.
    Использует coverage.py под капотом, но интегрирован в экосистему проекта.
    """

    def __init__(self, config_manager: Optional[UnifiedConfigManager] = None):
        self.logger = logging.getLogger("CoverageChecker")
        self.config_manager = config_manager or UnifiedConfigManager()
        self.audit_logger = AuditLogger()
        self.monitoring = IntelligentMonitoringSystem(self.config_manager)

        # Загрузка порогов из конфига или дефолты
        coverage_config = self.config_manager.get_section("testing.coverage", {})
        self.thresholds = CoverageThresholds(
            critical=coverage_config.get("critical_threshold", 95.0),
            high=coverage_config.get("high_threshold", 85.0),
            medium=coverage_config.get("medium_threshold", 75.0),
            low=coverage_config.get("low_threshold", 60.0)
        )

        self.source_root = PROJECT_ROOT
        self.report_dir = PROJECT_ROOT / "reports" / "coverage"
        self.report_dir.mkdir(parents=True, exist_ok=True)

        self.logger.info("✅ CoverageChecker initialized with thresholds: "
                         f"critical={self.thresholds.critical}%, "
                         f"high={self.thresholds.high}%, "
                         f"medium={self.thresholds.medium}%, "
                         f"low={self.thresholds.low}%")

    def _classify_module(self, file_path: Path) -> str:
        """Классифицирует модуль по критичности на основе пути."""
        rel_path = file_path.relative_to(self.source_root).as_posix()

        if any(seg in rel_path for seg in ["core/security", "core/payment", "core/automation"]):
            return "critical"
        elif any(seg in rel_path for seg in ["ai/", "core/ai_management", "core/communication"]):
            return "high"
        elif any(seg in rel_path for seg in ["services/", "ui/", "plugins/"]):
            return "medium"
        else:
            return "low"

    def _get_expected_threshold(self, file_path: Path) -> float:
        """Возвращает ожидаемый порог покрытия для файла."""
        category = self._classify_module(file_path)
        return getattr(self.thresholds, category)

    def run_coverage_analysis(self, fail_on_low_coverage: bool = True) -> Dict[str, Any]:
        """
        Запускает анализ покрытия и возвращает отчет.
        Интегрируется с системой мониторинга и аудита.
        """
        try:
            import coverage
        except ImportError as e:
            self.logger.error("❌ coverage package not installed. Install with: pip install coverage")
            raise RuntimeError("Missing dependency: coverage") from e

        self.logger.info("🔍 Starting coverage analysis...")

        # Инициализация coverage
        cov = coverage.Coverage(
            source=[str(self.source_root)],
            include=[str(self.source_root / "**/*.py")],
            omit=[
                "*/tests/*",
                "*/venv/*",
                "*/.venv/*",
                "*/env/*",
                "*/__pycache__/*",
                "*/migrations/*",
                "*/logs/*",
                "*/backup/*",
                "*/data/*",
                "*/ai/models/*",
                "*/ai/temp/*",
                "*/docker/*",
                "*/scripts/*",
                "*/tools/*",  # исключаем сами инструменты, чтобы не было рекурсии
                "coverage_check.py",  # исключаем себя
            ]
        )

        cov.start()

        # Запуск тестов через pytest (в отдельном процессе, чтобы coverage захватил всё)
        import subprocess
        test_result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/", "--tb=short"],
            cwd=self.source_root,
            capture_output=True,
            text=True
        )

        if test_result.returncode != 0:
            self.logger.warning("⚠️ Some tests failed, but proceeding with coverage analysis.")

        cov.stop()
        cov.save()

        # Генерация отчетов
        total_coverage = cov.report(show_missing=False, skip_covered=False, ignore_errors=True)
        cov.html_report(directory=str(self.report_dir / "html"))
        cov.xml_report(outfile=str(self.report_dir / "coverage.xml"))

        # Анализ по файлам
        analysis = cov.analysis2()
        file_coverage = {}
        violations = []

        for file_path_str, _, _, missing_lines, _ in zip(*analysis):
            file_path = Path(file_path_str)
            if not file_path.exists():
                continue

            total_lines = len([line for line in open(file_path, 'r', encoding='utf-8', errors='ignore') if line.strip() and not line.strip().startswith('#')])
            executed_lines = total_lines - len(missing_lines)
            coverage_percent = (executed_lines / total_lines * 100) if total_lines > 0 else 100.0

            threshold = self._get_expected_threshold(file_path)
            file_coverage[str(file_path.relative_to(self.source_root))] = {
                "coverage": round(coverage_percent, 2),
                "threshold": threshold,
                "category": self._classify_module(file_path),
                "missing_lines": missing_lines
            }

            if coverage_percent < threshold:
                violations.append({
                    "file": str(file_path.relative_to(self.source_root)),
                    "coverage": round(coverage_percent, 2),
                    "threshold": threshold,
                    "category": self._classify_module(file_path)
                })

        report = {
            "total_coverage": round(total_coverage, 2),
            "thresholds": {
                "critical": self.thresholds.critical,
                "high": self.thresholds.high,
                "medium": self.thresholds.medium,
                "low": self.thresholds.low
            },
            "file_coverage": file_coverage,
            "violations": violations,
            "report_path": {
                "html": str(self.report_dir / "html/index.html"),
                "xml": str(self.report_dir / "coverage.xml")
            }
        }

        # Логирование и мониторинг
        self.audit_logger.log_security_event(
            event_type="COVERAGE_ANALYSIS_COMPLETED",
            details={"total_coverage": report["total_coverage"], "violations_count": len(violations)}
        )

        self.monitoring.record_metric("test.coverage.total", report["total_coverage"])
        self.monitoring.record_metric("test.coverage.violations", len(violations))

        if violations:
            self.logger.warning(f"⚠️ {len(violations)} files below coverage threshold!")
            for v in violations[:5]:  # первые 5
                self.logger.warning(f"   {v['file']}: {v['coverage']}% < {v['threshold']}% ({v['category']})")
        else:
            self.logger.info("✅ All modules meet coverage requirements!")

        # Проверка на провал
        if fail_on_low_coverage and violations:
            self.logger.error("❌ Coverage check FAILED due to threshold violations.")
            raise AssertionError(f"Coverage below threshold in {len(violations)} files. See report.")

        return report

    def generate_badge(self) -> str:
        """Генерирует SVG-бейдж для README (упрощённо через JSON)."""
        # В реальности можно использовать shields.io API или генерировать SVG
        # Здесь — просто метаданные
        badge_data = {
            "schemaVersion": 1,
            "label": "coverage",
            "message": f"{self.run_coverage_analysis(fail_on_low_coverage=False)['total_coverage']}%",
            "color": "brightgreen" if self.run_coverage_analysis(fail_on_low_coverage=False)['total_coverage'] >= 85 else "orange"
        }
        (self.report_dir / "badge.json").write_text(json.dumps(badge_data, indent=2))
        return str(self.report_dir / "badge.json")


if __name__ == "__main__":
    # CLI-интерфейс для запуска вручную
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
    checker = CoverageChecker()
    try:
        report = checker.run_coverage_analysis(fail_on_low_coverage=True)
        print(f"\n📊 Total Coverage: {report['total_coverage']}%")
        print(f"📄 Report: {report['report_path']['html']}")
    except AssertionError as e:
        print(f"\n💥 {e}")
        sys.exit(1)
    except Exception as e:
        logging.getLogger("CoverageCheckCLI").error(f"Unexpected error: {e}", exc_info=True)
        sys.exit(2)