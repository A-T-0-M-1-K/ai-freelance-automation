# AI_FREELANCE_AUTOMATION/core/ai_management/model_optimizer.py

"""
Model Optimizer — автоматически улучшает производительность и эффективность AI-моделей
в реальном времени на основе метрик использования, качества и ресурсов.

Функции:
- Анализ производительности модели (latency, accuracy, memory)
- Автоматическая замена модели на более легкую/точную при необходимости
- Квантование, pruning, distillation (если поддерживается)
- Обновление конфигурации в UnifiedConfigManager
- Интеграция с continuous_learning для адаптации под домен

Архитектурные требования:
- Не зависит напрямую от конкретных фреймворков (PyTorch/TensorFlow абстрагированы)
- Работает через service locator или DI
- Поддерживает горячую замену моделей без остановки системы
"""

import logging
import time
from typing import Dict, Any, Optional, Callable
from pathlib import Path

from core.config.unified_config_manager import UnifiedConfigManager
from core.monitoring.intelligent_monitoring_system import IntelligentMonitoringSystem
from core.ai_management.model_registry import ModelRegistry
from core.learning.continuous_learning_system import ContinuousLearningSystem


class ModelOptimizer:
    """
    Оптимизатор AI-моделей. Работает в фоне и периодически анализирует,
    можно ли улучшить модель по скорости, точности или потреблению памяти.
    """

    def __init__(
        self,
        config_manager: UnifiedConfigManager,
        monitoring_system: IntelligentMonitoringSystem,
        model_registry: ModelRegistry,
        learning_system: Optional[ContinuousLearningSystem] = None,
        optimization_interval_seconds: int = 3600  # раз в час
    ):
        self.config = config_manager
        self.monitoring = monitoring_system
        self.registry = model_registry
        self.learning = learning_system
        self.interval = optimization_interval_seconds
        self.logger = logging.getLogger("ModelOptimizer")
        self._running = False
        self._last_optimization: Dict[str, float] = {}

        self.optimization_strategies = {
            "quantize": self._apply_quantization,
            "prune": self._apply_pruning,
            "distill": self._apply_distillation,
            "switch_to_lighter": self._switch_to_lighter_model,
            "fine_tune": self._trigger_fine_tuning,
        }

        self.logger.info("Intialized ModelOptimizer with %d strategies", len(self.optimization_strategies))

    async def start_optimization_loop(self):
        """Запускает фоновый цикл оптимизации."""
        if self._running:
            self.logger.warning("Optimization loop already running")
            return
        self._running = True
        self.logger.info("▶️ Starting model optimization loop (interval: %ds)", self.interval)

        while self._running:
            try:
                await self._run_optimization_cycle()
            except Exception as e:
                self.logger.error("❌ Error in optimization cycle: %s", e, exc_info=True)
                # Не останавливаем цикл — система должна быть отказоустойчивой
            await asyncio.sleep(self.interval)

    def stop(self):
        """Останавливает цикл оптимизации."""
        self._running = False
        self.logger.info("⏹️ Model optimization loop stopped")

    async def _run_optimization_cycle(self):
        """Выполняет один цикл анализа и оптимизации всех активных моделей."""
        self.logger.debug("🔍 Starting optimization cycle...")
        active_models = self.registry.get_active_models()

        for model_id in active_models:
            try:
                await self._optimize_single_model(model_id)
            except Exception as e:
                self.logger.error("💥 Failed to optimize model %s: %s", model_id, e, exc_info=True)

        self.logger.debug("✅ Optimization cycle completed")

    async def _optimize_single_model(self, model_id: str):
        """Оптимизирует одну модель на основе её метрик."""
        # Получаем последние метрики
        metrics = await self.monitoring.get_model_metrics(model_id)
        if not metrics:
            self.logger.debug("No metrics for model %s, skipping", model_id)
            return

        # Проверяем, прошло ли достаточно времени с последней оптимизации
        last_opt = self._last_optimization.get(model_id, 0)
        if time.time() - last_opt < self.interval:
            return

        # Анализируем необходимость оптимизации
        need_optimize = self._should_optimize(metrics)
        if not need_optimize:
            return

        self.logger.info("⚡ Optimization needed for model %s: %s", model_id, need_optimize)

        # Выбираем стратегию
        strategy_name = self._select_optimization_strategy(metrics, need_optimize)
        if strategy_name not in self.optimization_strategies:
            self.logger.warning("Unknown strategy: %s for model %s", strategy_name, model_id)
            return

        strategy = self.optimization_strategies[strategy_name]
        try:
            result = await strategy(model_id, metrics)
            if result:
                self._last_optimization[model_id] = time.time()
                self.logger.info("✅ Successfully applied '%s' to model %s", strategy_name, model_id)
                # Обновляем реестр и конфиг
                self.registry.mark_model_as_optimized(model_id, strategy_name, result)
                await self.config.update_model_config(model_id, result.get("new_config", {}))
        except Exception as e:
            self.logger.error("⚠️ Strategy '%s' failed for model %s: %s", strategy_name, model_id, e)

    def _should_optimize(self, metrics: Dict[str, Any]) -> Optional[str]:
        """
        Возвращает причину оптимизации или None, если не требуется.
        Возможные причины: 'high_latency', 'low_accuracy', 'high_memory', 'low_throughput'
        """
        latency = metrics.get("avg_inference_time_sec", 0)
        accuracy = metrics.get("accuracy", 1.0)
        memory = metrics.get("peak_memory_mb", 0)
        throughput = metrics.get("requests_per_minute", float('inf'))

        threshold = self.config.get("ai.optimization.thresholds", {})

        if latency > threshold.get("max_latency_sec", 5.0):
            return "high_latency"
        if accuracy < threshold.get("min_accuracy", 0.85):
            return "low_accuracy"
        if memory > threshold.get("max_memory_mb", 2048):
            return "high_memory"
        if throughput < threshold.get("min_throughput_rpm", 10):
            return "low_throughput"

        return None

    def _select_optimization_strategy(
        self, metrics: Dict[str, Any], reason: str
    ) -> str:
        """Выбирает стратегию оптимизации на основе причины и контекста."""
        model_type = metrics.get("model_type", "unknown")
        is_local = metrics.get("is_local", True)

        if reason == "high_latency" and is_local:
            return "quantize"
        if reason == "high_memory":
            return "prune"
        if reason == "low_accuracy" and self.learning:
            return "fine_tune"
        if reason in ("high_latency", "high_memory") and is_local:
            return "switch_to_lighter"
        # fallback
        return "quantize"

    async def _apply_quantization(self, model_id: str, metrics: Dict[str, Any]) -> Dict[str, Any]:
        """Применяет квантование (INT8/FP16) к модели."""
        self.logger.info("🔧 Applying quantization to %s", model_id)
        # Здесь будет интеграция с ONNX Runtime, TensorRT, или HuggingFace Optimum
        # Для каркаса — симуляция
        return {
            "strategy": "quantize",
            "new_config": {
                "precision": "int8",
                "expected_speedup": 1.8,
                "expected_memory_reduction": 0.6
            },
            "status": "applied"
        }

    async def _apply_pruning(self, model_id: str, metrics: Dict[str, Any]) -> Dict[str, Any]:
        """Применяет pruning (удаление нейронов/слоёв)."""
        self.logger.info("✂️ Applying pruning to %s", model_id)
        return {
            "strategy": "prune",
            "new_config": {
                "sparsity": 0.3,
                "expected_memory_reduction": 0.4
            },
            "status": "applied"
        }

    async def _apply_distillation(self, model_id: str, metrics: Dict[str, Any]) -> Dict[str, Any]:
        """Запускает knowledge distillation от большой модели к малой."""
        self.logger.info("🎓 Starting distillation for %s", model_id)
        raise NotImplementedError("Distillation requires teacher model — not implemented in base version")

    async def _switch_to_lighter_model(self, model_id: str, metrics: Dict[str, Any]) -> Dict[str, Any]:
        """Переключается на более лёгкую версию модели (например, small вместо medium)."""
        current_name = metrics.get("model_name", "")
        if "medium" in current_name:
            new_name = current_name.replace("medium", "small")
        elif "large" in current_name:
            new_name = current_name.replace("large", "medium")
        else:
            new_name = current_name + "_lite"

        self.logger.info("🔄 Switching %s → %s", current_name, new_name)
        return {
            "strategy": "switch_to_lighter",
            "new_config": {
                "model_name": new_name,
                "auto_loaded": True
            },
            "status": "switched"
        }

    async def _trigger_fine_tuning(self, model_id: str, metrics: Dict[str, Any]) -> Dict[str, Any]:
        """Инициирует дообучение модели на основе фидбэка из ContinuousLearningSystem."""
        if not self.learning:
            raise RuntimeError("Fine-tuning requires ContinuousLearningSystem")

        self.logger.info("🧠 Triggering fine-tuning for %s based on feedback", model_id)
        job_samples = await self.learning.get_recent_feedback_samples(model_id, n=100)
        task = await self.learning.create_finetune_task(model_id, job_samples)

        return {
            "strategy": "fine_tune",
            "new_config": {
                "finetune_task_id": task["id"],
                "status": "queued"
            },
            "status": "fine_tuning_started"
        }