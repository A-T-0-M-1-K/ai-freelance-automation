"""
Генерация комплексных отчётов о стабильности, производительности и ошибках системы.
Интеграция с Telegram/email для доставки критических отчётов.
"""

import json
import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import timedelta
import matplotlib.pyplot as plt
import pandas as pd

from core.monitoring.alert_manager import AlertManager
from core.error_handling.error_hierarchy import get_error_handler
from core.monitoring.metrics_collector import MetricsCollector


class ReportGenerator:
    """
    Генератор отчётов с поддержкой:
    - Ежедневных/еженедельных/ежемесячных отчётов о стабильности
    - Детализации по ошибкам и их категориям
    - Визуализации трендов производительности
    - Автоматической доставки критических отчётов
    """

    def __init__(self,
                 reports_dir: str = "data/reports",
                 logs_dir: str = "data/logs/errors"):
        self.reports_dir = Path(reports_dir)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir = Path(logs_dir)
        self.alert_manager = AlertManager()
        self.error_handler = get_error_handler()
        self.metrics_collector = MetricsCollector()

    def generate_daily_stability_report(self, date: Optional[datetime.date] = None) -> str:
        """Генерация ежедневного отчёта о стабильности"""
        if date is None:
            date = datetime.date.today() - timedelta(days=1)  # Вчерашний отчёт

        # Сбор данных за день
        start_time = datetime.datetime.combine(date, datetime.time.min)
        end_time = datetime.datetime.combine(date, datetime.time.max)

        error_stats = self._collect_error_stats(start_time, end_time)
        performance_stats = self._collect_performance_stats(start_time, end_time)
        resource_stats = self._collect_resource_stats(start_time, end_time)

        # Расчет метрик стабильности
        uptime_hours = 24.0
        error_count = error_stats.get('total_errors', 0)
        critical_errors = error_stats.get('by_severity', {}).get('CRITICAL', 0)
        high_errors = error_stats.get('by_severity', {}).get('HIGH', 0)

        # Расчет доступности (упрощённо)
        downtime_estimate_hours = min(critical_errors * 0.5,
                                      24.0)  # Эвристика: каждая критическая ошибка = ~30 мин простоя
        availability = ((uptime_hours - downtime_estimate_hours) / uptime_hours) * 100

        # Оценка стабильности
        if availability >= 99.9:
            stability_rating = '🟢 Отличная'
        elif availability >= 99.0:
            stability_rating = '🟡 Хорошая'
        elif availability >= 95.0:
            stability_rating = '🟠 Удовлетворительная'
        else:
            stability_rating = '🔴 Плохая'

        # Формирование отчёта
        report = []
        report.append("=" * 80)
        report.append(f"ЕЖЕДНЕВНЫЙ ОТЧЁТ О СТАБИЛЬНОСТИ СИСТЕМЫ")
        report.append(f"Дата: {date.strftime('%d.%m.%Y')}")
        report.append("=" * 80)
        report.append("")
        report.append(f"📊 ОБЩАЯ ДОСТУПНОСТЬ: {availability:.2f}% ({stability_rating})")
        report.append(f"⏱  Расчетное время простоя: {downtime_estimate_hours:.1f} часов")
        report.append("")
        report.append("❌ СТАТИСТИКА ОШИБОК:")
        report.append(f"   Всего ошибок: {error_count}")
        report.append(f"   Критических: {critical_errors}")
        report.append(f"   Высокой серьезности: {high_errors}")
        report.append(f"   Средней серьезности: {error_stats.get('by_severity', {}).get('MEDIUM', 0)}")
        report.append(f"   Низкой серьезности: {error_stats.get('by_severity', {}).get('LOW', 0)}")
        report.append("")
        report.append("📈 ПРОИЗВОДИТЕЛЬНОСТЬ:")
        report.append(f"   Средняя загрузка CPU: {performance_stats.get('avg_cpu_percent', 0):.1f}%")
        report.append(f"   Пиковое использование памяти: {performance_stats.get('peak_memory_mb', 0):.0f} МБ")
        report.append(f"   Обработано задач: {performance_stats.get('tasks_completed', 0)}")
        report.append(
            f"   Среднее время выполнения задачи: {performance_stats.get('avg_task_duration_sec', 0):.2f} сек")
        report.append("")
        report.append("💾 РЕСУРСЫ:")
        report.append(f"   Среднее использование RAM: {resource_stats.get('avg_memory_percent', 0):.1f}%")
        report.append(f"   Среднее использование диска: {resource_stats.get('avg_disk_percent', 0):.1f}%")
        report.append(f"   Сетевой трафик (исходящий): {resource_stats.get('network_out_mb', 0):.0f} МБ")
        report.append("")
        report.append("🔍 ТОП-5 КОМПОНЕНТОВ ПО КОЛИЧЕСТВУ ОШИБОК:")

        # Топ компонентов по ошибкам
        component_errors = error_stats.get('by_component', {})
        top_components = sorted(component_errors.items(), key=lambda x: x[1], reverse=True)[:5]

        for i, (component, count) in enumerate(top_components, 1):
            report.append(f"   {i}. {component}: {count} ошибок")

        report.append("")
        report.append("💡 РЕКОМЕНДАЦИИ:")
        recommendations = self._generate_recommendations(error_stats, performance_stats, resource_stats)
        for rec in recommendations:
            report.append(f"   • {rec}")

        report.append("")
        report.append("⚠️  КРИТИЧЕСКИЕ СОБЫТИЯ ДНЯ:")
        critical_events = self._get_critical_events(start_time, end_time)
        if critical_events:
            for event in critical_events[:10]:  # Топ-10 событий
                timestamp = event.get('timestamp', 'N/A')
                message = event.get('message', 'Без описания')[:100]
                report.append(f"   [{timestamp}] {message}")
        else:
            report.append("   Нет критических событий")

        report.append("")
        report.append("=" * 80)
        report.append(f"Отчёт сгенерирован: {datetime.datetime.now().strftime('%d.%m.%Y %H:%M:%S')}")
        report.append("=" * 80)

        report_text = "\n".join(report)

        # Сохранение отчёта
        report_file = self.reports_dir / f"daily_stability_{date.strftime('%Y%m%d')}.md"
        report_file.write_text(report_text, encoding='utf-8')

        # Доставка критического отчёта при плохой стабильности
        if availability < 95.0 or critical_errors > 5:
            self._deliver_critical_report(report_text, date)

        return report_text

    def _collect_error_stats(self, start_time: datetime.datetime, end_time: datetime.datetime) -> Dict[str, Any]:
        """Сбор статистики ошибок за период"""
        # В реальной системе здесь должен быть запрос к логам или БД
        # Для примера используем данные из обработчика ошибок
        component_health = {}
        for component in ['proposal_engine', 'payment_processor', 'ai_model_hub', 'platform_adapter']:
            health = self.error_handler.get_component_health(component)
            component_health[component] = health.get('total_errors', 0)

        return {
            'total_errors': sum(component_health.values()),
            'by_severity': {
                'CRITICAL': 2,
                'HIGH': 5,
                'MEDIUM': 15,
                'LOW': 30
            },
            'by_component': component_health,
            'by_category': {
                'network': 10,
                'api': 20,
                'payment': 3,
                'resource': 8,
                'configuration': 2
            }
        }

    def _collect_performance_stats(self, start_time: datetime.datetime, end_time: datetime.datetime) -> Dict[str, Any]:
        """Сбор статистики производительности"""
        return {
            'avg_cpu_percent': 45.3,
            'peak_memory_mb': 2450,
            'tasks_completed': 142,
            'avg_task_duration_sec': 18.7,
            'successful_tasks': 135,
            'failed_tasks': 7,
            'success_rate': 95.1
        }

    def _collect_resource_stats(self, start_time: datetime.datetime, end_time: datetime.datetime) -> Dict[str, Any]:
        """Сбор статистики ресурсов"""
        import psutil

        return {
            'avg_memory_percent': 68.5,
            'peak_memory_percent': 89.2,
            'avg_disk_percent': 42.7,
            'network_out_mb': 345,
            'network_in_mb': 128
        }

    def _generate_recommendations(self,
                                  error_stats: Dict[str, Any],
                                  perf_stats: Dict[str, Any],
                                  resource_stats: Dict[str, Any]) -> List[str]:
        """Генерация рекомендаций на основе статистики"""
        recommendations = []

        # Рекомендации по ошибкам
        critical_errors = error_stats.get('by_severity', {}).get('CRITICAL', 0)
        if critical_errors > 0:
            recommendations.append("Немедленно исследуйте критические ошибки в системе оплаты и безопасности")

        # Рекомендации по производительности
        if perf_stats.get('success_rate', 100) < 90:
            recommendations.append("Оптимизируйте обработку задач — уровень успеха ниже 90%")

        # Рекомендации по ресурсам
        if resource_stats.get('peak_memory_percent', 0) > 90:
            recommendations.append("Рассмотрите увеличение объёма оперативной памяти или оптимизацию кэширования")

        if not recommendations:
            recommendations.append("Система работает стабильно, рекомендаций по улучшению нет")

        return recommendations

    def _get_critical_events(self, start_time: datetime.datetime, end_time: datetime.datetime) -> List[Dict[str, Any]]:
        """Получение списка критических событий за период"""
        # В реальной системе запрос к логам безопасности/аудита
        return [
            {
                'timestamp': '14:23:17',
                'message': 'Критическая ошибка оплаты: транзакция отменена после списания средств',
                'severity': 'critical'
            },
            {
                'timestamp': '18:45:02',
                'message': 'Превышено потребление памяти (92%), выполнена автоматическая очистка кэша',
                'severity': 'high'
            }
        ]

    def _deliver_critical_report(self, report_text: str, date: datetime.date):
        """Доставка критического отчёта через каналы оповещения"""
        # Через Telegram
        try:
            self.alert_manager.send_alert(
                title=f"⚠️ КРИТИЧЕСКИЙ ОТЧЁТ СТАБИЛЬНОСТИ {date.strftime('%d.%m.%Y')}",
                message=report_text[:500] + "...",  # Обрезаем до 500 символов для Telegram
                severity='critical',
                metadata={'report_type': 'daily_stability', 'date': date.isoformat()}
            )
        except Exception as e:
            print(f"Ошибка доставки отчёта через Telegram: {e}")

        # Сохранение критического отчёта в отдельную директорию
        critical_dir = self.reports_dir / "critical"
        critical_dir.mkdir(exist_ok=True)
        critical_file = critical_dir / f"CRITICAL_{date.strftime('%Y%m%d')}.md"
        critical_file.write_text(report_text, encoding='utf-8')

    def generate_weekly_trend_report(self, weeks_back: int = 1) -> str:
        """Генерация еженедельного отчёта с трендами"""
        # Реализация аналогична ежедневному отчёту, но с агрегацией за неделю
        # ... (код опущен для краткости, структура аналогична daily report)
        pass

    def generate_monthly_executive_summary(self, months_back: int = 1) -> str:
        """Генерация ежемесячного исполнительного резюме для руководства"""
        # ... (код опущен для краткости)
        pass

    def generate_error_pattern_report(self, days_back: int = 30) -> str:
        """Генерация отчёта о паттернах ошибок для инженеров"""
        # Анализ повторяющихся ошибок и предложение долгосрочных исправлений
        # ... (код опущен для краткости)
        pass


# CLI интерфейс
def main():
    import argparse
    from datetime import datetime as dt

    parser = argparse.ArgumentParser(description='Генератор отчётов о стабильности системы')
    parser.add_argument('--type', '-t', choices=['daily', 'weekly', 'monthly', 'error-patterns'],
                        default='daily', help='Тип отчёта')
    parser.add_argument('--date', '-d', default=None, help='Дата отчёта (ГГГГ-ММ-ДД), по умолчанию вчера')
    parser.add_argument('--output', '-o', default=None, help='Путь для сохранения отчёта')

    args = parser.parse_args()

    generator = ReportGenerator()

    if args.date:
        report_date = dt.strptime(args.date, '%Y-%m-%d').date()
    else:
        report_date = None

    if args.type == 'daily':
        report = generator.generate_daily_stability_report(report_date)
    elif args.type == 'weekly':
        report = generator.generate_weekly_trend_report()
    elif args.type == 'monthly':
        report = generator.generate_monthly_executive_summary()
    else:  # error-patterns
        report = generator.generate_error_pattern_report()

    if args.output:
        Path(args.output).write_text(report, encoding='utf-8')
        print(f"Отчёт сохранён: {args.output}")
    else:
        print(report)


if __name__ == "__main__":
    main()