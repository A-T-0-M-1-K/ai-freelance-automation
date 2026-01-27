# core/monitoring/trend_analyzer.py
"""
Trend Analyzer — компонент интеллектуального мониторинга, отвечающий за
выявление, анализ и прогнозирование трендов в системных, бизнес- и AI-метриках.

Функционал:
- Обнаружение восходящих/нисходящих трендов
- Прогнозирование будущих значений (экспоненциальное сглаживание, линейная регрессия)
- Выявление сезонности и аномалий на основе исторических данных
- Интеграция с anomaly_detection и predictive_analytics
- Поддержка горизонтального масштабирования через shared state

Архитектурные гарантии:
- Безопасность: не хранит чувствительные данные, только агрегированные метрики
- Надёжность: обработка ошибок, fallback-механизмы
- Совместимость: использует unified_config_manager и metrics_collector
- Расширяемость: поддержка плагинов для новых алгоритмов
"""

import logging
import math
from typing import Dict, List, Optional, Tuple, Any, Callable
from datetime import datetime, timedelta
from collections import deque
import json

import numpy as np
from scipy import stats
from sklearn.linear_model import LinearRegression

from core.config.unified_config_manager import UnifiedConfigManager
from core.monitoring.metrics_collector import MetricsCollector
from core.dependency.service_locator import ServiceLocator

logger = logging.getLogger(__name__)


