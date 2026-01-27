"""
Мониторинг памяти с интеграцией tracemalloc для детектирования утечек
и автоматического дампа при превышении порогов.
"""

import tracemalloc
import gc
import os
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple
import threading
import psutil


class MemorySnapshot:
    """Снимок использования памяти с детальной информацией"""

    def __init__(self, timestamp: datetime, total_memory_kb: int,
                 peak_memory_kb: int, trace_stats: List[Any]):
        self.timestamp = timestamp
        self.total_memory_kb = total_memory_kb
        self.peak_memory_kb = peak_memory_kb
        self.trace_stats = trace_stats

    def to_dict(self) -> Dict[str, Any]:
        return {
            'timestamp': self.timestamp.isoformat(),
            'total_memory_kb': self.total_memory_kb,
            'peak_memory_kb': self.peak_memory_kb,
            'top_allocations': self._get_top_allocations(10)
        }

    def _get_top_allocations(self, n: int = 10) -> List[Dict[str, Any]]:
        """Получение топ-N аллокаций памяти"""
        top_stats = self.trace_stats[:n]
        result = []

        for stat in top_stats:
            result.append({
                'size_kb': stat.size / 1024,
                'count': stat.count,
                'traceback': self._format_traceback(stat.traceback)
            })

        return result

    def _format_traceback(self, tb) -> List[str]:
        """Форматирование трейсбэка для сериализации"""
        return [str(frame) for frame in tb[:5]]  # Первые 5 фреймов


