"""
Интеллектуальная система кэширования с отслеживанием зависимостей
и автоматической инвалидацией при изменении входных данных.
"""

import json
import hashlib
import time
from pathlib import Path
from typing import Dict, Any, Optional, Callable, List, Tuple
from datetime import datetime, timedelta
import threading


class CacheDependency:
    """Зависимость кэша от источника данных"""

    def __init__(self,
                 source_id: str,
                 source_type: str,
                 last_modified: datetime,
                 content_hash: str):
        self.source_id = source_id
        self.source_type = source_type  # 'file', 'database', 'api', 'config'
        self.last_modified = last_modified
        self.content_hash = content_hash

    def to_dict(self) -> Dict[str, Any]:
        return {
            'source_id': self.source_id,
            'source_type': self.source_type,
            'last_modified': self.last_modified.isoformat(),
            'content_hash': self.content_hash
        }

    @classmethod
    def from_dict(cls, Dict[str, Any]

    ) -> 'CacheDependency':
    return cls(
        source_id=data['source_id'],
        source_type=data['source_type'],
        last_modified=datetime.fromisoformat(data['last_modified']),
        content_hash=data['content_hash']
    )


class CacheEntry:
    """Запись в кэше с метаданными и зависимостями"""

    def __init__(self,
                 key: str,
                 value: Any,
                 ttl_seconds: int,
                 dependencies: Optional[List[CacheDependency]] = None):
        self.key = key
        self.value = value
        self.created_at = datetime.now()
        self.expires_at = self.created_at + timedelta(seconds=ttl_seconds)
        self.dependencies = dependencies or []
        self.access_count = 0
        self.last_accessed = self.created_at

    def is_expired(self) -> bool:
        """Проверка истечения TTL"""
        return datetime.now() > self.expires_at

    def is_invalidated(self, dependency_checker: Callable[[CacheDependency], bool]) -> bool:
        """Проверка инвалидации через зависимости"""
        return any(dependency_checker(dep) for dep in self.dependencies)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'key': self.key,
            'value': self.value,
            'created_at': self.created_at.isoformat(),
            'expires_at': self.expires_at.isoformat(),
            'dependencies': [dep.to_dict() for dep in self.dependencies],
            'access_count': self.access_count,
            'last_accessed': self.last_accessed.isoformat()
        }

    @classmethod
    def from_dict(cls, Dict[str, Any]

    ) -> 'CacheEntry':
    entry = cls(
        key=data['key'],
        value=data['value'],
        ttl_seconds=0  # Не используется при восстановлении
    )
    entry.created_at = datetime.fromisoformat(data['created_at'])
    entry.expires_at = datetime.fromisoformat(data['expires_at'])
    entry.dependencies = [CacheDependency.from_dict(dep) for dep in data.get('dependencies', [])]
    entry.access_count = data.get('access_count', 0)
    entry.last_accessed = datetime.fromisoformat(data.get('last_accessed', data['created_at']))
    return entry


