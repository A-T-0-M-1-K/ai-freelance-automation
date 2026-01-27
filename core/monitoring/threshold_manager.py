# AI_FREELANCE_AUTOMATION/core/monitoring/threshold_manager.py
"""
Threshold Manager — динамическое управление пороговыми значениями метрик системы.
Автоматически адаптирует пороги на основе исторических данных, нагрузки и SLA.
Интегрируется с anomaly_detection.py и alert_manager.py.
"""

import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional, Union
from threading import Lock
import time

from core.config.unified_config_manager import UnifiedConfigManager
from core.monitoring.metrics_collector import MetricsCollector


class ThresholdManager:
    """
    Управляет пороговыми значениями для метрик мониторинга.
    Поддерживает:
      - статические пороги из конфигурации
      - динамические пороги (на основе скользящего среднего + std)
      - адаптацию под пиковую/ночную нагрузку
      - сохранение состояния между перезапусками
    """

    def __init__(self, config_manager: UnifiedConfigManager, metrics_collector: Optional[MetricsCollector] = None):
        self.logger = logging.getLogger("ThresholdManager")
        self.config_manager = config_manager
        self.metrics_collector = metrics_collector
        self._lock = Lock()

        # Загрузка конфигурации мониторинга
        self.monitoring_config = self.config_manager.get_section("monitoring")
        self.thresholds_file = Path(self.monitoring_config.get("thresholds_state_path", "data/monitoring/thresholds.json"))
        self.thresholds_file.parent.mkdir(parents=True, exist_ok=True)

        # Внутреннее состояние порогов: {metric_name: {"static": float, "dynamic": float, "mode": "static"|"dynamic"}}
        self._thresholds: Dict[str, Dict[str, Union[float, str]]] = {}
        self._last_update: Dict[str, float] = {}

        self._load_thresholds()
        self.logger.info("✅ ThresholdManager initialized.")

    def _load_thresholds(self) -> None:
        """Загружает сохранённые пороги или инициализирует по умолчанию."""
        default_thresholds = {
            "cpu_usage_percent": {"static": 90.0, "dynamic": 85.0, "mode": "dynamic"},
            "memory_usage_percent": {"static": 95.0, "dynamic": 90.0, "mode": "dynamic"},
            "disk_usage_percent": {"static": 90.0, "dynamic": 85.0, "mode": "static"},
            "network_latency_ms": {"static": 500.0, "dynamic": 300.0, "mode": "dynamic"},
            "job_queue_length": {"static": 100, "dynamic": 50, "mode": "dynamic"},
            "ai_inference_time_sec": {"static": 30.0, "dynamic": 20.0, "mode": "dynamic"},
            "error_rate_percent": {"static": 5.0, "dynamic": 2.0, "mode": "dynamic"},
        }

        if self.thresholds_file.exists():
            try:
                with open(self.thresholds_file, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    # Валидация структуры
                    for key, val in loaded.items():
                        if not isinstance(val, dict) or not all(k in val for k in ("static", "dynamic", "mode")):
                            raise ValueError(f"Invalid threshold structure for {key}")
                    self._thresholds = loaded
                    self.logger.info(f"Loaded thresholds from {self.thresholds_file}")
            except Exception as e:
                self.logger.warning(f"Failed to load thresholds, using defaults: {e}")
                self._thresholds = default_thresholds
        else:
            self._thresholds = default_thresholds
            self._save_thresholds()

    def _save_thresholds(self) -> None:
        """Сохраняет текущие пороги на диск."""
        try:
            with open(self.thresholds_file, "w", encoding="utf-8") as f:
                json.dump(self._thresholds, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.logger.error(f"Failed to save thresholds: {e}")

    def get_threshold(self, metric_name: str) -> Optional[float]:
        """
        Возвращает актуальный порог для метрики.
        Если метрика неизвестна — возвращает None.
        """
        if metric_name not in self._thresholds:
            self.logger.warning(f"Unknown metric '{metric_name}', no threshold defined.")
            return None

        mode = self._thresholds[metric_name]["mode"]
        if mode == "static":
            return self._thresholds[metric_name]["static"]
        elif mode == "dynamic":
            return self._calculate_dynamic_threshold(metric_name)
        else:
            self.logger.error(f"Invalid mode '{mode}' for metric '{metric_name}'")
            return self._thresholds[metric_name]["static"]

    def _calculate_dynamic_threshold(self, metric_name: str) -> float:
        """
        Рассчитывает динамический порог на основе исторических данных.
        Использует скользящее среднее + 2*std за последние N минут.
        """
        if not self.metrics_collector:
            # Без коллектора — fallback на static
            return self._thresholds[metric_name]["static"]

        window_minutes = self.monitoring_config.get("dynamic_threshold_window_minutes", 15)
        history = self.metrics_collector.get_metric_history(
            metric_name, duration_minutes=window_minutes
        )

        if not history:
            return self._thresholds[metric_name]["static"]

        values = [m["value"] for m in history]
        avg = sum(values) / len(values)
        std = (sum((x - avg) ** 2 for x in values) / len(values)) ** 0.5
        dynamic = avg + 2 * std

        # Ограничиваем разумными пределами
        static_val = self._thresholds[metric_name]["static"]
        min_val = static_val * 0.5
        max_val = static_val * 1.5
        dynamic = max(min_val, min(dynamic, max_val))

        # Обновляем кэш динамического порога (опционально для отладки)
        self._thresholds[metric_name]["dynamic"] = dynamic
        self._last_update[metric_name] = time.time()

        return dynamic

    def set_mode(self, metric_name: str, mode: str) -> bool:
        """Переключает режим порога (static/dynamic)."""
        if metric_name not in self._thresholds:
            return False
        if mode not in ("static", "dynamic"):
            return False
        with self._lock:
            self._thresholds[metric_name]["mode"] = mode
            self._save_thresholds()
        self.logger.info(f"Threshold mode for '{metric_name}' set to '{mode}'")
        return True

    def update_static_threshold(self, metric_name: str, value: float) -> bool:
        """Обновляет статический порог."""
        if metric_name not in self._thresholds:
            return False
        if not isinstance(value, (int, float)) or value <= 0:
            return False
        with self._lock:
            self._thresholds[metric_name]["static"] = float(value)
            self._save_thresholds()
        self.logger.info(f"Static threshold for '{metric_name}' updated to {value}")
        return True

    def get_all_thresholds(self) -> Dict[str, Dict[str, Union[float, str]]]:
        """Возвращает копию всех порогов (безопасно для чтения)."""
        with self._lock:
            return self._thresholds.copy()

    def reload_config(self) -> None:
        """Hot-reload конфигурации без перезапуска."""
        old_config = self.monitoring_config
        self.monitoring_config = self.config_manager.get_section("monitoring")
        if old_config != self.monitoring_config:
            self.logger.info("Monitoring config reloaded in ThresholdManager")