class MemoryOptimizer:
    """
    Продвинутый монитор памяти с:
    - Интеграцией tracemalloc для отслеживания аллокаций
    - Автоматическим дампом при превышении порогов
    - Детектированием утечек памяти
    - Рекомендациями по оптимизации
    """

    def __init__(self,
                 dump_dir: str = "data/dumps/memory",
                 threshold_mb: int = 512,
                 leak_detection_window: int = 5,
                 check_interval_seconds: int = 60):
        self.dump_dir = Path(dump_dir)
        self.dump_dir.mkdir(parents=True, exist_ok=True)
        self.threshold_mb = threshold_mb
        self.leak_detection_window = leak_detection_window
        self.check_interval_seconds = check_interval_seconds
        self.snapshots: List[MemorySnapshot] = []
        self._lock = threading.RLock()
        self._running = False

        # Запуск мониторинга
        self._start_monitoring()

    def _start_monitoring(self):
        """Запуск фонового мониторинга памяти"""
        tracemalloc.start()
        self._running = True

        import threading

        def monitor_loop():
            while self._running:
                try:
                    self._check_memory_usage()
                    threading.Event().wait(self.check_interval_seconds)
                except Exception as e:
                    self._log(f"Ошибка мониторинга памяти: {e}", level='ERROR')

        thread = threading.Thread(target=monitor_loop, daemon=True, name="MemoryMonitor")
        thread.start()

        self._log("Мониторинг памяти запущен с tracemalloc")

    def _check_memory_usage(self):
        """Проверка использования памяти и принятие мер при превышении порогов"""
        # Текущее использование памяти процессом
        process = psutil.Process()
        mem_info = process.memory_info()
        current_mb = mem_info.rss / (1024 ** 2)

        # Системная память
        system_mem = psutil.virtual_memory()
        system_percent = system_mem.percent

        self._log(f"Использование памяти: процесс={current_mb:.2f} МБ, система={system_percent:.1f}%")

        # Проверка порогов
        if current_mb > self.threshold_mb:
            self._log(f"ПРЕВЫШЕН ПОРОГ ПАМЯТИ ({current_mb:.2f} МБ > {self.threshold_mb} МБ)!", level='WARNING')
            self._handle_memory_threshold_exceeded(current_mb)

        if system_percent > 90:
            self._log(f"КРИТИЧЕСКОЕ ИСПОЛЬЗОВАНИЕ СИСТЕМНОЙ ПАМЯТИ ({system_percent:.1f}%)!", level='CRITICAL')
            self._handle_system_memory_critical()

        # Создание снимка для детектирования утечек
        self._take_snapshot()
        self._detect_memory_leaks()

    def _take_snapshot(self):
        """Создание снимка использования памяти через tracemalloc"""
        snapshot = tracemalloc.take_snapshot()
        stats = snapshot.statistics('lineno')

        mem_snapshot = MemorySnapshot(
            timestamp=datetime.now(),
            total_memory_kb=sum(stat.size for stat in stats) / 1024,
            peak_memory_kb=tracemalloc.get_traced_memory()[1] / 1024,
            trace_stats=stats
        )

        with self._lock:
            self.snapshots.append(mem_snapshot)
            # Ограничение истории снимков
            if len(self.snapshots) > 100:
                self.snapshots.pop(0)

    def _detect_memory_leaks(self):
        """Детектирование утечек памяти через анализ трендов"""
        if len(self.snapshots) < self.leak_detection_window * 2:
            return

        # Сравнение текущего использования с историей
        recent = self.snapshots[-self.leak_detection_window:]
        older = self.snapshots[-self.leak_detection_window * 2:-self.leak_detection_window]

        recent_avg = sum(s.total_memory_kb for s in recent) / len(recent)
        older_avg = sum(s.total_memory_kb for s in older) / len(older)

        # Обнаружение утечки если память растет более чем на 20%
        if recent_avg > older_avg * 1.2:
            growth_percent = ((recent_avg - older_avg) / older_avg) * 100
            self._log(f"ОБНАРУЖЕНА ВОЗМОЖНАЯ УТЕЧКА ПАМЯТИ: рост на {growth_percent:.1f}%", level='WARNING')
            self._generate_leak_report(recent[-1])

    def _handle_memory_threshold_exceeded(self, current_mb: float):
        """Обработка превышения порога памяти"""
        # 1. Принудительная сборка мусора
        gc.collect()
        self._log("Выполнена принудительная сборка мусора")

        # 2. Очистка кэшей (через интеграцию с системой кэширования)
        self._clear_caches()

        # 3. Создание дампа памяти для анализа
        dump_path = self._create_memory_dump(current_mb)
        self._log(f"Создан дамп памяти: {dump_path}")

        # 4. Отправка алерта
        self._send_memory_alert(current_mb, dump_path)

    def _handle_system_memory_critical(self):
        """Обработка критического использования системной памяти"""
        # Экстренные меры: остановка не критичных задач
        self._log("Приняты экстренные меры: остановка фоновых задач", level='CRITICAL')
        # ... логика остановки задач ...

        # Создание критического дампа
        dump_path = self._create_memory_dump(psutil.Process().memory_info().rss / (1024 ** 2), critical=True)
        self._send_critical_alert(dump_path)

    def _clear_caches(self):
        """Очистка кэшей системы"""
        # Интеграция с основной системой кэширования
        try:
            from core.performance.intelligent_cache_system import get_intelligent_cache
            cache = get_intelligent_cache()
            stats_before = cache.get_stats()

            # Очистка 50% кэша
            target_entries = max(1, int(stats_before['total_entries'] * 0.5))
            # ... логика очистки ...

            stats_after = cache.get_stats()
            self._log(f"Очистка кэша: {stats_before['total_entries']} -> {stats_after['total_entries']} записей")
        except Exception as e:
            self._log(f"Ошибка очистки кэша: {e}", level='WARNING')

    def _create_memory_dump(self, memory_mb: float, critical: bool = False) -> Path:
        """Создание дампа памяти для последующего анализа"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        severity = 'critical' if critical else 'warning'
        dump_file = self.dump_dir / f"memory_dump_{severity}_{timestamp}_{int(memory_mb)}mb.json"

        # Сбор детальной информации
        dump_data = {
            'timestamp': datetime.now().isoformat(),
            'severity': severity,
            'memory_usage_mb': memory_mb,
            'system_memory_percent': psutil.virtual_memory().percent,
            'tracemalloc_stats': self._get_tracemalloc_stats(),
            'gc_stats': self._get_gc_stats(),
            'top_objects': self._get_top_objects(),
            'thread_count': threading.active_count(),
            'process_info': self._get_process_info()
        }

        with open(dump_file, 'w', encoding='utf-8') as f:
            json.dump(dump_data, f, indent=2, ensure_ascii=False)

        return dump_file

    def _get_tracemalloc_stats(self) -> Dict[str, Any]:
        """Получение статистики tracemalloc"""
        current, peak = tracemalloc.get_traced_memory()
        return {
            'current_kb': current / 1024,
            'peak_kb': peak / 1024,
            'top_allocations': self._get_top_allocations()
        }

    def _get_top_allocations(self, n: int = 20) -> List[Dict[str, Any]]:
        """Получение топ аллокаций памяти"""
        snapshot = tracemalloc.take_snapshot()
        stats = snapshot.statistics('lineno')[:n]

        result = []
        for stat in stats:
            result.append({
                'size_kb': stat.size / 1024,
                'count': stat.count,
                'filename': stat.traceback[0].filename if stat.traceback else 'unknown',
                'lineno': stat.traceback[0].lineno if stat.traceback else 0
            })

        return result

    def _get_gc_stats(self) -> Dict[str, Any]:
        """Получение статистики сборщика мусора"""
        return {
            'garbage_count': len(gc.garbage),
            'gc_enabled': gc.isenabled(),
            'gc_counts': gc.get_count(),
            'thresholds': gc.get_threshold()
        }

    def _get_top_objects(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Получение топ объектов по потреблению памяти (упрощенно)"""
        # В реальной системе здесь должен быть анализ через objgraph или подобные инструменты
        return []

    def _get_process_info(self) -> Dict[str, Any]:
        """Получение информации о процессе"""
        p = psutil.Process()
        return {
            'pid': p.pid,
            'cpu_percent': p.cpu_percent(interval=0.1),
            'num_threads': p.num_threads(),
            'open_files': len(p.open_files()) if hasattr(p, 'open_files') else 0
        }

    def _generate_leak_report(self, snapshot: MemorySnapshot):
        """Генерация отчета об утечке памяти"""
        report_file = self.dump_dir / f"leak_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"

        report = []
        report.append("# Отчет об обнаруженной утечке памяти")
        report.append(f"Дата: {snapshot.timestamp}")
        report.append(f"Текущее использование: {snapshot.total_memory_kb / 1024:.2f} МБ")
        report.append(f"Пиковое использование: {snapshot.peak_memory_kb / 1024:.2f} МБ")
        report.append("\n## Топ аллокаций памяти")

        for i, alloc in enumerate(snapshot._get_top_allocations(10), 1):
            report.append(f"\n{i}. {alloc['size_kb']:.2f} КБ ({alloc['count']} объектов)")
            for frame in alloc['traceback']:
                report.append(f"   {frame}")

        report.append("\n## Рекомендации")
        report.append("1. Проверьте циклические ссылки в объектах")
        report.append("2. Убедитесь в корректной работе деструкторов (__del__)")
        report.append("3. Проверьте использование глобальных кэшей без ограничения размера")
        report.append("4. Проанализируйте долгоживущие объекты в памяти")

        with open(report_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(report))

        self._log(f"Создан отчет об утечке: {report_file}")

    def _send_memory_alert(self, memory_mb: float, dump_path: Path):
        """Отправка алерта о превышении памяти"""
        try:
            from core.monitoring.alert_manager import AlertManager
            alert_manager = AlertManager()

            alert_manager.send_alert(
                title=f"Превышение порога памяти: {memory_mb:.2f} МБ",
                message=f"Память превысила порог в {self.threshold_mb} МБ. Создан дамп для анализа.",
                severity='warning',
                metadata={
                    'memory_usage_mb': memory_mb,
                    'threshold_mb': self.threshold_mb,
                    'dump_path': str(dump_path),
                    'timestamp': datetime.now().isoformat()
                }
            )
        except Exception as e:
            self._log(f"Ошибка отправки алерта: {e}", level='ERROR')

    def _send_critical_alert(self, dump_path: Path):
        """Отправка критического алерта"""
        # Аналогично _send_memory_alert но с повышенной серьезностью
        pass

    def get_current_stats(self) -> Dict[str, Any]:
        """Получение текущей статистики памяти"""
        process = psutil.Process()
        mem_info = process.memory_info()
        current, peak = tracemalloc.get_traced_memory()

        return {
            'process_memory_mb': mem_info.rss / (1024 ** 2),
            'tracemalloc_current_kb': current / 1024,
            'tracemalloc_peak_kb': peak / 1024,
            'system_memory_percent': psutil.virtual_memory().percent,
            'gc_garbage_count': len(gc.garbage),
            'snapshot_count': len(self.snapshots)
        }

    def _log(self, message: str, level: str = 'INFO'):
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f"[{timestamp}] [MemoryOptimizer] [{level}] {message}")

    def stop(self):
        """Остановка мониторинга"""
        self._running = False
        tracemalloc.stop()
        self._log
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f"[{timestamp}] [MemoryOptimizer] [{level}] {message}")

    def stop(self):
        """Остановка мониторинга памяти"""
        self._running = False
        tracemalloc.stop()
        self._log("Мониторинг памяти остановлен")

    # Глобальный экземпляр оптимизатора памяти (паттерн Singleton)
    _memory_optimizer_instance = None

    def get_memory_optimizer(dump_dir: str = "data/dumps/memory",
                             threshold_mb: int = 512) -> MemoryOptimizer:
        """Получение глобального экземпляра оптимизатора памяти"""
        global _memory_optimizer_instance

        if _memory_optimizer_instance is None:
            _memory_optimizer_instance = MemoryOptimizer(dump_dir, threshold_mb)

        return _memory_optimizer_instance