# Файл: core/ai_management/adaptive_model_loader.py
"""
Адаптивная система загрузки моделей ИИ с автоматическим выбором оптимальной конфигурации
под доступные ресурсы устройства (ПК/ноутбук без дискретной видеокарты)
"""
import os
import psutil
import torch
import logging
from typing import Dict, Any, Optional, Tuple
from pathlib import Path
from enum import Enum
from transformers import AutoModel, AutoTokenizer, pipeline

logger = logging.getLogger(__name__)


class DeviceCapability(Enum):
    """Классификация возможностей устройства"""
    HIGH_END_GPU = "high_end_gpu"  # GPU с 8+ ГБ VRAM (RTX 3070+)
    MID_RANGE_GPU = "mid_range_gpu"  # GPU с 4-8 ГБ VRAM (GTX 1660 / RTX 3050)
    INTEGRATED_GPU = "integrated_gpu"  # Интегрированная графика (Intel Iris / AMD Vega)
    CPU_ONLY = "cpu_only"  # Только CPU (ноутбуки без GPU)


class ModelVariant(Enum):
    """Варианты моделей для разных устройств"""
    FULL = "full"  # Полная модель (оригинальная)
    QUANTIZED_INT8 = "int8"  # Квантованная 8-бит
    QUANTIZED_INT4 = "int4"  # Квантованная 4-бит (для слабых устройств)
    DISTILLED = "distilled"  # Дистиллированная легкая версия


@dataclass
class DeviceProfile:
    """Профиль устройства с автоматическим определением характеристик"""
    total_ram_gb: float
    available_ram_gb: float
    has_gpu: bool
    gpu_name: Optional[str]
    gpu_vram_gb: Optional[float]
    cpu_cores: int
    capability: DeviceCapability
    recommended_variant: ModelVariant


