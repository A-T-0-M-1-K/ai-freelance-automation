import os
import psutil
import torch
import gc
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from pathlib import Path
import json


class MemoryOptimizer:
    """
    Продвинутый оптимизатор памяти для систем с ленивой загрузкой моделей ИИ.
    Обеспечивает:
    - Мониторинг использования RAM/GPU
    - Автоматическую выгрузку неиспользуемых моделей
    - Прогнозирование нехватки памяти
    - Динамическую настройку стратегий кэширования
    """

    def __init__(self, config: Dict):
        self.config = config
        self.memory_history: List[Dict] = []
        self.model_usage_stats: Dict[str, Dict] = {}
        self.last_gc_time = datetime.utcnow()
        self.alert_thresholds = config.get("alert_thresholds", {
            "ram_warning": 80,  # %
            "ram_critical": 90,  # %
            "gpu_warning": 85,  # %
            "gpu_critical": 95,  # %
            "swap_warning": 50  # %
        })
        self.stats_file = Path("data/stats/memory_stats.json")
        self._load_history()

    def monitor_memory(self) -> Dict:
        """
        Сбор метрик использования памяти в реальном времени.
        """
        # Системная память (RAM)
        ram = psutil.virtual_memory()
        swap = psutil.swap_memory()

        # GPU память (если доступна)
        gpu_info = self._get_gpu_memory()

        # Память процесса Python
        process = psutil.Process(os.getpid())
        process_memory = process.memory_info()

        timestamp = datetime.utcnow().isoformat()

        metrics = {
            "timestamp": timestamp,
            "ram": {
                "total_gb": ram.total / (1024 ** 3),
                "used_gb": ram.used / (1024 ** 3),
                "available_gb": ram.available / (1024 ** 3),
                "percent": ram.percent,
                "swap_percent": swap.percent
            },
            "gpu": gpu_info,
            "process": {
                "rss_gb": process_memory.rss / (1024 ** 3),
                "vms_gb": process_memory.vms / (1024 ** 3),
                "num_threads": process.num_threads()
            },
            "python_gc": {
                "garbage_count": len(gc.garbage),
                "collections": gc.get_count()
            }
        }

        # Сохранение в историю
        self.memory_history.append(metrics)

        # Очистка старых записей (> 24 часа)
        cutoff = datetime.utcnow() - timedelta(hours=24)
        self.memory_history = [
            m for m in self.memory_history
            if datetime.fromisoformat(m["timestamp"]) > cutoff
        ]

        # Сохранение на диск
        self._save_history()

        # Проверка алертов
        self._check_memory_alerts(metrics)

        return metrics

    def _get_gpu_memory(self) -> Dict:
        """Получение информации об использовании GPU"""
        if not torch.cuda.is_available():
            return {"available": False, "devices": []}

        devices = []
        for i in range(torch.cuda.device_count()):
            props = torch.cuda.get_device_properties(i)
            mem_info = torch.cuda.mem_get_info(i)

            total = props.total_memory
            free = mem_info[0]
            used = total - free

            devices.append({
                "id": i,
                "name": props.name,
                "total_gb": total / (1024 ** 3),
                "used_gb": used / (1024 ** 3),
                "free_gb": free / (1024 ** 3),
                "percent": (used / total) * 100,
                "temperature": self._get_gpu_temperature(i)
            })

        return {
            "available": True,
            "devices": devices,
            "active_device": torch.cuda.current_device()
        }

    def _get_gpu_temperature(self, device_id: int) -> Optional[float]:
        """Получение температуры GPU (Linux только)"""
        try:
            # Для NVIDIA через nvidia-smi
            import subprocess
            result = subprocess.run(
                ['nvidia-smi', '--query-gpu=temperature.gpu', '--format=csv,noheader,nounits'],
                capture_output=True,
                text=True,
                timeout=2
            )
            if result.returncode == 0:
                temps = [float(t.strip()) for t in result.stdout.strip().split('\n')]
                return temps[device_id] if device_id < len(temps) else None
        except:
            pass
        return None

    def _check_memory_alerts(self, metrics: Dict):
        """Проверка пороговых значений и генерация алертов"""
        alerts = []

        # RAM алерты
        if metrics["ram"]["percent"] > self.alert_thresholds["ram_critical"]:
            alerts.append({
                "level": "critical",
                "type": "ram",
                "message": f"Критическое использование RAM: {metrics['ram']['percent']:.1f}%",
                "timestamp": metrics["timestamp"]
            })
        elif metrics["ram"]["percent"] > self.alert_thresholds["ram_warning"]:
            alerts.append({
                "level": "warning",
                "type": "ram",
                "message": f"Высокое использование RAM: {metrics['ram']['percent']:.1f}%",
                "timestamp": metrics["timestamp"]
            })

        # GPU алерты
        if metrics["gpu"]["available"]:
            for device in metrics["gpu"]["devices"]:
                if device["percent"] > self.alert_thresholds["gpu_critical"]:
                    alerts.append({
                        "level": "critical",
                        "type": "gpu",
                        "device_id": device["id"],
                        "message": f"Критическое использование GPU {device['id']}: {device['percent']:.1f}%",
                        "temperature": device.get("temperature"),
                        "timestamp": metrics["timestamp"]
                    })
                elif device["percent"] > self.alert_thresholds["gpu_warning"]:
                    alerts.append({
                        "level": "warning",
                        "type": "gpu",
                        "device_id": device["id"],
                        "message": f"Высокое использование GPU {device['id']}: {device['percent']:.1f}%",
                        "temperature": device.get("temperature"),
                        "timestamp": metrics["timestamp"]
                    })

        # Обработка алертов
        for alert in alerts:
            self._handle_alert(alert)

    def _handle_alert(self, alert: Dict):
        """Обработка алерта — логирование и автоматические действия"""
        print(f"[{alert['level'].upper()}] {alert['message']}")

        # Запись в лог алертов
        alert_log = Path("logs/alerts/memory_alerts.log")
        alert_log.parent.mkdir(parents=True, exist_ok=True)

        with open(alert_log, 'a') as f:
            f.write(f"{alert['timestamp']} | {alert['level']} | {alert['type']} | {alert['message']}\n")

        # Автоматические действия для критических алертов
        if alert["level"] == "critical":
            if alert["type"] == "ram":
                self._emergency_ram_optimization()
            elif alert["type"] == "gpu":
                self._emergency_gpu_optimization(alert.get("device_id", 0))

    def _emergency_ram_optimization(self):
        """Экстренная оптимизация использования RAM"""
        print("⚠️  Запуск экстренной оптимизации RAM...")

        # 1. Принудительный сбор мусора
        gc.collect()

        # 2. Очистка кэшей PyTorch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        # 3. Выгрузка неактивных моделей ИИ
        from core.ai_management.lazy_model_loader import LazyModelLoader
        loader = LazyModelLoader.get_instance()
        unloaded = loader.unload_inactive_models(max_age_minutes=5)
        print(f"   📦 Выгружено неактивных моделей: {len(unloaded)}")

        # 4. Очистка кэша данных
        from core.performance.intelligent_cache_system import IntelligentCacheSystem
        cache = IntelligentCacheSystem.get_instance()
        freed = cache.clear_low_priority_cache()
        print(f"   🗑️  Очищено кэша: {freed / (1024 ** 2):.2f} MB")

        print("✅ Экстренная оптимизация RAM завершена")

    def _emergency_gpu_optimization(self, device_id: int):
        """Экстренная оптимизация использования GPU"""
        print(f"⚠️  Запуск экстренной оптимизации GPU {device_id}...")

        # 1. Очистка кэша CUDA
        torch.cuda.empty_cache()

        # 2. Перемещение неактивных тензоров на CPU
        # (Реализация зависит от архитектуры приложения)

        # 3. Снижение точности вычислений (если возможно)
        # torch.set_float32_matmul_precision('medium')

        print(f"✅ Экстренная оптимизация GPU {device_id} завершена")

    def _save_history(self):
        """Сохранение истории метрик на диск"""
        if not self.stats_file.parent.exists():
            self.stats_file.parent.mkdir(parents=True, exist_ok=True)

        # Сохранение только последних 1000 записей
        history_to_save = self.memory_history[-1000:]

        with open(self.stats_file, 'w') as f:
            json.dump({
                "last_updated": datetime.utcnow().isoformat(),
                "history": history_to_save
            }, f, indent=2)

    def _load_history(self):
        """Загрузка истории метрик с диска"""
        if self.stats_file.exists():
            try:
                with open(self.stats_file) as f:
                    data = json.load(f)
                    self.memory_history = data.get("history", [])
            except Exception as e:
                print(f"⚠️  Ошибка загрузки истории памяти: {e}")

    def get_memory_recommendations(self) -> List[str]:
        """
        Анализ истории и генерация рекомендаций по оптимизации.
        """
        if len(self.memory_history) < 10:
            return ["Недостаточно данных для анализа"]

        # Анализ трендов использования памяти
        recent = self.memory_history[-10:]
        avg_ram = sum(m["ram"]["percent"] for m in recent) / len(recent)
        avg_gpu = 0
        gpu_devices = 0

        if recent[0]["gpu"]["available"]:
            for m in recent:
                for dev in m["gpu"]["devices"]:
                    avg_gpu += dev["percent"]
                    gpu_devices += 1
            avg_gpu = avg_gpu / gpu_devices if gpu_devices > 0 else 0

        recommendations = []

        if avg_ram > 85:
            recommendations.append("⚠️  Среднее использование RAM > 85% — рассмотрите увеличение оперативной памяти")
            recommendations.append("💡 Оптимизация: Уменьшите размер батча для обработки данных")
            recommendations.append("💡 Оптимизация: Включите более агрессивную стратегию выгрузки моделей")

        if avg_gpu > 80:
            recommendations.append("⚠️  Среднее использование GPU > 80% — риск нехватки памяти при пиковых нагрузках")
            recommendations.append("💡 Оптимизация: Используйте квантизацию моделей (int8/float16)")
            recommendations.append("💡 Оптимизация: Внедрите пайплайн обработки с разбивкой на этапы")

        # Анализ утечек памяти (монотонный рост)
        if len(self.memory_history) >= 30:
            first_10 = self.memory_history[-30:-20]
            last_10 = self.memory_history[-10:]
            first_avg = sum(m["ram"]["percent"] for m in first_10) / 10
            last_avg = sum(m["ram"]["percent"] for m in last_10) / 10

            if last_avg - first_avg > 5:  # Рост > 5% за период
                recommendations.append("🚨 Обнаружен потенциальный утечка памяти — рост использования на {:.1f}%".format(
                    last_avg - first_avg))
                recommendations.append("🔍 Рекомендуется: Профилирование памяти через memory_profiler")

        return recommendations if recommendations else ["✅ Использование памяти в норме"]

    def generate_memory_report(self) -> str:
        """
        Генерация подробного отчёта по использованию памяти.
        """
        metrics = self.monitor_memory()
        recommendations = self.get_memory_recommendations()

        report = f"""
Отчёт по использованию памяти
Сгенерировано: {metrics['timestamp']}
{'=' * 60}

📊 Оперативная память (RAM)
   Всего:    {metrics['ram']['total_gb']:.2f} GB
   Использ.: {metrics['ram']['used_gb']:.2f} GB ({metrics['ram']['percent']:.1f}%)
   Свободно: {metrics['ram']['available_gb']:.2f} GB
   Swap:     {metrics['ram']['swap_percent']:.1f}%

{'GPU не обнаружен' if not metrics['gpu']['available'] else ''}
"""

        if metrics['gpu']['available']:
            report += "\n🎮 Видеопамять (GPU)\n"
            for dev in metrics['gpu']['devices']:
                temp_info = f" ({dev['temperature']}°C)" if dev.get('temperature') else ""
                report += f"   Устройство {dev['id']} ({dev['name']}){temp_info}:\n"
                report += f"      Использ.: {dev['used_gb']:.2f} GB ({dev['percent']:.1f}%)\n"
                report += f"      Свободно: {dev['free_gb']:.2f} GB\n"

        report += f"\n🐍 Память процесса Python\n"
        report += f"   RSS:  {metrics['process']['rss_gb']:.2f} GB\n"
        report += f"   VMS:  {metrics['process']['vms_gb']:.2f} GB\n"
        report += f"   Потоки: {metrics['process']['num_threads']}\n"

        report += f"\n💡 Рекомендации:\n"
        for i, rec in enumerate(recommendations, 1):
            report += f"   {i}. {rec}\n"

        return report