class IntelligentCacheSystem:
    """
    Интеллектуальная система кэширования с:
    - Отслеживанием зависимостей от источников данных
    - Автоматической инвалидацией при изменении зависимостей
    - Адаптивным TTL на основе частоты обновления источника
    - Поддержкой различных стратегий (LRU, LFU, TTL)
    """

    def __init__(self,
                 cache_dir: str = "data/cache/intelligent",
                 max_size_mb: int = 1024,
                 default_ttl_seconds: int = 3600):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_size_mb = max_size_mb
        self.default_ttl_seconds = default_ttl_seconds
        self.cache: Dict[str, CacheEntry] = {}
        self.dependency_map: Dict[str, List[str]] = {}  # source_id -> [cache_keys]
        self._lock = threading.RLock()
        self._load_persistent_cache()

        # Фоновая очистка
        self._start_cleanup_thread()

    def get(self, key: str, compute_func: Callable[[], Any],
            dependencies: Optional[List[CacheDependency]] = None,
            ttl_seconds: Optional[int] = None) -> Any:
        """
        Получение значения из кэша или вычисление с кэшированием.

        Args:
            key: Ключ кэша
            compute_func: Функция для вычисления значения при отсутствии в кэше
            dependencies: Зависимости для отслеживания изменений
            ttl_seconds: Время жизни кэша в секундах

        Returns:
            Кэшированное или вычисленное значение
        """
        with self._lock:
            # Проверка наличия в кэше
            entry = self.cache.get(key)

            if entry:
                # Проверка истечения TTL
                if entry.is_expired():
                    self._log(f"Кэш для ключа {key} истек, удаляем")
                    self._remove_entry(key)
                    entry = None
                # Проверка инвалидации зависимостей
                elif dependencies and entry.is_invalidated(self._check_dependency_changed):
                    self._log(f"Кэш для ключа {key} инвалидирован зависимостями, удаляем")
                    self._remove_entry(key)
                    entry = None

            # Возврат из кэша если актуален
            if entry:
                entry.access_count += 1
                entry.last_accessed = datetime.now()
                self._log(f"Попадание в кэш для ключа {key} (доступ #{entry.access_count})")
                return entry.value

            # Вычисление нового значения
            self._log(f"Промах кэша для ключа {key}, вычисление...")
            start_time = time.time()
            value = compute_func()
            compute_time = time.time() - start_time

            # Сохранение в кэш
            ttl = ttl_seconds or self._calculate_adaptive_ttl(dependencies, compute_time)
            new_entry = CacheEntry(
                key=key,
                value=value,
                ttl_seconds=ttl,
                dependencies=dependencies
            )
            self._add_entry(key, new_entry)

            # Регистрация зависимостей
            if dependencies:
                for dep in dependencies:
                    if dep.source_id not in self.dependency_map:
                        self.dependency_map[dep.source_id] = []
                    if key not in self.dependency_map[dep.source_id]:
                        self.dependency_map[dep.source_id].append(key)

            self._log(
                f"Значение для ключа {key} вычислено за {compute_time:.2f} сек и сохранено в кэш (TTL: {ttl} сек)")
            return value

    def _calculate_adaptive_ttl(self, dependencies: Optional[List[CacheDependency]], compute_time: float) -> int:
        """
        Расчет адаптивного TTL на основе:
        - Времени вычисления (долгие вычисления -> больший TTL)
        - Типа зависимостей (редко меняющиеся источники -> больший TTL)
        """
        base_ttl = self.default_ttl_seconds

        # Увеличение TTL для долгих вычислений
        if compute_time > 5.0:
            base_ttl = int(base_ttl * (1 + compute_time / 10))

        # Адаптация под тип зависимостей
        if dependencies:
            # Средняя частота обновления зависимостей (эвристика)
            update_frequency = self._estimate_update_frequency(dependencies)
            if update_frequency == 'rare':  # Редко обновляется
                base_ttl = int(base_ttl * 2)
            elif update_frequency == 'frequent':  # Часто обновляется
                base_ttl = int(base_ttl * 0.5)

        return max(60, min(base_ttl, 86400))  # Ограничение от 1 мин до 24 часов

    def _estimate_update_frequency(self, dependencies: List[CacheDependency]) -> str:
        """Оценка частоты обновления зависимостей (упрощенная эвристика)"""
        # В реальной системе здесь должна быть статистика по каждому источнику
        # Для примера используем эвристику по типу источника
        source_types = {dep.source_type for dep in dependencies}

        if 'config' in source_types or 'database_static' in source_types:
            return 'rare'
        elif 'api' in source_types or 'database_dynamic' in source_types:
            return 'frequent'
        else:
            return 'normal'

    def _check_dependency_changed(self, dependency: CacheDependency) -> bool:
        """Проверка изменения зависимости"""
        # Реализация проверки для разных типов источников
        if dependency.source_type == 'file':
            return self._check_file_changed(dependency.source_id, dependency.content_hash)
        elif dependency.source_type == 'database':
            return self._check_db_changed(dependency.source_id, dependency.last_modified)
        elif dependency.source_type == 'api':
            return self._check_api_changed(dependency.source_id, dependency.content_hash)
        else:
            return False

    def _check_file_changed(self, filepath: str, old_hash: str) -> bool:
        """Проверка изменения файла через хеш содержимого"""
        try:
            path = Path(filepath)
            if not path.exists():
                return True

            current_hash = hashlib.md5(path.read_bytes()).hexdigest()
            return current_hash != old_hash
        except Exception:
            return True

    def _check_db_changed(self, table: str, last_modified: datetime) -> bool:
        """Проверка изменения данных в БД (упрощенно)"""
        # В реальной системе здесь должен быть запрос к БД
        # Для примера всегда возвращаем False (предполагаем неизменность)
        return False

    def _check_api_changed(self, endpoint: str, old_hash: str) -> bool:
        """Проверка изменения данных через API"""
        # В реальной системе здесь должен быть HEAD/conditional GET запрос
        return False

    def _add_entry(self, key: str, entry: CacheEntry):
        """Добавление записи в кэш с управлением размером"""
        self.cache[key] = entry

        # Проверка превышения размера кэша
        if self._get_cache_size_mb() > self.max_size_mb:
            self._evict_entries()

        # Сохранение на диск для персистентности
        self._save_entry_to_disk(key, entry)

    def _remove_entry(self, key: str):
        """Удаление записи из кэша"""
        if key in self.cache:
            entry = self.cache.pop(key)

            # Удаление из карты зависимостей
            for dep_list in self.dependency_map.values():
                if key in dep_list:
                    dep_list.remove(key)

            # Удаление с диска
            cache_file = self.cache_dir / f"{key}.json"
            if cache_file.exists():
                cache_file.unlink()

    def _evict_entries(self):
        """Вытеснение записей по стратегии LFU (Least Frequently Used)"""
        # Сортировка по частоте использования (редко используемые первыми)
        sorted_entries = sorted(
            self.cache.items(),
            key=lambda x: (x[1].access_count, x[1].last_accessed)
        )

        target_size = self.max_size_mb * 0.8  # Целевой размер 80% от максимума

        while self._get_cache_size_mb() > target_size and sorted_entries:
            key, _ = sorted_entries.pop(0)
            self._remove_entry(key)
            self._log(f"Вытеснена запись {key} для освобождения места в кэше")

    def _get_cache_size_mb(self) -> float:
        """Расчет текущего размера кэша в МБ"""
        # Упрощенная оценка (в реальной системе нужно точное измерение)
        return len(self.cache) * 0.1  # Эвристика: ~100 КБ на запись

    def _save_entry_to_disk(self, key: str, entry: CacheEntry):
        """Сохранение записи кэша на диск для персистентности"""
        cache_file = self.cache_dir / f"{key}.json"

        try:
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(entry.to_dict(), f, ensure_ascii=False, indent=2)
        except Exception as e:
            self._log(f"Ошибка сохранения кэша на диск: {e}", level='WARNING')

    def _load_persistent_cache(self):
        """Загрузка кэша с диска при старте"""
        for cache_file in self.cache_dir.glob("*.json"):
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    entry = CacheEntry.from_dict(data)

                    # Проверка актуальности перед загрузкой
                    if not entry.is_expired():
                        self.cache[entry.key] = entry

                        # Восстановление карты зависимостей
                        for dep in entry.dependencies:
                            if dep.source_id not in self.dependency_map:
                                self.dependency_map[dep.source_id] = []
                            if entry.key not in self.dependency_map[dep.source_id]:
                                self.dependency_map[dep.source_id].append(entry.key)
            except Exception as e:
                self._log(f"Ошибка загрузки кэша из {cache_file}: {e}", level='WARNING')
                # Удаление поврежденного файла
                try:
                    cache_file.unlink()
                except:
                    pass

    def _start_cleanup_thread(self):
        """Запуск фонового потока очистки устаревших записей"""
        import threading

        def cleanup_loop():
            while True:
                time.sleep(300)  # Проверка каждые 5 минут

                with self._lock:
                    expired_keys = [k for k, v in self.cache.items() if v.is_expired()]
                    for key in expired_keys:
                        self._remove_entry(key)
                        self._log(f"Удалена устаревшая запись кэша: {key}")

        thread = threading.Thread(target=cleanup_loop, daemon=True, name="CacheCleanup")
        thread.start()

    def invalidate_by_source(self, source_id: str):
        """Инвалидация всех записей, зависящих от указанного источника"""
        with self._lock:
            keys_to_invalidate = self.dependency_map.get(source_id, [])
            for key in keys_to_invalidate[:]:  # Копия списка для безопасного удаления
                self._remove_entry(key)
                self._log(f"Инвалидирована запись {key} из-за изменения источника {source_id}")

    def get_stats(self) -> Dict[str, Any]:
        """Получение статистики кэша"""
        with self._lock:
            total_entries = len(self.cache)
            if total_entries == 0:
                return {'total_entries': 0, 'hit_rate': 0.0, 'size_mb': 0.0}

            total_accesses = sum(entry.access_count for entry in self.cache.values())
            hits = total_accesses - total_entries  # Упрощенная оценка (первый доступ = промах)
            hit_rate = hits / max(total_accesses, 1)

            return {
                'total_entries': total_entries,
                'hit_rate': hit_rate,
                'size_mb': self._get_cache_size_mb(),
                'oldest_entry': min((e.created_at for e in self.cache.values()), default=None),
                'most_accessed': max(((e.access_count, k) for k, e in self.cache.items()), default=(0, None))
            }

    def _log(self, message: str, level: str = 'INFO'):
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f"[{timestamp}] [IntelligentCache] [{level}] {message}")


# Глобальный экземпляр кэша (паттерн Singleton)
_intelligent_cache_instance = None


def get_intelligent_cache(cache_dir: str = "data/cache/intelligent") -> IntelligentCacheSystem:
    """Получение глобального экземпляра кэша"""
    global _intelligent_cache_instance

    if _intelligent_cache_instance is None:
        _intelligent_cache_instance = IntelligentCacheSystem(cache_dir)

    return _intelligent_cache_instance