class AdaptiveModelLoader:
    """
    Интеллектуальная система загрузки моделей с автоматической адаптацией
    под возможности устройства пользователя
    """

    def __init__(self, base_model_dir: str = "ai/models"):
        self.base_model_dir = Path(base_model_dir)
        self.device_profile = self._detect_device_capabilities()
        self.loaded_models: Dict[str, Any] = {}
        self.model_variants: Dict[str, Dict[str, str]] = self._define_model_variants()

        logger.info(f"Обнаружен профиль устройства: {self.device_profile.capability.value}")
        logger.info(f"Рекомендуемый вариант моделей: {self.device_profile.recommended_variant.value}")
        logger.info(
            f"Доступно ОЗУ: {self.device_profile.available_ram_gb:.1f} ГБ из {self.device_profile.total_ram_gb:.1f} ГБ")
        if self.device_profile.has_gpu:
            logger.info(f"GPU: {self.device_profile.gpu_name} с {self.device_profile.gpu_vram_gb:.1f} ГБ VRAM")

    def _detect_device_capabilities(self) -> DeviceProfile:
        """Автоматическое определение характеристик устройства"""
        # Определение ОЗУ
        total_ram = psutil.virtual_memory().total / (1024 ** 3)
        available_ram = psutil.virtual_memory().available / (1024 ** 3)
        cpu_cores = psutil.cpu_count(logical=True)

        # Определение GPU
        has_gpu = torch.cuda.is_available()
        gpu_name = None
        gpu_vram = None

        if has_gpu:
            gpu_name = torch.cuda.get_device_name(0)
            gpu_vram = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)

        # Классификация устройства
        if has_gpu and gpu_vram >= 8.0:
            capability = DeviceCapability.HIGH_END_GPU
            recommended_variant = ModelVariant.FULL
        elif has_gpu and gpu_vram >= 4.0:
            capability = DeviceCapability.MID_RANGE_GPU
            recommended_variant = ModelVariant.QUANTIZED_INT8
        elif has_gpu:
            capability = DeviceCapability.INTEGRATED_GPU
            recommended_variant = ModelVariant.QUANTIZED_INT4
        elif total_ram >= 16.0:
            capability = DeviceCapability.CPU_ONLY
            recommended_variant = ModelVariant.DISTILLED
        else:
            capability = DeviceCapability.CPU_ONLY
            recommended_variant = ModelVariant.QUANTIZED_INT4

        return DeviceProfile(
            total_ram_gb=total_ram,
            available_ram_gb=available_ram,
            has_gpu=has_gpu,
            gpu_name=gpu_name,
            gpu_vram_gb=gpu_vram,
            cpu_cores=cpu_cores,
            capability=capability,
            recommended_variant=recommended_variant
        )

    def _define_model_variants(self) -> Dict[str, Dict[str, str]]:
        """Определение путей к различным вариантам моделей"""
        return {
            "embedding": {
                "full": "bert-base-multilingual",
                "distilled": "distilbert-base-multilingual-cased",
                "quantized_int8": "bert-base-multilingual-int8",
                "quantized_int4": "bert-base-multilingual-int4"
            },
            "textgen": {
                "full": "gpt2-medium",
                "distilled": "gpt2",
                "quantized_int8": "gpt2-medium-int8",
                "quantized_int4": "gpt2-medium-int4"
            },
            "translation": {
                "full": "nllb-200",
                "distilled": "nllb-200-distilled-600M",
                "quantized_int8": "nllb-200-int8",
                "quantized_int4": "nllb-200-int4"
            },
            "whisper": {
                "full": "whisper-medium",
                "distilled": "whisper-small",
                "quantized_int8": "whisper-medium-int8",
                "quantized_int4": "whisper-small-int4"
            }
        }

    def get_optimal_variant(self, model_type: str) -> Tuple[str, ModelVariant]:
        """
        Получение оптимального варианта модели для текущего устройства
        """
        variants = self.model_variants.get(model_type, {})
        recommended = self.device_profile.recommended_variant.value

        # Поиск рекомендуемого варианта
        if recommended in variants:
            return variants[recommended], ModelVariant(recommended)

        # Резервные варианты в порядке убывания производительности
        fallback_order = ["distilled", "quantized_int8", "quantized_int4", "full"]
        for variant in fallback_order:
            if variant in variants:
                return variants[variant], ModelVariant(variant)

        # Если ничего не найдено — использовать полную модель как резерв
        return variants.get("full", variants[list(variants.keys())[0]]), ModelVariant.FULL

    async def load_model(self, model_type: str, force_variant: Optional[ModelVariant] = None) -> Any:
        """
        Загрузка модели с автоматической адаптацией под возможности устройства
        """
        # Определение оптимального варианта
        if force_variant:
            variant_name = force_variant.value
            model_path = self.model_variants[model_type].get(variant_name)
            if not model_path:
                # Автоматический фолбэк на доступный вариант
                model_path, detected_variant = self.get_optimal_variant(model_type)
                logger.warning(
                    f"Вариант {variant_name} недоступен для {model_type}, используется {detected_variant.value}")
        else:
            model_path, variant = self.get_optimal_variant(model_type)

        # Проверка существования модели на диске
        full_path = self.base_model_dir / model_path
        if not full_path.exists():
            logger.info(f"Модель {model_path} отсутствует, запускается автоматическая загрузка...")
            await self._download_model(model_type, variant)

        # Загрузка модели с оптимальными параметрами
        logger.info(
            f"Загрузка модели {model_type} ({variant.value}) для устройства {self.device_profile.capability.value}")

        try:
            if model_type == "embedding":
                return self._load_embedding_model(full_path, variant)
            elif model_type == "textgen":
                return self._load_textgen_model(full_path, variant)
            elif model_type == "translation":
                return self._load_translation_model(full_path, variant)
            elif model_type == "whisper":
                return self._load_whisper_model(full_path, variant)
            else:
                raise ValueError(f"Неизвестный тип модели: {model_type}")

        except RuntimeError as e:
            if "out of memory" in str(e).lower() or "cuda out of memory" in str(e).lower():
                logger.warning(
                    f"Недостаточно памяти для загрузки {model_type} ({variant.value}), пробуем более легкий вариант...")
                # Автоматический переход на более легкий вариант
                lighter_variants = {
                    ModelVariant.FULL: ModelVariant.QUANTIZED_INT8,
                    ModelVariant.QUANTIZED_INT8: ModelVariant.QUANTIZED_INT4,
                    ModelVariant.QUANTIZED_INT4: ModelVariant.DISTILLED,
                    ModelVariant.DISTILLED: ModelVariant.QUANTIZED_INT4  # Циклический фолбэк
                }
                new_variant = lighter_variants.get(variant, ModelVariant.QUANTIZED_INT4)
                return await self.load_model(model_type, force_variant=new_variant)
            else:
                raise

    def _load_embedding_model(self, path: Path, variant: ModelVariant):
        """Загрузка модели эмбеддингов с оптимизациями для слабых устройств"""
        device = "cuda" if self.device_profile.has_gpu and self.device_profile.gpu_vram_gb >= 2.0 else "cpu"

        # Применение квантования при необходимости
        load_kwargs = {}
        if variant == ModelVariant.QUANTIZED_INT8:
            load_kwargs["load_in_8bit"] = True
        elif variant == ModelVariant.QUANTIZED_INT4:
            load_kwargs["load_in_4bit"] = True

        # Загрузка модели
        model = AutoModel.from_pretrained(
            str(path),
            device_map="auto" if device == "cuda" else None,
            **load_kwargs
        )
        tokenizer = AutoTokenizer.from_pretrained(str(path))

        # Оптимизация для CPU
        if device == "cpu" and variant != ModelVariant.QUANTIZED_INT4:
            model = torch.quantization.quantize_dynamic(
                model, {torch.nn.Linear}, dtype=torch.qint8
            )
            logger.info("Применено динамическое квантование для CPU")

        return {"model": model, "tokenizer": tokenizer, "device": device, "variant": variant.value}

    def _load_textgen_model(self, path: Path, variant: ModelVariant):
        """Загрузка модели генерации текста с ограничением длины для экономии памяти"""
        device = "cuda" if self.device_profile.has_gpu and self.device_profile.gpu_vram_gb >= 3.0 else "cpu"

        # Ограничение длины генерации в зависимости от возможностей устройства
        max_length = {
            DeviceCapability.HIGH_END_GPU: 1024,
            DeviceCapability.MID_RANGE_GPU: 512,
            DeviceCapability.INTEGRATED_GPU: 256,
            DeviceCapability.CPU_ONLY: 128
        }.get(self.device_profile.capability, 256)

        return pipeline(
            "text-generation",
            model=str(path),
            device=0 if device == "cuda" else -1,
            max_length=max_length,
            torch_dtype=torch.float16 if device == "cuda" and variant != ModelVariant.QUANTIZED_INT4 else torch.float32
        )

    def _load_whisper_model(self, path: Path, variant: ModelVariant):
        """Загрузка модели Whisper с адаптацией под возможности устройства"""
        device = "cuda" if self.device_profile.has_gpu and self.device_profile.gpu_vram_gb >= 2.0 else "cpu"

        # Выбор размера модели в зависимости от памяти
        model_size = "medium" if self.device_profile.gpu_vram_gb and self.device_profile.gpu_vram_gb >= 4.0 else "small"

        return pipeline(
            "automatic-speech-recognition",
            model=f"openai/whisper-{model_size}",
            device=0 if device == "cuda" else -1,
            torch_dtype=torch.float16 if device == "cuda" else torch.float32,
            chunk_length_s=30,  # Оптимизация для слабых устройств
            stride_length_s=5
        )

    async def _download_model(self, model_type: str, variant: ModelVariant):
        """Автоматическая загрузка модели с прогресс-баром"""
        import huggingface_hub

        model_map = {
            "embedding": {
                "full": "sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
                "distilled": "sentence-transformers/distiluse-base-multilingual-cased-v1",
                "quantized_int8": "sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
                # Квантование при загрузке
                "quantized_int4": "sentence-transformers/distiluse-base-multilingual-cased-v1"
            },
            "textgen": {
                "full": "gpt2-medium",
                "distilled": "gpt2",
                "quantized_int8": "gpt2-medium",
                "quantized_int4": "gpt2"
            },
            "translation": {
                "full": "facebook/nllb-200-3.3B",
                "distilled": "facebook/nllb-200-distilled-600M",
                "quantized_int8": "facebook/nllb-200-distilled-600M",
                "quantized_int4": "facebook/nllb-200-distilled-600M"
            },
            "whisper": {
                "full": "openai/whisper-medium",
                "distilled": "openai/whisper-small",
                "quantized_int8": "openai/whisper-small",
                "quantized_int4": "openai/whisper-small"
            }
        }

        model_name = model_map[model_type][variant.value]
        save_path = self.base_model_dir / self.model_variants[model_type][variant.value]

        logger.info(f"Загрузка модели {model_name} в {save_path}...")

        # Создание директории
        save_path.parent.mkdir(parents=True, exist_ok=True)

        # Загрузка с прогрессом
        huggingface_hub.snapshot_download(
            repo_id=model_name,
            local_dir=str(save_path),
            progress=True
        )

        # Применение квантования для соответствующих вариантов
        if variant in [ModelVariant.QUANTIZED_INT8, ModelVariant.QUANTIZED_INT4]:
            await self._apply_quantization(save_path, variant)

        logger.info(f"Модель {model_type} ({variant.value}) успешно загружена в {save_path}")

    async def _apply_quantization(self, model_path: Path, variant: ModelVariant):
        """Применение квантования к загруженной модели"""
        try:
            from transformers import AutoModelForCausalLM, AutoTokenizer
            from transformers import BitsAndBytesConfig

            # Загрузка модели для квантования
            model = AutoModelForCausalLM.from_pretrained(str(model_path))
            tokenizer = AutoTokenizer.from_pretrained(str(model_path))

            # Применение квантования
            if variant == ModelVariant.QUANTIZED_INT8:
                quantization_config = BitsAndBytesConfig(load_in_8bit=True)
            else:  # QUANTIZED_INT4
                quantization_config = BitsAndBytesConfig(load_in_4bit=True)

            # Сохранение квантованной модели
            model.save_pretrained(str(model_path), quantization_config=quantization_config)
            tokenizer.save_pretrained(str(model_path))

            logger.info(f"Квантование {variant.value} применено к модели в {model_path}")

        except Exception as e:
            logger.warning(f"Ошибка квантования модели: {str(e)}. Используется оригинальная модель.")

    def get_performance_recommendations(self) -> Dict[str, Any]:
        """Получение рекомендаций по оптимизации производительности"""
        recommendations = []

        if self.device_profile.capability == DeviceCapability.CPU_ONLY:
            recommendations.extend([
                "⚠️ Используется режим только CPU — ожидайте замедление работы ИИ на 5-10x",
                "💡 Рекомендуется: закрыть другие приложения для освобождения ОЗУ",
                "💡 Рекомендуется: использовать квантованные модели (int4) для всех задач",
                "💡 Опционально: подключить внешнюю видеокарту через eGPU (для ноутбуков)",
                "⚡ Оптимизация: включить 'режим экономии ресурсов' в настройках"
            ])

        if self.device_profile.available_ram_gb < 4.0:
            recommendations.extend([
                "⚠️ Критически мало доступной оперативной памяти (<4 ГБ)",
                "💡 Обязательно: включить агрессивное кэширование и ограничение одновременных задач",
                "💡 Обязательно: использовать только квантованные модели int4",
                "💡 Рекомендуется: увеличить файл подкачки до 8 ГБ"
            ])

        if self.device_profile.capability == DeviceCapability.INTEGRATED_GPU:
            recommendations.extend([
                "⚠️ Используется интегрированная графика — производительность ограничена",
                "💡 Рекомендуется: установить драйверы последней версии для максимизации производительности",
                "💡 Рекомендуется: ограничить одновременную работу до 2 моделей ИИ",
                "💡 Опционально: использовать облачные ИИ-сервисы для тяжелых задач (оплачивается отдельно)"
            ])

        return {
            "device_profile": {
                "capability": self.device_profile.capability.value,
                "ram_total_gb": round(self.device_profile.total_ram_gb, 1),
                "ram_available_gb": round(self.device_profile.available_ram_gb, 1),
                "has_gpu": self.device_profile.has_gpu,
                "gpu_vram_gb": round(self.device_profile.gpu_vram_gb, 1) if self.device_profile.gpu_vram_gb else None
            },
            "recommended_variant": self.device_profile.recommended_variant.value,
            "recommendations": recommendations,
            "estimated_performance": self._estimate_performance()
        }

    def _estimate_performance(self) -> Dict[str, str]:
        """Оценка производительности для различных задач"""
        estimates = {}

        if self.device_profile.capability == DeviceCapability.CPU_ONLY:
            estimates = {
                "text_generation": "15-30 сек на 100 слов",
                "translation": "5-10 сек на абзац",
                "transcription": "2-3x реального времени",
                "embedding": "3-5 сек на документ"
            }
        elif self.device_profile.capability == DeviceCapability.INTEGRATED_GPU:
            estimates = {
                "text_generation": "8-15 сек на 100 слов",
                "translation": "3-6 сек на абзац",
                "transcription": "1.5x реального времени",
                "embedding": "2-3 сек на документ"
            }
        elif self.device_profile.capability == DeviceCapability.MID_RANGE_GPU:
            estimates = {
                "text_generation": "3-6 сек на 100 слов",
                "translation": "1-2 сек на абзац",
                "transcription": "0.8x реального времени",
                "embedding": "0.5-1 сек на документ"
            }
        else:  # HIGH_END_GPU
            estimates = {
                "text_generation": "1-2 сек на 100 слов",
                "translation": "0.3-0.5 сек на абзац",
                "transcription": "0.3x реального времени",
                "embedding": "0.2-0.3 сек на документ"
            }

        return estimates

    async def cleanup_memory(self):
        """Очистка памяти от неиспользуемых моделей"""
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            logger.info("Очистка кэша CUDA выполнена")

        # Выгрузка моделей, не использовавшихся более 15 минут
        current_time = psutil.time()
        models_to_unload = []

        for model_name, model_info in self.loaded_models.items():
            last_used = model_info.get("last_used", 0)
            if current_time - last_used > 900:  # 15 минут
                models_to_unload.append(model_name)

        for model_name in models_to_unload:
            del self.loaded_models[model_name]
            logger.info(f"Модель {model_name} выгружена из памяти для освобождения ресурсов")

    def health_check(self) -> Dict[str, Any]:
        """Проверка здоровья системы загрузки моделей"""
        return {
            "device_profile": self.device_profile.capability.value,
            "available_ram_gb": round(self.device_profile.available_ram_gb, 1),
            "loaded_models": list(self.loaded_models.keys()),
            "gpu_available": self.device_profile.has_gpu,
            "gpu_vram_gb": round(self.device_profile.gpu_vram_gb, 1) if self.device_profile.gpu_vram_gb else None,
            "recommendations": self.get_performance_recommendations()["recommendations"][:3]  # Первые 3 рекомендации
        }