"""
Единый хаб управления ИИ-моделями с поддержкой гибридной загрузки,
адаптивного кэширования и мониторинга состояния моделей.
"""

import json
import os
import time
from enum import Enum
from pathlib import Path
from typing import Dict, Any, Optional, List, Literal, Tuple
from dataclasses import dataclass, asdict
import hashlib
import threading
from datetime import datetime, timedelta

import torch
import psutil
from transformers import AutoModel, AutoTokenizer, pipeline
from sentence_transformers import SentenceTransformer

from core.ai_management.lazy_model_loader import LazyModelLoader
from core.ai_management.model_registry import ModelRegistry
from core.monitoring.metrics_collector import MetricsCollector
from core.security.encryption_engine import EncryptionEngine


class ModelProvider(Enum):
    """Провайдер модели: локальный, облачный или гибридный"""
    LOCAL = "local"
    CLOUD = "cloud"
    HYBRID = "hybrid"


class ModelTaskType(Enum):
    """Типы задач для моделей"""
    TEXT_GENERATION = "text_generation"
    TRANSLATION = "translation"
    EMBEDDINGS = "embeddings"
    SPEECH_TO_TEXT = "speech_to_text"
    SENTIMENT_ANALYSIS = "sentiment_analysis"
    SUMMARIZATION = "summarization"


@dataclass
class ModelHealthMetrics:
    """Метрики здоровья модели"""
    latency_ms: float
    memory_usage_mb: float
    success_rate: float
    last_checked: datetime
    error_count: int
    cpu_usage_percent: float
    gpu_memory_mb: Optional[float] = None


@dataclass
class ModelConfig:
    """Конфигурация модели"""
    model_id: str
    task_type: ModelTaskType
    provider: ModelProvider
    local_path: Optional[str] = None
    cloud_endpoint: Optional[str] = None
    priority: int = 5  # 1-10, где 10 - высший приоритет
    min_vram_gb: float = 0.0
    fallback_model: Optional[str] = None
    cache_ttl_hours: int = 24
    quantization: Literal["none", "int8", "int4", "fp16"] = "none"
    language: str = "ru"


