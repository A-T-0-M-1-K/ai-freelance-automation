# AI_FREELANCE_AUTOMATION/core/ai_management/intelligent_model_manager.py

"""
Intelligent Model Manager — центральный компонент управления AI-моделями.
Обеспечивает:
- Динамическую загрузку/выгрузку моделей
- Оптимизацию использования памяти
- Мониторинг производительности
- Поддержку гибридных провайдеров (локальные + API)
- Самовосстановление при сбоях
- Совместимость с плагинами AI
"""

import asyncio
import logging
import time
from typing import Dict, Any, Optional, Union, List
from pathlib import Path

from core.config.unified_config_manager import UnifiedConfigManager
from core.performance.intelligent_cache_system import IntelligentCacheSystem
from core.performance.memory_optimizer import MemoryOptimizer
from core.ai_management.model_registry import ModelRegistry
from core.security.advanced_crypto_system import AdvancedCryptoSystem
from core.monitoring.metrics_collector import MetricsCollector

# Типы моделей
ModelType = str  # например: "whisper-medium", "gpt-4-turbo", "nllb-200"
ModelInstance = Any  # абстрактный экземпляр модели


class IntelligentModelManager:
    """
    Управляет всеми AI-моделями в системе.
    Работает как фабрика + пул + монитор.
    """

    def __init__(
        self,
        config: UnifiedConfigManager,
        crypto: AdvancedCryptoSystem,
        cache: Optional[IntelligentCacheSystem] = None,
        memory_optimizer: Optional[MemoryOptimizer] = None,
        metrics_collector: Optional[MetricsCollector] = None
    ):
        self.config = config
        self.crypto = crypto
        self.cache = cache or IntelligentCacheSystem(config)
        self.memory_optimizer = memory_optimizer or MemoryOptimizer(config)
        self.metrics = metrics_collector or MetricsCollector()
        self.logger = logging.getLogger("IntelligentModelManager")

        # Внутренние структуры
        self._loaded_models: Dict[ModelType, ModelInstance] = {}
        self._model_load_times: Dict[ModelType, float] = {}
        self._model_usage_count: Dict[ModelType, int] = {}
        self._model_last_used: Dict[ModelType, float] = {}

        # Регистр моделей (содержит метаданные: источник, тип, требования)
        self.registry = ModelRegistry(config)

        # Флаги состояния
        self._initialized = False
        self._shutdown = False

        self.logger.info("Intialized IntelligentModelManager")

    async def initialize(self) -> None:
        """Инициализация менеджера: предзагрузка критических моделей."""
        if self._initialized:
            return
        self.logger.info("🔄 Initializing AI models...")

        # Загружаем модели, помеченные как 'preload'
        preload_models = self.config.get("ai.preload_models", [])
        for model_name in preload_models:
            try:
                await self.get_model(model_name)
            except Exception as e:
                self.logger.warning(f"⚠️ Failed to preload model '{model_name}': {e}")

        self._initialized = True
        self.logger.info("✅ AI Model Manager initialized")

    async def get_model(self, model_name: ModelType) -> ModelInstance:
        """
        Получить экземпляр модели по имени.
        Если модель не загружена — загружает её с учётом ресурсов и кэша.
        """
        if self._shutdown:
            raise RuntimeError("Model manager is shutting down")

        # Проверяем кэш
        cached = self.cache.get(f"model:{model_name}")
        if cached and not self._is_model_stale(model_name):
            self._update_usage_stats(model_name)
            self.metrics.increment("ai.model.cache_hit", tags={"model": model_name})
            return cached

        # Если не в кэше — загружаем
        if model_name not in self._loaded_models:
            await self._load_model(model_name)

        instance = self._loaded_models[model_name]
        self.cache.set(f"model:{model_name}", instance, ttl=3600)  # кэш на 1 час
        self._update_usage_stats(model_name)
        self.metrics.increment("ai.model.load", tags={"model": model_name})
        return instance

    async def _load_model(self, model_name: ModelType) -> None:
        """Загружает модель с учётом типа (локальная / API / плагин)."""
        self.logger.info(f"📥 Loading model: {model_name}")

        model_info = self.registry.get_model_info(model_name)
        if not model_info:
            raise ValueError(f"Unknown model: {model_name}")

        # Проверка доступности ресурсов
        required_memory = model_info.get("memory_mb", 1024)
        if not self.memory_optimizer.can_allocate(required_memory):
            # Выгружаем наименее используемую модель
            await self._evict_least_used_model()

        try:
            start_time = time.time()
            provider = model_info.get("provider", "local")
            model_path = model_info.get("path")
            api_key = None

            if provider == "openai":
                from ai_plugins.openai_plugin import OpenAIModelAdapter
                api_key = self.crypto.decrypt_secret("OPENAI_API_KEY")
                instance = OpenAIModelAdapter(model_name, api_key=api_key)
            elif provider == "anthropic":
                from ai_plugins.claude_plugin import ClaudeModelAdapter
                api_key = self.crypto.decrypt_secret("ANTHROPIC_API_KEY")
                instance = ClaudeModelAdapter(model_name, api_key=api_key)
            elif provider == "local":
                if not model_path:
                    raise ValueError(f"Local model '{model_name}' requires 'path' in registry")
                model_path = Path(model_path)
                if not model_path.exists():
                    raise FileNotFoundError(f"Model path not found: {model_path}")
                # Используем sandboxed loader
                instance = await self._load_local_model_safely(model_path, model_name)
            else:
                # Поддержка плагинов
                plugin_class = self._load_plugin_model(provider, model_name)
                instance = plugin_class(model_info)

            self._loaded_models[model_name] = instance
            self._model_load_times[model_name] = time.time() - start_time
            self.logger.info(f"✅ Model '{model_name}' loaded in {self._model_load_times[model_name]:.2f}s")

        except Exception as e:
            self.logger.error(f"💥 Failed to load model '{model_name}': {e}", exc_info=True)
            self.metrics.increment("ai.model.load_failure", tags={"model": model_name})
            raise

    async def _load_local_model_safely(self, path: Path, model_name: str) -> ModelInstance:
        """Безопасная загрузка локальной модели в изолированной среде."""
        # TODO: в продакшене — использовать subprocess или контейнеризацию
        # Здесь — базовая защита через try/except и ограничение путей
        if ".." in str(path) or not str(path).startswith("ai/models/"):
            raise ValueError("Invalid model path (security violation)")

        if "whisper" in model_name:
            from ai_services.transcription_service import WhisperModelLoader
            return WhisperModelLoader.load(str(path))
        elif "gpt" in model_name or "llama" in model_name:
            from ai_services.copywriting_service import TransformerModelLoader
            return TransformerModelLoader.load(str(path))
        else:
            raise NotImplementedError(f"Unsupported local model type: {model_name}")

    def _load_plugin_model(self, provider: str, model_name: str) -> type:
        """Загружает класс модели из плагина."""
        try:
            plugin_module = f"plugins.ai_plugins.{provider}_plugin"
            plugin = __import__(plugin_module, fromlist=["get_model_class"])
            return plugin.get_model_class(model_name)
        except ImportError as e:
            raise ImportError(f"Plugin for provider '{provider}' not found: {e}")

    def _is_model_stale(self, model_name: str) -> bool:
        """Проверяет, устарела ли модель в кэше (например, после обновления конфига)."""
        last_used = self._model_last_used.get(model_name, 0)
        ttl = self.config.get("ai.model_cache_ttl_seconds", 3600)
        return (time.time() - last_used) > ttl

    def _update_usage_stats(self, model_name: str) -> None:
        """Обновляет статистику использования модели."""
        self._model_usage_count[model_name] = self._model_usage_count.get(model_name, 0) + 1
        self._model_last_used[model_name] = time.time()

    async def _evict_least_used_model(self) -> None:
        """Выгружает наименее используемую модель для освобождения памяти."""
        if not self._loaded_models:
            return

        # Находим модель с минимальным usage и максимальным временем бездействия
        candidate = min(
            self._loaded_models.keys(),
            key=lambda m: (
                self._model_usage_count.get(m, 0),
                -self._model_last_used.get(m, 0)  # чем старше — тем приоритетнее выгрузка
            )
        )

        self.logger.info(f"📤 Evicting least-used model: {candidate}")
        await self.unload_model(candidate)

    async def unload_model(self, model_name: ModelType) -> None:
        """Выгружает модель из памяти и очищает кэш."""
        if model_name not in self._loaded_models:
            return

        instance = self._loaded_models.pop(model_name)
        self.cache.delete(f"model:{model_name}")

        # Вызываем cleanup, если поддерживается
        if hasattr(instance, "cleanup"):
            try:
                await instance.cleanup()
            except Exception as e:
                self.logger.warning(f"⚠️ Error during model cleanup: {e}")

        self.logger.info(f"🗑️ Model '{model_name}' unloaded")
        self.metrics.increment("ai.model.unload", tags={"model": model_name})

    async def shutdown(self) -> None:
        """Корректное завершение работы: выгрузка всех моделей."""
        self._shutdown = True
        self.logger.info("🛑 Shutting down IntelligentModelManager...")

        tasks = [self.unload_model(name) for name in list(self._loaded_models.keys())]
        await asyncio.gather(*tasks, return_exceptions=True)

        self.logger.info("✅ Model manager shut down complete")

    def get_model_performance_report(self) -> Dict[str, Any]:
        """Возвращает отчёт о производительности всех моделей."""
        return {
            "loaded_models": list(self._loaded_models.keys()),
            "load_times_sec": self._model_load_times,
            "usage_counts": self._model_usage_count,
            "last_used_timestamps": self._model_last_used,
            "memory_usage_mb": self.memory_optimizer.get_current_usage(),
        }