"""
Адаптивное управление ресурсами в зависимости от профиля устройства.
Автоматически настраивает параметры выполнения под возможности железа.
"""

import json
import os
from pathlib import Path
from typing import Dict, Any, Optional
import threading

from scripts.setup.detect_device_profile import DeviceProfileDetector


class ResourceAdaptor:
    """
    Адаптер ресурсов, который автоматически настраивает поведение системы
    в зависимости от аппаратного профиля устройства.
    """

    def __init__(self,
                 profile_path: str = "config/profiles/auto_detected.json",
                 fallback_profile: str = "balanced"):
        self.profile_path = Path(profile_path)
        self.fallback_profile = fallback_profile
        self.current_profile: Optional[Dict[str, Any]] = None
        self._lock = threading.RLock()
        self._load_profile()

    def _load_profile(self):
        """Загрузка конфигурации профиля"""
        with self._lock:
            if self.profile_path.exists():
                try:
                    with open(self.profile_path, 'r', encoding='utf-8') as f:
                        self.current_profile = json.load(f)
                    print(f"Загружен профиль: {self.current_profile.get('name', 'unknown')}")
                except Exception as e:
                    print(f"Ошибка загрузки профиля: {e}. Используется резервный профиль.")
                    self._use_fallback_profile()
            else:
                print(f"Файл профиля не найден: {self.profile_path}. Выполняется авто-детектирование...")
                self._detect_and_save_profile()

    def _detect_and_save_profile(self):
        """Авто-детектирование и сохранение профиля"""
        try:
            detector = DeviceProfileDetector()
            self.current_profile = detector.get_profile_config()
            detector.save_profile_config(str(self.profile_path))
        except Exception as e:
            print(f"Ошибка авто-детектирования: {e}. Используется резервный профиль.")
            self._use_fallback_profile()

    def _use_fallback_profile(self):
        """Использование резервного профиля"""
        detector = DeviceProfileDetector()
        self.current_profile = detector.get_profile_config(self.fallback_profile)

    def get_max_parallel_tasks(self) -> int:
        """Получение максимального количества параллельных задач"""
        with self._lock:
            return self.current_profile.get('max_parallel_tasks', 2)

    def get_model_quantization(self) -> str:
        """Получение рекомендуемого уровня квантования моделей"""
        with self._lock:
            return self.current_profile.get('model_quantization', 'int8')

    def get_cache_strategy(self) -> str:
        """Получение стратегии кэширования"""
        with self._lock:
            return self.current_profile.get('cache_strategy', 'ram_balanced')

    def should_use_gpu(self) -> bool:
        """Проверка необходимости использования GPU"""
        with self._lock:
            hardware = self.current_profile.get('hardware_info', {})
            return hardware.get('has_dedicated_gpu', False)

    def is_laptop(self) -> bool:
        """Проверка, является ли устройство ноутбуком"""
        with self._lock:
            hardware = self.current_profile.get('hardware_info', {})
            return hardware.get('is_laptop', False)

    def get_memory_safety_margin(self) -> float:
        """
        Получение безопасного запаса памяти (в процентах).
        Ноутбуки требуют большего запаса из-за термальных ограничений.
        """
        with self._lock:
            if self.is_laptop():
                return 0.75  # 75% максимального использования для ноутбуков
            else:
                return 0.90  # 90% для десктопов

    def adapt_ai_model_loading(self, model_size_gb: float) -> Dict[str, Any]:
        """
        Адаптация параметров загрузки ИИ-модели под возможности устройства.

        Returns:
            Словарь с параметрами загрузки: {
                'quantization': str,
                'device_map': str,
                'max_memory': Optional[Dict],
                'offload_folder': Optional[str]
            }
        """
        with self._lock:
            profile_name = self.current_profile.get('name', 'balanced')
            ram_gb = self.current_profile.get('hardware_info', {}).get('ram_total_gb', 8)
            has_gpu = self.current_profile.get('hardware_info', {}).get('has_dedicated_gpu', False)
            gpu_mem_gb = self.current_profile.get('hardware_info', {}).get('gpu_info', {}).get('total_memory_gb', 0)

            # Определение стратегии загрузки
            if profile_name == 'ultra_low':
                # Только квантизация + выгрузка на диск
                return {
                    'quantization': 'int4',
                    'device_map': 'cpu',
                    'max_memory': None,
                    'offload_folder': 'data/cache/offload',
                    'use_cache': True
                }

            elif profile_name == 'low_resource':
                # Квантизация int8 + частичная выгрузка
                return {
                    'quantization': 'int8',
                    'device_map': 'cpu' if not has_gpu else 'auto',
                    'max_memory': {0: f"{min(2, gpu_mem_gb)}GB"} if has_gpu else None,
                    'offload_folder': 'data/cache/offload' if not has_gpu else None,
                    'use_cache': True
                }

            elif profile_name == 'balanced':
                # FP16 для GPU или квантизация для CPU
                if has_gpu and gpu_mem_gb >= model_size_gb * 0.7:
                    return {
                        'quantization': 'fp16',
                        'device_map': 'auto',
                        'max_memory': None,
                        'offload_folder': None,
                        'use_cache': True
                    }
                else:
                    return {
                        'quantization': 'int8',
                        'device_map': 'cpu',
                        'max_memory': None,
                        'offload_folder': 'data/cache/offload',
                        'use_cache': True
                    }

            else:  # high_performance
                # Полная загрузка без квантизации
                return {
                    'quantization': 'none',
                    'device_map': 'auto' if has_gpu else 'cpu',
                    'max_memory': None,
                    'offload_folder': None,
                    'use_cache': True
                }

    def adapt_batch_size(self, task_type: str, default_batch_size: int) -> int:
        """
        Адаптация размера батча под возможности устройства.

        Args:
            task_type: Тип задачи ('text_generation', 'embedding', 'translation')
            default_batch_size: Базовый размер батча

        Returns:
            Адаптированный размер батча
        """
        with self._lock:
            profile_name = self.current_profile.get('name', 'balanced')
            ram_gb = self.current_profile.get('hardware_info', {}).get('ram_total_gb', 8)

            # Коэффициенты адаптации для разных профилей
            profile_factors = {
                'ultra_low': 0.25,
                'low_resource': 0.5,
                'balanced': 1.0,
                'high_performance': 2.0
            }

            factor = profile_factors.get(profile_name, 1.0)

            # Дополнительная адаптация под тип задачи
            task_factors = {
                'text_generation': 0.8,  # Более требовательная задача
                'embedding': 1.2,  # Менее требовательная
                'translation': 1.0
            }

            task_factor = task_factors.get(task_type, 1.0)

            adapted_size = int(default_batch_size * factor * task_factor)
            return max(1, min(adapted_size, 32))  # Ограничение от 1 до 32

    def should_enable_power_saving(self) -> bool:
        """
        Определение необходимости включения режима энергосбережения.
        Актуально для ноутбуков при работе от батареи.
        """
        with self._lock:
            if not self.is_laptop():
                return False

            # Проверка режима питания (только для ноутбуков)
            try:
                import psutil
                battery = psutil.sensors_battery()
                if battery and not battery.power_plugged:
                    return True  # Работа от батареи
            except:
                pass

            return False

    def get_adaptation_report(self) -> str:
        """Генерация отчета об адаптации ресурсов"""
        with self._lock:
            hardware = self.current_profile.get('hardware_info', {})
            profile = self.current_profile

            report = []
            report.append("=" * 60)
            report.append("ОТЧЕТ ОБ АДАПТАЦИИ РЕСУРСОВ")
            report.append("=" * 60)
            report.append(f"Профиль устройства: {profile.get('name', 'unknown')}")
            report.append(f"Описание: {profile.get('description', 'N/A')}")
            report.append(f"RAM: {hardware.get('ram_total_gb', 0):.1f} ГБ")
            report.append(f"GPU: {'Да' if hardware.get('has_dedicated_gpu') else 'Нет'}")
            report.append(f"Тип устройства: {'Ноутбук' if hardware.get('is_laptop') else 'Десктоп'}")
            report.append(f"Ядер CPU: {hardware.get('cpu_cores', 'N/A')}")
            report.append("-" * 60)
            report.append("РЕКОМЕНДУЕМЫЕ ПАРАМЕТРЫ:")
            report.append(f"  • Макс. параллельных задач: {self.get_max_parallel_tasks()}")
            report.append(f"  • Квантизация моделей: {self.get_model_quantization()}")
            report.append(f"  • Стратегия кэширования: {self.get_cache_strategy()}")
            report.append(f"  • Использовать GPU: {'Да' if self.should_use_gpu() else 'Нет'}")
            report.append(
                f"  • Режим энергосбережения: {'Включен' if self.should_enable_power_saving() else 'Выключен'}")
            report.append("=" * 60)

            return "\n".join(report)


# Глобальный экземпляр адаптера (паттерн Singleton)
_resource_adaptor_instance = None


def get_resource_adaptor(profile_path: str = "config/profiles/auto_detected.json") -> ResourceAdaptor:
    """Получение глобального экземпляра адаптера ресурсов"""
    global _resource_adaptor_instance

    if _resource_adaptor_instance is None:
        _resource_adaptor_instance = ResourceAdaptor(profile_path)

    return _resource_adaptor_instance

# Пример использования в других модулях:
# from core.performance.resource_adaptor import get_resource_adaptor
#
# adaptor = get_resource_adaptor()
# batch_size = adaptor.adapt_batch_size('text_generation', default_batch_size=8)
# quantization = adaptor.get_model_quantization()