class AIModelHub:
    """
    Централизованный хаб управления всеми ИИ-моделями в системе.
    Обеспечивает:
    - Единый интерфейс доступа к моделям
    - Автоматическое переключение между локальными/облачными провайдерами
    - Адаптивное кэширование на диск
    - Мониторинг здоровья и автоматические откаты
    - Приоритизацию по частоте использования
    """

    def __init__(self, config_path: str = "config/ai_config.json"):
        self.config_path = config_path
        self.models: Dict[str, Dict[str, Any]] = {}
        self.model_configs: Dict[str, ModelConfig] = {}
        self.usage_stats: Dict[str, int] = {}  # model_id -> usage_count
        self.health_metrics: Dict[str, ModelHealthMetrics] = {}
        self.lazy_loader = LazyModelLoader()
        self.model_registry = ModelRegistry()
        self.metrics_collector = MetricsCollector()
        self.encryption_engine = EncryptionEngine()
        self._lock = threading.RLock()
        self._load_configs()
        self._initialize_cache()

    def _load_configs(self):
        """Загрузка конфигураций моделей из JSON"""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config_data = json.load(f)

            # Загрузка глобальных настроек
            self.default_provider = ModelProvider(config_data.get('default_provider', 'local'))
            self.fallback_enabled = config_data.get('fallback_enabled', True)
            self.max_concurrent_models = config_data.get('max_concurrent_models', 3)

            # Загрузка конфигураций отдельных моделей
            for model_id, cfg in config_data.get('models', {}).items():
                self.model_configs[model_id] = ModelConfig(
                    model_id=model_id,
                    task_type=ModelTaskType(cfg['task_type']),
                    provider=ModelProvider(cfg.get('provider', 'local')),
                    local_path=cfg.get('local_path'),
                    cloud_endpoint=cfg.get('cloud_endpoint'),
                    priority=cfg.get('priority', 5),
                    min_vram_gb=cfg.get('min_vram_gb', 0.0),
                    fallback_model=cfg.get('fallback_model'),
                    cache_ttl_hours=cfg.get('cache_ttl_hours', 24),
                    quantization=cfg.get('quantization', 'none'),
                    language=cfg.get('language', 'ru')
                )

            self._logger.info(f"Загружено {len(self.model_configs)} конфигураций моделей")

        except Exception as e:
            self._logger.error(f"Ошибка загрузки конфигураций моделей: {e}")
            raise

    def _initialize_cache(self):
        """Инициализация системы кэширования моделей на диск"""
        self.cache_dir = Path("data/cache/models")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_index_path = self.cache_dir / "cache_index.json"

        if self.cache_index_path.exists():
            with open(self.cache_index_path, 'r', encoding='utf-8') as f:
                self.cache_index = json.load(f)
        else:
            self.cache_index = {
                "models": {},
                "last_cleanup": datetime.now().isoformat(),
                "total_size_mb": 0
            }

    def get_model(self,
                  task_type: ModelTaskType,
                  language: str = "ru",
                  provider: Optional[ModelProvider] = None,
                  force_reload: bool = False) -> Any:
        """
        Получение модели для указанной задачи с автоматической адаптацией под ресурсы.

        Args:
            task_type: Тип задачи (генерация текста, перевод и т.д.)
            language: Язык модели (по умолчанию "ru")
            provider: Принудительный выбор провайдера (локальный/облачный)
            force_reload: Принудительная перезагрузка модели

        Returns:
            Экземпляр модели или пайплайна для работы

        Raises:
            ModelUnavailableError: Если ни одна модель не доступна для задачи
        """
        with self._lock:
            # 1. Найти подходящие модели по критериям
            candidates = self._find_candidate_models(task_type, language, provider)

            if not candidates:
                raise ModelUnavailableError(
                    f"Не найдено моделей для задачи {task_type.value} и языка {language}"
                )

            # 2. Отсортировать кандидатов по приоритету и доступности ресурсов
            sorted_candidates = self._sort_candidates_by_priority(candidates)

            # 3. Попытаться загрузить первую доступную модель
            for model_id in sorted_candidates:
                try:
                    model = self._load_or_get_cached_model(model_id, force_reload)
                    self._update_usage_stats(model_id)
                    self._log_model_access(model_id, task_type, language)
                    return model

                except Exception as e:
                    self._logger.warning(
                        f"Не удалось загрузить модель {model_id}: {e}. "
                        f"Попытка использовать резервную модель..."
                    )
                    # Попробовать резервную модель
                    fallback = self.model_configs[model_id].fallback_model
                    if fallback and fallback in self.model_configs:
                        try:
                            model = self._load_or_get_cached_model(fallback, force_reload)
                            self._update_usage_stats(fallback)
                            self._log_model_access(fallback, task_type, language)
                            return model
                        except Exception as fe:
                            self._logger.error(f"Резервная модель {fallback} также недоступна: {fe}")

            raise ModelUnavailableError(
                f"Все кандидаты для задачи {task_type.value} недоступны. "
                f"Проверьте конфигурацию и доступные ресурсы."
            )

    def _find_candidate_models(self,
                               task_type: ModelTaskType,
                               language: str,
                               provider: Optional[ModelProvider]) -> List[str]:
        """Поиск подходящих моделей по критериям"""
        candidates = []

        for model_id, config in self.model_configs.items():
            # Проверка совпадения типа задачи
            if config.task_type != task_type:
                continue

            # Проверка языка (если указан)
            if language != "any" and config.language != language:
                continue

            # Проверка провайдера (если указан принудительно)
            if provider and config.provider != provider:
                continue

            # Проверка доступности ресурсов для локальной загрузки
            if config.provider == ModelProvider.LOCAL:
                if not self._check_resource_availability(config):
                    continue

            candidates.append(model_id)

        return candidates

    def _check_resource_availability(self, config: ModelConfig) -> bool:
        """Проверка достаточности ресурсов для загрузки модели"""
        # Проверка VRAM для моделей с требованиями к видеопамяти
        if config.min_vram_gb > 0:
            try:
                if torch.cuda.is_available():
                    total_vram = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
                    if total_vram < config.min_vram_gb:
                        return False
                else:
                    # Для CPU-режима используем общий объем RAM как ориентир
                    total_ram = psutil.virtual_memory().total / (1024 ** 3)
                    if total_ram < config.min_vram_gb * 1.5:  # +50% запас для CPU
                        return False
            except Exception as e:
                self._logger.warning(f"Ошибка проверки ресурсов: {e}")
                return False

        return True

    def _sort_candidates_by_priority(self, candidates: List[str]) -> List[str]:
        """Сортировка кандидатов по приоритету с учетом статистики использования"""

        def sort_key(model_id):
            config = self.model_configs[model_id]
            # Комбинированный приоритет: конфигурация + частота использования
            usage_boost = min(self.usage_stats.get(model_id, 0) / 100, 2.0)  # Макс +200% к приоритету
            effective_priority = config.priority * (1 + usage_boost)
            return -effective_priority  # Сортировка по убыванию

        return sorted(candidates, key=sort_key)

    def _load_or_get_cached_model(self, model_id: str, force_reload: bool = False) -> Any:
        """Загрузка модели с использованием кэша на диске"""
        # 1. Проверить кэш на диске
        cache_key = self._generate_cache_key(model_id)
        cache_path = self.cache_dir / f"{cache_key}.pt"

        if not force_reload and cache_path.exists():
            cache_info = self.cache_index["models"].get(cache_key)
            if cache_info:
                # Проверить TTL кэша
                cache_time = datetime.fromisoformat(cache_info["timestamp"])
                ttl = timedelta(hours=self.model_configs[model_id].cache_ttl_hours)
                if datetime.now() - cache_time < ttl:
                    try:
                        self._logger.info(f"Загрузка модели {model_id} из кэша на диске")
                        # Загрузка зашифрованного кэша
                        encrypted_data = cache_path.read_bytes()
                        decrypted_data = self.encryption_engine.decrypt(encrypted_data)
                        model = torch.load(decrypted_data, map_location='cpu')
                        self.models[model_id] = model
                        self._update_health_metrics(model_id, success=True)
                        return model
                    except Exception as e:
                        self._logger.warning(f"Ошибка загрузки из кэша: {e}. Загрузка заново...")

        # 2. Загрузка через ленивый загрузчик
        config = self.model_configs[model_id]
        model = self.lazy_loader.load_model(
            model_id=model_id,
            model_path=config.local_path or model_id,
            task_type=config.task_type.value,
            quantization=config.quantization,
            provider=config.provider
        )

        self.models[model_id] = model

        # 3. Сохранение в кэш на диск (асинхронно)
        self._cache_model_to_disk(model_id, model, cache_key)

        self._update_health_metrics(model_id, success=True)
        return model

    def _generate_cache_key(self, model_id: str) -> str:
        """Генерация уникального ключа кэша для модели"""
        config = self.model_configs[model_id]
        key_data = f"{model_id}:{config.quantization}:{config.provider.value}"
        return hashlib.sha256(key_data.encode()).hexdigest()[:16]

    def _cache_model_to_disk(self, model_id: str, model: Any, cache_key: str):
        """Асинхронное сохранение модели в кэш на диск"""
        import threading

        def _save_task():
            try:
                cache_path = self.cache_dir / f"{cache_key}.pt"

                # Сериализация модели
                buffer = torch.io.BytesIO()
                torch.save(model, buffer)
                buffer.seek(0)
                model_bytes = buffer.read()

                # Шифрование перед сохранением
                encrypted = self.encryption_engine.encrypt(model_bytes)

                # Сохранение на диск
                cache_path.write_bytes(encrypted)

                # Обновление индекса кэша
                with self._lock:
                    self.cache_index["models"][cache_key] = {
                        "model_id": model_id,
                        "timestamp": datetime.now().isoformat(),
                        "size_bytes": len(encrypted),
                        "quantization": self.model_configs[model_id].quantization
                    }

                    # Очистка старого кэша если превышен лимит
                    self._cleanup_old_cache()

                    # Сохранение индекса
                    with open(self.cache_index_path, 'w', encoding='utf-8') as f:
                        json.dump(self.cache_index, f, indent=2, ensure_ascii=False)

                self._logger.info(f"Модель {model_id} сохранена в кэш: {cache_path}")

            except Exception as e:
                self._logger.error(f"Ошибка сохранения модели в кэш: {e}")

        # Запуск в отдельном потоке для неблокирующей операции
        threading.Thread(target=_save_task, daemon=True).start()

    def _cleanup_old_cache(self, max_size_gb: float = 5.0):
        """Очистка старого кэша при превышении лимита"""
        max_bytes = max_size_gb * (1024 ** 3)
        total_size = sum(info["size_bytes"] for info in self.cache_index["models"].values())

        if total_size > max_bytes:
            # Сортировка моделей по времени использования (самые старые первыми)
            sorted_models = sorted(
                self.cache_index["models"].items(),
                key=lambda x: x[1]["timestamp"]
            )

            # Удаление старых моделей до достижения лимита
            for cache_key, info in sorted_models:
                if total_size <= max_bytes * 0.8:  # Оставить 20% запаса
                    break

                cache_path = self.cache_dir / f"{cache_key}.pt"
                if cache_path.exists():
                    try:
                        cache_path.unlink()
                        total_size -= info["size_bytes"]
                        del self.cache_index["models"][cache_key]
                        self._logger.info(f"Удален кэш модели {info['model_id']} для освобождения места")
                    except Exception as e:
                        self._logger.warning(f"Ошибка удаления кэша {cache_key}: {e}")

            self.cache_index["total_size_mb"] = total_size / (1024 ** 2)

    def _update_usage_stats(self, model_id: str):
        """Обновление статистики использования модели"""
        self.usage_stats[model_id] = self.usage_stats.get(model_id, 0) + 1

    def _log_model_access(self, model_id: str, task_type: ModelTaskType, language: str):
        """Логирование доступа к модели для аналитики"""
        self.metrics_collector.record_metric(
            "model_access",
            {
                "model_id": model_id,
                "task_type": task_type.value,
                "language": language,
                "timestamp": datetime.now().isoformat()
            }
        )

    def _update_health_metrics(self, model_id: str, success: bool, latency_ms: Optional[float] = None):
        """Обновление метрик здоровья модели"""
        # Сбор метрик ресурсов
        process = psutil.Process()
        cpu_percent = process.cpu_percent(interval=0.1)
        mem_info = process.memory_info()
        mem_mb = mem_info.rss / (1024 ** 2)

        gpu_mem = None
        if torch.cuda.is_available():
            try:
                gpu_mem = torch.cuda.memory_allocated() / (1024 ** 2)
            except:
                pass

        # Обновление метрик
        current = self.health_metrics.get(model_id)
        if current:
            error_count = current.error_count if success else current.error_count + 1
            success_rate = (current.success_rate * 0.9) + (1.0 if success else 0.0) * 0.1
        else:
            error_count = 0 if success else 1
            success_rate = 1.0 if success else 0.0

        self.health_metrics[model_id] = ModelHealthMetrics(
            latency_ms=latency_ms or (current.latency_ms if current else 100.0),
            memory_usage_mb=mem_mb,
            success_rate=success_rate,
            last_checked=datetime.now(),
            error_count=error_count,
            cpu_usage_percent=cpu_percent,
            gpu_memory_mb=gpu_mem
        )

    def switch_model_runtime(self, model_id: str, provider: Literal["local", "cloud", "hybrid"]):
        """Динамическое переключение провайдера модели во время выполнения"""
        if model_id not in self.model_configs:
            raise ValueError(f"Модель {model_id} не найдена в конфигурации")

        # Очистка текущей загруженной модели
        if model_id in self.models:
            del self.models[model_id]

        # Обновление конфигурации
        self.model_configs[model_id].provider = ModelProvider(provider)

        self._logger.info(f"Провайдер модели {model_id} изменен на {provider}")

    def monitor_model_health(self) -> Dict[str, ModelHealthMetrics]:
        """Получение метрик здоровья всех моделей"""
        # Автоматическая проверка моделей, не проверявшихся более 5 минут
        for model_id in list(self.models.keys()):
            metrics = self.health_metrics.get(model_id)
            if not metrics or (datetime.now() - metrics.last_checked) > timedelta(minutes=5):
                try:
                    # Простой тест работоспособности
                    test_start = time.time()
                    _ = self.get_model(
                        self.model_configs[model_id].task_type,
                        self.model_configs[model_id].language
                    )
                    latency = (time.time() - test_start) * 1000

                    self._update_health_metrics(model_id, success=True, latency_ms=latency)
                except Exception as e:
                    self._logger.warning(f"Модель {model_id} не отвечает: {e}")
                    self._update_health_metrics(model_id, success=False)

        return self.health_metrics.copy()

    def get_model_recommendations(self, task_type: ModelTaskType, language: str = "ru") -> List[Dict[str, Any]]:
        """Получение рекомендаций по выбору модели с учетом текущего состояния системы"""
        candidates = self._find_candidate_models(task_type, language, None)
        recommendations = []

        for model_id in candidates:
            config = self.model_configs[model_id]
            health = self.health_metrics.get(model_id)

            # Расчет общего рейтинга
            base_score = config.priority * 10
            if health:
                health_score = health.success_rate * 50 + (100 - health.latency_ms / 10) * 0.3
                base_score += health_score

            # Штраф за нехватку ресурсов
            if not self._check_resource_availability(config):
                base_score *= 0.5

            recommendations.append({
                "model_id": model_id,
                "score": base_score,
                "provider": config.provider.value,
                "quantization": config.quantization,
                "estimated_vram_gb": config.min_vram_gb,
                "health_status": "healthy" if health and health.success_rate > 0.95 else "degraded" if health else "unknown"
            })

        return sorted(recommendations, key=lambda x: x["score"], reverse=True)

    @property
    def _logger(self):
        """Ленивая инициализация логгера"""
        if not hasattr(self, '_internal_logger'):
            import logging
            self._internal_logger = logging.getLogger('AIModelHub')
        return self._internal_logger


class ModelUnavailableError(Exception):
    """Исключение: модель недоступна для загрузки"""
    pass


# Глобальный экземпляр хаба (паттерн Singleton)
_ai_model_hub_instance = None
_ai_model_hub_lock = threading.Lock()


def get_ai_model_hub(config_path: str = "config/ai_config.json") -> AIModelHub:
    """
    Получение глобального экземпляра AIModelHub (Singleton).

    Returns:
        Единый экземпляр хаба моделей для всего приложения
    """
    global _ai_model_hub_instance, _ai_model_hub_lock

    if _ai_model_hub_instance is None:
        with _ai_model_hub_lock:
            if _ai_model_hub_instance is None:
                _ai_model_hub_instance = AIModelHub(config_path)

    return _ai_model_hub_instance