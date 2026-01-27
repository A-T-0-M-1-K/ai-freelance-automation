"""
Ленивая загрузка моделей ИИ с приоритизацией по частоте использования
и адаптивным кэшированием на диск для экономии памяти.
"""

import json
import os
import time
import threading
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timedelta
import hashlib
import pickle
import gc

import torch
import psutil
from transformers import AutoModel, AutoTokenizer, pipeline
from sentence_transformers import SentenceTransformer

from core.security.encryption_engine import EncryptionEngine


class LazyModelLoader:
    """
    Система ленивой загрузки моделей с поддержкой:
    - Приоритизации по частоте использования
    - Адаптивного кэширования на диск
    - Автоматической выгрузки редкоиспользуемых моделей
    - Гибридной загрузки (локально/облачно)
    """

    def __init__(self,
                 cache_dir: str = "data/cache/models_lazy",
                 max_memory_percent: float = 70.0,
                 eviction_threshold_percent: float = 85.0):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_memory_percent = max_memory_percent
        self.eviction_threshold_percent = eviction_threshold_percent
        self.loaded_models: Dict[str, Dict[str, Any]] = {}
        self.usage_stats: Dict[str, Dict[str, Any]] = {}  # model_id -> {last_used, usage_count, load_time}
        self.cache_index_path = self.cache_dir / "cache_index.json"
        self.encryption_engine = EncryptionEngine()
        self._lock = threading.RLock()
        self._load_cache_index()

        # Запуск фонового монитора памяти
        self._start_memory_monitor()

    def _load_cache_index(self):
        """Загрузка индекса кэша с диска"""
        if self.cache_index_path.exists():
            try:
                with open(self.cache_index_path, 'r', encoding='utf-8') as f:
                    self.cache_index = json.load(f)
            except Exception as e:
                self._log(f"Ошибка загрузки индекса кэша: {e}", level='WARNING')
                self.cache_index = {"models": {}, "last_cleanup": None, "total_size_bytes": 0}
        else:
            self.cache_index = {"models": {}, "last_cleanup": None, "total_size_bytes": 0}

    def _save_cache_index(self):
        """Сохранение индекса кэша на диск"""
        with open(self.cache_index_path, 'w', encoding='utf-8') as f:
            json.dump(self.cache_index, f, indent=2, ensure_ascii=False)

    def load_model(self,
                  model_id: str,
                  model_path: str,
                  task_type: str,
                  quantization: str = "none",
                  provider: str = "local",
                  force_reload: bool = False) -> Any:
        """
        Ленивая загрузка модели с автоматическим управлением памятью.

        Args:
            model_id: Уникальный идентификатор модели
            model_path: Путь к модели (локальный или Hugging Face ID)
            task_type: Тип задачи (для выбора правильного пайплайна)
            quantization: Уровень квантования ('none', 'int8', 'int4', 'fp16')
            provider: Провайдер ('local', 'cloud', 'hybrid')
            force_reload: Принудительная перезагрузка даже если модель уже загружена

        Returns:
            Загруженная модель или пайплайн
        """
        with self._lock:
            # Проверка наличия в памяти
            if model_id in self.loaded_models and not force_reload:
                self._update_usage_stats(model_id)
                return self.loaded_models[model_id]['model']

            # Проверка доступности памяти и выгрузка редкоиспользуемых моделей при необходимости
            self._ensure_memory_available()

            # Попытка загрузки из кэша на диске
            if not force_reload:
                cached_model = self._load_from_disk_cache(model_id)
                if cached_model:
                    self.loaded_models[model_id] = {
                        'model': cached_model,
                        'loaded_at': datetime.now(),
                        'task_type': task_type,
                        'quantization': quantization,
                        'provider': provider
                    }
                    self._update_usage_stats(model_id)
                    self._log(f"Модель {model_id} загружена из дискового кэша")
                    return cached_model

            # Загрузка с нуля
            self._log(f"Загрузка модели {model_id} из источника (квантизация: {quantization})")
            start_time = time.time()

            try:
                model = self._load_model_from_source(model_path, task_type, quantization, provider)
                load_time = time.time() - start_time

                # Сохранение в памяти
                self.loaded_models[model_id] = {
                    'model': model,
                    'loaded_at': datetime.now(),
                    'task_type': task_type,
                    'quantization': quantization,
                    'provider': provider,
                    'load_time_seconds': load_time
                }

                # Обновление статистики
                self._update_usage_stats(model_id, first_load=True, load_time=load_time)

                # Асинхронное сохранение в дисковый кэш
                self._cache_to_disk_async(model_id, model, quantization)

                self._log(f"Модель {model_id} успешно загружена за {load_time:.2f} сек")
                return model

            except Exception as e:
                self._log(f"Ошибка загрузки модели {model_id}: {e}", level='ERROR')
                raise

    def _load_model_from_source(self,
                              model_path: str,
                              task_type: str,
                              quantization: str,
                              provider: str) -> Any:
        """Загрузка модели из исходного источника с применением квантования"""
        device = "cuda" if torch.cuda.is_available() else "cpu"

        # Определение типа модели по задаче
        if task_type == "text_generation":
            if quantization == "int8":
                model = AutoModel.from_pretrained(model_path, load_in_8bit=True, device_map="auto")
            elif quantization == "int4":
                model = AutoModel.from_pretrained(model_path, load_in_4bit=True, device_map="auto")
            elif quantization == "fp16" and device == "cuda":
                model = AutoModel.from_pretrained(model_path, torch_dtype=torch.float16)
            else:
                model = AutoModel.from_pretrained(model_path)

            tokenizer = AutoTokenizer.from_pretrained(model_path)
            return pipeline("text-generation", model=model, tokenizer=tokenizer, device=0 if device == "cuda" else -1)

        elif task_type == "translation":
            return pipeline("translation", model=model_path, device=0 if device == "cuda" else -1)

        elif task_type == "embeddings":
            return SentenceTransformer(model_path, device=device)

        elif task_type == "speech_to_text":
            return pipeline("automatic-speech-recognition", model=model_path, device=0 if device == "cuda" else -1)

        else:
            raise ValueError(f"Неизвестный тип задачи: {task_type}")

    def _load_from_disk_cache(self, model_id: str) -> Optional[Any]:
        """Загрузка модели из дискового кэша"""
        cache_key = self._generate_cache_key(model_id)
        cache_file = self.cache_dir / f"{cache_key}.pkl.enc"

        if not cache_file.exists():
            return None

        # Проверка актуальности кэша (TTL 24 часа)
        cache_info = self.cache_index["models"].get(cache_key)
        if not cache_info:
            return None

        cache_time = datetime.fromisoformat(cache_info["timestamp"])
        if datetime.now() - cache_time > timedelta(hours=24):
            self._log(f"Кэш модели {model_id} устарел, пропускаем загрузку из кэша")
            return None

        try:
            # Загрузка и расшифровка
            encrypted_data = cache_file.read_bytes()
            decrypted_data = self.encryption_engine.decrypt(encrypted_data)

            # Десериализация
            model_data = pickle.loads(decrypted_data)

            # Восстановление модели из сериализованных данных
            model = self._reconstruct_model_from_cache(model_data)

            self._log(f"Модель {model_id} успешно загружена из дискового кэша")
            return model

        except Exception as e:
            self._log(f"Ошибка загрузки из дискового кэша: {e}", level='WARNING')
            # Удаление поврежденного кэша
            try:
                cache_file.unlink()
                self.cache_index["models"].pop(cache_key, None)
                self._save_cache_index()
            except:
                pass
            return None

    def _reconstruct_model_from_cache(self, model_ Dict[str, Any]) -> Any:
        """Восстановление модели из сериализованных данных кэша"""
        # Для простоты возвращаем данные как есть - в реальной реализации
        # потребуется полная сериализация/десериализация модели
        # В данном примере предполагается, что модель сохраняется через torch.save
        import io
        buffer = io.BytesIO(model_data['model_bytes'])
        return torch.load(buffer, map_location='cpu')

    def _cache_to_disk_async(self, model_id: str, model: Any, quantization: str):
        """Асинхронное сохранение модели в дисковый кэш"""
        import threading

        def _save_task():
            try:
                cache_key = self._generate_cache_key(model_id)
                cache_file = self.cache_dir / f"{cache_key}.pkl.enc"

                # Сериализация модели
                model_bytes = self._serialize_model(model)
                cache_data = {
                    'model_id': model_id,
                    'quantization': quantization,
                    'timestamp': datetime.now().isoformat(),
                    'model_bytes': model_bytes
                }

                # Шифрование
                serialized = pickle.dumps(cache_data)
                encrypted = self.encryption_engine.encrypt(serialized)

                # Сохранение на диск
                cache_file.write_bytes(encrypted)

                # Обновление индекса
                with self._lock:
                    self.cache_index["models"][cache_key] = {
                        "model_id": model_id,
                        "timestamp": datetime.now().isoformat(),
                        "size_bytes": len(encrypted),
                        "quantization": quantization
                    }
                    self.cache_index["total_size_bytes"] += len(encrypted)
                    self._save_cache_index()

                self._log(f"Модель {model_id} сохранена в дисковый кэш")

                # Очистка старого кэша если превышен лимит (5 ГБ)
                self._cleanup_old_cache(max_size_bytes=5 * 1024**3)

            except Exception as e:
                self._log(f"Ошибка сохранения в дисковый кэш: {e}", level='ERROR')

        threading.Thread(target=_save_task, daemon=True).start()

    def _serialize_model(self, model: Any) -> bytes:
        """Сериализация модели в байты"""
        import io
        buffer = io.BytesIO()
        torch.save(model, buffer)
        buffer.seek(0)
        return buffer.read()

    def _generate_cache_key(self, model_id: str) -> str:
        """Генерация уникального ключа кэша"""
        # Включение версии для инвалидации кэша при обновлениях
        version = "v1.0"
        key_data = f"{model_id}:{version}"
        return hashlib.sha256(key_data.encode()).hexdigest()[:20]

    def _update_usage_stats(self, model_id: str, first_load: bool = False, load_time: float = 0.0):
        """Обновление статистики использования модели"""
        now = datetime.now()

        if model_id not in self.usage_stats:
            self.usage_stats[model_id] = {
                'last_used': now,
                'usage_count': 1,
                'total_load_time': load_time if first_load else 0.0,
                'first_loaded': now
            }
        else:
            stats = self.usage_stats[model_id]
            stats['last_used'] = now
            stats['usage_count'] += 1
            if first_load:
                stats['total_load_time'] += load_time

    def _ensure_memory_available(self):
        """Обеспечение доступности памяти через выгрузку редкоиспользуемых моделей"""
        mem = psutil.virtual_memory()

        # Если память заполнена больше порога эвакуации - выгружаем модели
        if mem.percent > self.eviction_threshold_percent:
            self._log(f"Память заполнена на {mem.percent}%, начинаем выгрузку моделей", level='WARNING')

            # Сортировка моделей по частоте использования (редкоиспользуемые первыми)
            sorted_models = sorted(
                self.loaded_models.items(),
                key=lambda x: self.usage_stats.get(x[0], {}).get('usage_count', 0)
            )

            # Выгрузка моделей пока память не освободится до безопасного уровня
            for model_id, model_info in sorted_models:
                if mem.percent <= self.max_memory_percent:
                    break

                # Выгрузка модели
                self._unload_model(model_id)
                self._log(f"Выгружена модель {model_id} для освобождения памяти")

                # Обновление статистики памяти
                mem = psutil.virtual_memory()

    def _unload_model(self, model_id: str):
        """Выгрузка модели из памяти с освобождением ресурсов"""
        if model_id not in self.loaded_models:
            return

        model_info = self.loaded_models.pop(model_id)
        model = model_info['model']

        # Очистка ресурсов в зависимости от типа модели
        if isinstance(model, torch.nn.Module):
            model.cpu()  # Перемещение на CPU перед удалением
            del model
        elif hasattr(model, 'model') and isinstance(model.model, torch.nn.Module):
            model.model.cpu()
            del model.model

        # Принудительная сборка мусора
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        self._log(f"Модель {model_id} выгружена из памяти")

    def _cleanup_old_cache(self, max_size_bytes: int):
        """Очистка старого кэша при превышении лимита размера"""
        if self.cache_index["total_size_bytes"] <= max_size_bytes:
            return

        # Сортировка кэшей по времени использования (самые старые первыми)
        cache_items = sorted(
            self.cache_index["models"].items(),
            key=lambda x: x[1].get("timestamp", "1970-01-01T00:00:00")
        )

        total_size = self.cache_index["total_size_bytes"]

        for cache_key, cache_info in cache_items:
            if total_size <= max_size_bytes * 0.8:  # Оставить 20% запаса
                break

            cache_file = self.cache_dir / f"{cache_key}.pkl.enc"
            if cache_file.exists():
                try:
                    size = cache_file.stat().st_size
                    cache_file.unlink()
                    total_size -= size
                    self.cache_index["models"].pop(cache_key, None)
                    self._log(f"Удален дисковый кэш {cache_info['model_id']} ({size / 1024**2:.2f} МБ)")
                except Exception as e:
                    self._log(f"Ошибка удаления кэша {cache_key}: {e}", level='WARNING')

        self.cache_index["total_size_bytes"] = total_size
        self._save_cache_index()

    def _start_memory_monitor(self):
        """Запуск фонового монитора использования памяти"""
        import threading

        def monitor_loop():
            while True:
                time.sleep(60)  # Проверка каждую минуту

                mem = psutil.virtual_memory()
                if mem.percent > self.eviction_threshold_percent:
                    self._log(f"Монитор памяти: обнаружено высокое использование ({mem.percent}%)", level='WARNING')
                    with self._lock:
                        self._ensure_memory_available()

        monitor_thread = threading.Thread(target=monitor_loop, daemon=True, name="MemoryMonitor")
        monitor_thread.start()

    def get_model_stats(self, model_id: str) -> Dict[str, Any]:
        """Получение статистики по модели"""
        stats = self.usage_stats.get(model_id, {})
        loaded = self.loaded_models.get(model_id, {})

        return {
            'in_memory': model_id in self.loaded_models,
            'usage_count': stats.get('usage_count', 0),
            'last_used': stats.get('last_used'),
            'load_time_avg': stats.get('total_load_time', 0) / max(stats.get('usage_count', 1), 1),
            'quantization': loaded.get('quantization'),
            'provider': loaded.get('provider'),
            'in_disk_cache': self._generate_cache_key(model_id) in self.cache_index["models"]
        }

    def _log(self, message: str, level: str = 'INFO'):
        """Логирование"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f"[{timestamp}] [LazyModelLoader] [{level}] {message}")