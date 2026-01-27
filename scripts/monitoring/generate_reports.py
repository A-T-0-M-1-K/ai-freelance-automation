# AI_FREELANCE_AUTOMATION/scripts/monitoring/generate_reports.py
"""
Автоматическая генерация отчётов для мониторинга системы и бизнес-показателей.
Поддерживает ежедневные, еженедельные и ежемесячные отчёты.
Интегрируется с шаблонами, системой логирования и конфигурацией.
"""

import os
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional

# Импорты из ядра — через service locator для избежания циклических зависимостей
from core.dependency.service_locator import ServiceLocator
from core.config.unified_config_manager import UnifiedConfigManager
from core.monitoring.intelligent_monitoring_system import IntelligentMonitoringSystem
from core.analytics.predictive_analytics import PredictiveAnalytics

# Пути к шаблонам и данным
TEMPLATES_DIR = Path("templates/report")
EXPORTS_DIR = Path("data/exports/reports")
LOGS_DIR = Path("logs/app")

# Убедимся, что директории существуют
EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# Настройка логгера
logger = logging.getLogger("ReportGenerator")


class ReportGenerator:
    """
    Генератор отчётов на основе собранных метрик и предсказательной аналитики.
    """

    def __init__(self):
        self.config = ServiceLocator.get("config") or UnifiedConfigManager()
        self.monitoring = ServiceLocator.get("monitoring") or IntelligentMonitoringSystem(self.config)
        self.analytics = ServiceLocator.get("analytics") or PredictiveAnalytics(self.config)
        self.report_format = self.config.get("reporting.format", "json")
        self.timezone = self.config.get("system.timezone", "UTC")

    def _load_template(self, report_type: str) -> str:
        """Загружает шаблон отчёта по типу."""
        template_path = TEMPLATES_DIR / f"{report_type}_report_template.md"
        if not template_path.exists():
            logger.warning(f"Шаблон отчёта не найден: {template_path}. Используется резервный формат.")
            return "# Отчёт ({date})\n\n{content}\n"
        try:
            with open(template_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            logger.error(f"Ошибка загрузки шаблона {template_path}: {e}")
            raise

    def _collect_metrics(self, period_start: datetime, period_end: datetime) -> Dict[str, Any]:
        """Собирает метрики за указанный период."""
        metrics = self.monitoring.get_metrics_in_range(period_start, period_end)
        predictions = self.analytics.generate_predictions(period_end)
        return {
            "period": {
                "start": period_start.isoformat(),
                "end": period_end.isoformat()
            },
            "system": metrics.get("system", {}),
            "business": metrics.get("business", {}),
            "ai_performance": metrics.get("ai", {}),
            "predictions": predictions,
            "generated_at": datetime.now().isoformat()
        }

    def _render_report(self, template: str, data: Dict[str, Any]) -> str:
        """Рендерит шаблон с данными."""
        date_str = data["period"]["end"].split("T")[0]
        content_lines = []

        # Системные метрики
        sys = data["system"]
        if sys:
            content_lines.append("## 🖥️ Системные метрики")
            content_lines.append(f"- CPU usage: {sys.get('cpu_avg', 'N/A')}%")
            content_lines.append(f"- Memory usage: {sys.get('memory_avg', 'N/A')} MB")
            content_lines.append(f"- Active jobs: {sys.get('active_jobs', 0)}")
            content_lines.append(f"- Errors: {sys.get('error_count', 0)}")

        # Бизнес-метрики
        biz = data["business"]
        if biz:
            content_lines.append("\n## 💼 Бизнес-показатели")
            content_lines.append(f"- Завершено заказов: {biz.get('completed_jobs', 0)}")
            content_lines.append(f"- Доход: {biz.get('revenue', 0):.2f} USD")
            content_lines.append(f"- Конверсия ставок: {biz.get('bid_conversion_rate', 0):.1f}%")
            content_lines.append(f"- Удовлетворённость клиентов: {biz.get('csat', 'N/A')}")

        # Прогнозы
        pred = data["predictions"]
        if pred:
            content_lines.append("\n## 🔮 Прогнозы")
            content_lines.append(f"- Ожидаемый доход (след. неделя): {pred.get('next_week_revenue', 0):.2f} USD")
            content_lines.append(f"- Риск сбоев: {'Высокий' if pred.get('failure_risk', 0) > 0.7 else 'Низкий'}")

        content = "\n".join(content_lines)
        return template.format(date=date_str, content=content)

    def generate_report(
        self,
        report_type: str,
        output_path: Optional[Path] = None
    ) -> Path:
        """
        Генерирует отчёт указанного типа.
        Поддерживаемые типы: 'daily', 'weekly', 'monthly'
        """
        now = datetime.now()
        if report_type == "daily":
            period_end = now.replace(hour=0, minute=0, second=0, microsecond=0)
            period_start = period_end - timedelta(days=1)
            filename = f"daily_report_{period_end.strftime('%Y-%m-%d')}"
        elif report_type == "weekly":
            period_end = now - timedelta(days=now.weekday())  # Понедельник текущей недели
            period_start = period_end - timedelta(weeks=1)
            filename = f"weekly_report_{period_end.strftime('%Y-%W')}"
        elif report_type == "monthly":
            period_end = now.replace(day=1)
            if period_end.month == 1:
                period_start = period_end.replace(year=period_end.year - 1, month=12)
            else:
                period_start = period_end.replace(month=period_end.month - 1)
            filename = f"monthly_report_{period_end.strftime('%Y-%m')}"
        else:
            raise ValueError(f"Неизвестный тип отчёта: {report_type}")

        logger.info(f"Генерация {report_type} отчёта за период: {period_start} – {period_end}")

        # Сбор данных
        data = self._collect_metrics(period_start, period_end)

        # Выбор формата
        if self.report_format == "json":
            output_file = (output_path or EXPORTS_DIR) / f"{filename}.json"
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        else:  # markdown
            template = self._load_template(report_type)
            rendered = self._render_report(template, data)
            output_file = (output_path or EXPORTS_DIR) / f"{filename}.md"
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(rendered)

        logger.info(f"✅ Отчёт сохранён: {output_file}")
        return output_file

    def generate_all_scheduled_reports(self) -> List[Path]:
        """Генерирует все запланированные отчёты согласно конфигурации."""
        enabled_reports = self.config.get("reporting.enabled_reports", ["daily"])
        paths = []
        for rpt_type in enabled_reports:
            try:
                path = self.generate_report(rpt_type)
                paths.append(path)
            except Exception as e:
                logger.error(f"Не удалось сгенерировать отчёт '{rpt_type}': {e}", exc_info=True)
        return paths


def main():
    """Точка входа для CLI или cron."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(LOGS_DIR / "report_generation.log"),
            logging.StreamHandler()
        ]
    )

    try:
        generator = ReportGenerator()
        generated = generator.generate_all_scheduled_reports()
        logger.info(f"Сгенерировано отчётов: {len(generated)}")
    except Exception as e:
        logger.critical(f"Критическая ошибка при генерации отчётов: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    main()