# Интеграция с системой мониторинга Prometheus
def setup_prometheus_memory_metrics():
    """
    Настройка метрик памяти для экспорта в Prometheus.
    """
    try:
        from prometheus_client import Gauge, CollectorRegistry, push_to_gateway

        registry = CollectorRegistry()

        ram_percent = Gauge('system_ram_percent', 'RAM usage percent', registry=registry)
        gpu_percent = Gauge('system_gpu_percent', 'GPU usage percent', registry=registry)
        process_rss = Gauge('process_rss_bytes', 'Process RSS memory in bytes', registry=registry)

        # Обновление метрик
        optimizer = MemoryOptimizer(config={})
        metrics = optimizer.monitor_memory()

        ram_percent.set(metrics['ram']['percent'])
        process_rss.set(metrics['process']['rss_gb'] * (1024 ** 3))

        if metrics['gpu']['available'] and metrics['gpu']['devices']:
            gpu_percent.set(metrics['gpu']['devices'][0]['percent'])

        # Отправка в Pushgateway (для краткосрочных задач)
        push_to_gateway('localhost:9091', job='ai_freelance', registry=registry)

        print("✅ Метрики памяти отправлены в Prometheus")

    except ImportError:
        print("ℹ️  Prometheus client не установлен — пропуск экспорта метрик")
    except Exception as e:
        print(f"⚠️  Ошибка экспорта метрик в Prometheus: {e}")