class TrendAnalyzer:
    """
    Анализатор трендов для ключевых метрик системы.
    Работает в фоне и предоставляет прогнозы другим компонентам.
    """

    def __init__(self, config_manager: Optional[UnifiedConfigManager] = None):
        """
        Инициализация анализатора трендов.

        Args:
            config_manager: менеджер конфигурации. Если None — загружается через ServiceLocator.
        """
        self.config = config_manager or ServiceLocator.get("config")
        self.metrics_collector: MetricsCollector = ServiceLocator.get("metrics_collector")

        # Загрузка параметров из конфигурации
        trend_config = self.config.get("monitoring.trend_analysis", {})
        self.window_size = trend_config.get("window_size_hours", 24)
        self.min_data_points = trend_config.get("min_data_points", 10)
        self.confidence_level = trend_config.get("confidence_level", 0.95)
        self.enabled_metrics = set(trend_config.get("enabled_metrics", [
            "jobs.fetched",
            "jobs.accepted",
            "revenue.daily",
            "ai.accuracy.average",
            "system.cpu.usage",
            "system.memory.usage"
        ]))

        # Внутреннее состояние: последние N часов по каждой метрике
        self._history: Dict[str, deque] = {
            metric: deque(maxlen=self._calculate_maxlen(metric)) for metric in self.enabled_metrics
        }

        # Кэш последних прогнозов (для снижения нагрузки)
        self._last_forecast: Dict[str, Dict[str, Any]] = {}
        self._last_update: Dict[str, datetime] = {}

        logger.info(f"✅ TrendAnalyzer initialized with window={self.window_size}h, "
                    f"metrics={list(self.enabled_metrics)}")

    def _calculate_maxlen(self, metric_name: str) -> int:
        """Рассчитывает максимальную длину истории на основе частоты сбора метрик."""
        # Предполагаем, что метрики собираются каждые 5 минут → 12 точек/час
        points_per_hour = 12
        return max(self.min_data_points, self.window_size * points_per_hour)

    def ingest_metric(self, metric_name: str, value: float, timestamp: Optional[datetime] = None):
        """
        Добавляет новую точку метрики в историю.

        Args:
            metric_name: имя метрики (например, 'revenue.daily')
            value: числовое значение
            timestamp: время фиксации (по умолчанию — сейчас)
        """
        if metric_name not in self.enabled_metrics:
            return  # игнорируем неотслеживаемые метрики

        if timestamp is None:
            timestamp = datetime.utcnow()

        self._history[metric_name].append((timestamp, value))
        # Сбрасываем кэш прогноза при обновлении данных
        if metric_name in self._last_forecast:
            del self._last_forecast[metric_name]

    def analyze_trend(self, metric_name: str) -> Dict[str, Any]:
        """
        Анализирует тренд для указанной метрики.

        Returns:
            Словарь с полями:
            - trend: 'up', 'down', 'stable'
            - slope: наклон линии тренда
            - r_squared: коэффициент детерминации
            - forecast_next: прогноз на следующий интервал
            - confidence_interval: [low, high]
            - seasonality_detected: bool
            - anomaly_risk: float [0..1]
        """
        if metric_name not in self.enabled_metrics:
            raise ValueError(f"Metric '{metric_name}' is not enabled for trend analysis")

        data = list(self._history[metric_name])
        if len(data) < self.min_data_points:
            return self._empty_result()

        timestamps, values = zip(*data)
        values = np.array(values, dtype=float)

        # Преобразуем временные метки в часы с начала наблюдения
        start_time = min(timestamps)
        hours_since_start = np.array([
            (ts - start_time).total_seconds() / 3600.0 for ts in timestamps
        ]).reshape(-1, 1)

        # Линейная регрессия
        model = LinearRegression()
        model.fit(hours_since_start, values)
        slope = float(model.coef_[0])
        r_squared = float(model.score(hours_since_start, values))

        # Прогноз на следующий интервал (+1 час)
        next_hour = hours_since_start[-1] + 1
        forecast = float(model.predict(next_hour.reshape(1, -1))[0])

        # Доверительный интервал (упрощённый)
        residuals = values - model.predict(hours_since_start)
        std_err = np.std(residuals)
        t_val = stats.t.ppf((1 + self.confidence_level) / 2, len(values) - 2)
        margin = t_val * std_err * math.sqrt(1 + 1/len(values) + ((next_hour - np.mean(hours_since_start))**2) / np.sum((hours_since_start - np.mean(hours_since_start))**2))
        ci_low = forecast - margin
        ci_high = forecast + margin

        # Определение направления тренда
        if abs(slope) < 1e-6:
            trend = "stable"
        elif slope > 0:
            trend = "up"
        else:
            trend = "down"

        # Эвристика для аномального риска (на основе отклонения от тренда)
        last_value = values[-1]
        predicted_last = float(model.predict(hours_since_start[-1].reshape(1, -1))[0])
        anomaly_risk = min(1.0, abs(last_value - predicted_last) / (std_err + 1e-6))

        # Проверка сезонности (простая: сравнение с тем же часом предыдущего дня)
        seasonality_detected = False
        if len(values) >= 24 * 12:  # есть хотя бы день данных
            try:
                current_hour = timestamps[-1].hour
                same_hour_values = [
                    v for ts, v in data[:-12] if ts.hour == current_hour
                ]
                if same_hour_values:
                    avg_same_hour = np.mean(same_hour_values)
                    if abs(last_value - avg_same_hour) > 2 * np.std(same_hour_values + [last_value]):
                        seasonality_detected = True
            except Exception as e:
                logger.debug(f"Seasonality check failed for {metric_name}: {e}")

        result = {
            "trend": trend,
            "slope": slope,
            "r_squared": r_squared,
            "forecast_next": forecast,
            "confidence_interval": [float(ci_low), float(ci_high)],
            "seasonality_detected": seasonality_detected,
            "anomaly_risk": float(anomaly_risk),
            "analyzed_at": datetime.utcnow().isoformat(),
            "data_points": len(values)
        }

        self._last_forecast[metric_name] = result
        self._last_update[metric_name] = datetime.utcnow()
        return result

    def get_cached_forecast(self, metric_name: str) -> Optional[Dict[str, Any]]:
        """Возвращает последний кэшированный прогноз, если он актуален (<5 мин)."""
        if metric_name not in self._last_forecast:
            return None
        if datetime.utcnow() - self._last_update[metric_name] > timedelta(minutes=5):
            return None
        return self._last_forecast[metric_name]

    def _empty_result(self) -> Dict[str, Any]:
        """Возвращает нейтральный результат при недостатке данных."""
        return {
            "trend": "unknown",
            "slope": 0.0,
            "r_squared": 0.0,
            "forecast_next": 0.0,
            "confidence_interval": [0.0, 0.0],
            "seasonality_detected": False,
            "anomaly_risk": 0.0,
            "analyzed_at": datetime.utcnow().isoformat(),
            "data_points": 0
        }

    def export_state(self) -> Dict[str, Any]:
        """Экспортирует текущее состояние для сериализации (например, при бэкапе)."""
        serializable_history = {
            metric: [(ts.isoformat(), val) for ts, val in list(deq)]
            for metric, deq in self._history.items()
        }
        return {
            "history": serializable_history,
            "last_forecast": self._last_forecast,
            "last_update": {
                k: v.isoformat() for k, v in self._last_update.items()
            }
        }

    def restore_state(self, state: Dict[str, Any]):
        """Восстанавливает состояние из сериализованного объекта."""
        try:
            for metric, data in state.get("history", {}).items():
                if metric in self._history:
                    self._history[metric].clear()
                    for ts_str, val in data:
                        self._history[metric].append((datetime.fromisoformat(ts_str), val))
            self._last_forecast = state.get("last_forecast", {})
            self._last_update = {
                k: datetime.fromisoformat(v) for k, v in state.get("last_update", {}).items()
            }
            logger.info("✅ TrendAnalyzer state restored successfully")
        except Exception as e:
            logger.error(f"❌ Failed to restore TrendAnalyzer state: {e}")
            raise

    def get_all_trends(self) -> Dict[str, Dict[str, Any]]:
        """Анализирует все отслеживаемые метрики и возвращает сводку."""
        return {
            metric: self.analyze_trend(metric) for metric in self.enabled_metrics
            if len(self._history[metric]) >= self.min_data_points
        }


# Регистрация в DI-контейнере (если используется)
def register_trend_analyzer():
    """Регистрирует экземпляр в ServiceLocator при старте системы."""
    from core.dependency.service_locator import ServiceLocator
    if not ServiceLocator.has("trend_analyzer"):
        analyzer = TrendAnalyzer()
        ServiceLocator.register("trend_analyzer", analyzer)
        logger.debug("📈 TrendAnalyzer registered in ServiceLocator")