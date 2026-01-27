"""
Ленивая загрузка моделей ИИ с кэшированием, квантованием и фоновой предзагрузкой
"""
import asyncio
import torch
import logging
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import time
import os
from pathlib import Path
from transformers import AutoModel, AutoTokenizer, pipeline
from core.ai_management.model_optimizer import ModelOptimizer
from core.performance.intelligent_cache_system import IntelligentCacheSystem

logger = logging.getLogger(__name__)


class ModelSize(Enum):
    SMALL = "small"  # <500MB
    MEDIUM = "medium"  # 500MB - 2GB
    LARGE = "large"  # 2GB - 5GB
    XLARGE = "xlarge"  # >5GB


@dataclass
class ModelConfig:
    """Конфигурация модели для ленивой загрузки"""
    name: str
    model_path: str
    model_type: str  # "transformer", "whisper", "diffusion" и т.д.
    size: ModelSize
    quantization: Optional[str] = None  # "int8", "int4", "fp16"
    device: str = "auto"  # "cuda", "cpu", "auto"
    cache_ttl: int = 86400  # Время жизни в кэше (секунды)
    preload_priority: int = 5  # Приоритет предзагрузки (1-10, 10=высший)
    min_memory_gb: float = 2.0  # Минимум памяти для загрузки


class LazyModelLoader:
    """
    Система ленивой загрузки моделей с адаптивным управлением ресурсами
    """

    def __init__(self, cache_system: IntelligentCacheSystem, model_optimizer: ModelOptimizer):
        self.cache_system = cache_system
        self.model_optimizer = model_optimizer
        self.loaded_models: Dict[str, Any] = {}
        self.model_configs: Dict[str, ModelConfig] = {}
        self._lock = asyncio.Lock()
        self._background_tasks: Dict[str, asyncio.Task] = {}
        self._device = self._detect_device()

        logger.info(f"Ленивая загрузка моделей инициализирована. Устройство: {self._device}")

    def _detect_device(self) -> str:
        """Автоопределение устройства для вычислений"""
        if torch.cuda.is_available():
            free_memory_gb = torch.cuda.get_device_properties(0).total_memory / 1024 ** 3
            logger.info(f"Обнаружена CUDA. Свободная память: {free_memory_gb:.2f}GB")
            return "cuda"
        elif hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
            logger.info("Обнаружен Apple MPS")
            return "mps"
        else:
            logger.warning("CUDA/MPS недоступны. Используется CPU (низкая производительность)")
            return "cpu"

    def register_model(self, config: ModelConfig):
        """Регистрация конфигурации модели"""
        self.model_configs[config.name] = config
        logger.info(f"Зарегистрирована модель '{config.name}' (размер: {config.size.value}, путь: {config.model_path})")

        # Запуск фоновой предзагрузки для высокоприоритетных моделей
        if config.preload_priority >= 8:
            asyncio.create_task(self._background_preload(config.name))

    async def get_model(self, model_name: str, force_reload: bool = False) -> Any:
        """
        Получение модели с ленивой загрузкой
        """
        async with self._lock:
            # Проверка кэша
            if not force_reload and model_name in self.loaded_models:
                model = self.loaded_models[model_name]
                if self._validate_model(model):
                    logger.debug(f"Модель '{model_name}' получена из кэша")
                    return model

            # Загрузка конфигурации
            config = self.model_configs.get(model_name)
            if not config:
                raise ValueError(f"Модель '{model_name}' не зарегистрирована")

            # Проверка достаточности памяти
            if not await self._check_memory_availability(config):
                # Очистка менее приоритетных моделей
                await self._evict_low_priority_models(config.min_memory_gb)

            # Загрузка модели
            logger.info(f"Загрузка модели '{model_name}'...")
            start_time = time.time()

            try:
                model = await self._load_model_with_optimizations(config)
                load_time = time.time() - start_time

                # Кэширование
                self.loaded_models[model_name] = model
                await self.cache_system.set(
                    key=f"model:{model_name}",
                    value=model,
                    ttl=config.cache_ttl,
                    metadata={
                        "load_time": load_time,
                        "device": self._device,
                        "quantization": config.quantization,
                        "size": config.size.value
                    }
                )

                logger.info(f"Модель '{model_name}' загружена за {load_time:.2f}с на устройстве {self._device}")
                return model

            except Exception as e:
                logger.error(f"Ошибка загрузки модели '{model_name}': {str(e)}")
                raise

    async def _load_model_with_optimizations(self, config: ModelConfig) -> Any:
        """Загрузка модели с применением оптимизаций"""
        # Определение устройства с учетом ограничений памяти
        device = config.device if config.device != "auto" else self._device

        # Применение квантования при необходимости
        load_kwargs = {}

        if config.quantization == "int8":
            load_kwargs["load_in_8bit"] = True
        elif config.quantization == "int4":
            load_kwargs["load_in_4bit"] = True
        elif config.quantization == "fp16" and device != "cpu":
            load_kwargs["torch_dtype"] = torch.float16

        # Загрузка в зависимости от типа модели
        if config.model_type == "transformer":
            # Для моделей transformers
            model = AutoModel.from_pretrained(
                config.model_path,
                device_map="auto" if device == "cuda" else None,
                **load_kwargs
            )
            tokenizer = AutoTokenizer.from_pretrained(config.model_path)
            return {"model": model, "tokenizer": tokenizer}

        elif config.model_type == "whisper":
            # Для Whisper моделей
            return pipeline(
                "automatic-speech-recognition",
                model=config.model_path,
                device=0 if device == "cuda" else -1,
                torch_dtype=torch.float16 if config.quantization == "fp16" else torch.float32
            )

        elif config.model_type == "text-generation":
            # Для генеративных моделей
            return pipeline(
                "text-generation",
                model=config.model_path,
                device=0 if device == "cuda" else -1,
                max_new_tokens=512,
                **load_kwargs
            )

        else:
            raise ValueError(f"Неизвестный тип модели: {config.model_type}")

    async def _check_memory_availability(self, config: ModelConfig) -> bool:
        """Проверка доступности достаточного объема памяти"""
        if self._device == "cuda":
            free_memory = torch.cuda.mem_get_info()[0] / 1024 ** 3  # В GB
            required = config.min_memory_gb * 1.2  # +20% запас
            return free_memory >= required
        return True  # На CPU проверка не требуется

    async def _evict_low_priority_models(self, required_gb: float):
        """Выгрузка менее приоритетных моделей для освобождения памяти"""
        if self._device != "cuda":
            return

        current_free = torch.cuda.mem_get_info()[0] / 1024 ** 3
        to_free = required_gb * 1.2 - current_free

        if to_free <= 0:
            return

        # Сортировка моделей по приоритету (низкий приоритет = первые на выгрузку)
        models_by_priority = sorted(
            self.loaded_models.items(),
            key=lambda x: self.model_configs.get(x[0], ModelConfig("", "", "", ModelSize.SMALL)).preload_priority
        )

        freed = 0.0
        for model_name, model in models_by_priority:
            if freed >= to_free:
                break

            # Оценка освобождаемой памяти
            model_size_gb = self._estimate_model_size(model_name)
            del self.loaded_models[model_name]
            torch.cuda.empty_cache()

            freed += model_size_gb
            logger.info(f"Выгружена модель '{model_name}' для освобождения {model_size_gb:.2f}GB памяти")

    def _estimate_model_size(self, model_name: str) -> float:
        """Оценка размера модели в памяти"""
        config = self.model_configs.get(model_name)
        if not config:
            return 1.0  # Значение по умолчанию

        size_map = {
            ModelSize.SMALL: 0.5,
            ModelSize.MEDIUM: 2.0,
            ModelSize.LARGE: 4.0,
            ModelSize.XLARGE: 8.0
        }

        base_size = size_map.get(config.size, 2.0)

        # Корректировка на квантование
        if config.quantization == "int8":
            base_size *= 0.5
        elif config.quantization == "int4":
            base_size *= 0.25

        return base_size

    def _validate_model(self, model: Any) -> bool:
        """Валидация загруженной модели"""
        try:
            if isinstance(model, dict) and "model" in model:
                return model["model"] is not None
            return model is not None
        except:
            return False

    async def _background_preload(self, model_name: str):
        """Фоновая предзагрузка модели после первого запуска системы"""
        # Задержка для завершения основной инициализации
        await asyncio.sleep(30)

        try:
            await self.get_model(model_name)
            logger.info(f"Фоновая предзагрузка модели '{model_name}' завершена")
        except Exception as e:
            logger.warning(f"Фоновая предзагрузка модели '{model_name}' не удалась: {str(e)}")

    async def unload_model(self, model_name: str, force: bool = False):
        """Выгрузка модели из памяти"""
        async with self._lock:
            if model_name in self.loaded_models:
                model = self.loaded_models.pop(model_name)

                # Очистка памяти CUDA
                if self._device == "cuda":
                    if isinstance(model, dict) and "model" in model:
                        del model["model"]
                    else:
                        del model
                    torch.cuda.empty_cache()

                logger.info(f"Модель '{model_name}' выгружена из памяти")

    async def get_model_stats(self) -> Dict[str, Any]:
        """Статистика по загруженным моделям"""
        stats = {
            "loaded_models": list(self.loaded_models.keys()),
            "device": self._device,
            "total_models_registered": len(self.model_configs),
            "memory_usage_gb": self._get_gpu_memory_usage() if self._device == "cuda" else 0.0
        }

        if self._device == "cuda":
            free, total = torch.cuda.mem_get_info()
            stats["gpu_memory_free_gb"] = free / 1024 ** 3
            stats["gpu_memory_total_gb"] = total / 1024 ** 3

        return stats

    def _get_gpu_memory_usage(self) -> float:
        """Получение использования памяти GPU"""
        if self._device != "cuda":
            return 0.0
        allocated = torch.cuda.memory_allocated(0) / 1024 ** 3
        return allocated