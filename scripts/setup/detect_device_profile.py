#!/usr/bin/env python3
"""
Автоматическое определение профиля производительности устройства
на основе доступных ресурсов (RAM, GPU, CPU).
"""

import psutil
import platform
import subprocess
import json
from pathlib import Path
from typing import Dict, Any, Optional
import torch


class DeviceProfileDetector:
    """Детектор аппаратного профиля устройства"""

    PROFILES = {
        'ultra_low': {
            'min_ram_gb': 0,
            'max_ram_gb': 4,
            'requires_gpu': False,
            'description': 'Ультра-низкий профиль: <4 ГБ RAM, нет GPU',
            'max_parallel_tasks': 1,
            'model_quantization': 'int4',
            'cache_strategy': 'disk_heavy'
        },
        'low_resource': {
            'min_ram_gb': 4,
            'max_ram_gb': 8,
            'requires_gpu': False,
            'description': 'Низкий профиль: 4-8 ГБ RAM, интегрированная графика',
            'max_parallel_tasks': 2,
            'model_quantization': 'int8',
            'cache_strategy': 'disk_balanced'
        },
        'balanced': {
            'min_ram_gb': 8,
            'max_ram_gb': 16,
            'requires_gpu': False,
            'description': 'Сбалансированный профиль: 8-16 ГБ RAM',
            'max_parallel_tasks': 3,
            'model_quantization': 'fp16',
            'cache_strategy': 'ram_balanced'
        },
        'high_performance': {
            'min_ram_gb': 16,
            'max_ram_gb': 1024,  # практически неограниченно
            'requires_gpu': True,
            'description': 'Высокопроизводительный профиль: 16+ ГБ RAM, дискретная GPU',
            'max_parallel_tasks': 5,
            'model_quantization': 'none',
            'cache_strategy': 'ram_heavy'
        }
    }

    def __init__(self):
        self.hardware_info = self._detect_hardware()

    def _detect_hardware(self) -> Dict[str, Any]:
        """Детектирование аппаратных характеристик"""
        # Оперативная память
        ram_total = psutil.virtual_memory().total / (1024 ** 3)  # ГБ

        # Детектирование GPU
        has_cuda = torch.cuda.is_available()
        has_mps = hasattr(torch.backends, 'mps') and torch.backends.mps.is_available()

        gpu_info = {}
        if has_cuda:
            gpu_info = {
                'name': torch.cuda.get_device_name(0),
                'total_memory_gb': torch.cuda.get_device_properties(0).total_memory / (1024 ** 3),
                'compute_capability': torch.cuda.get_device_capability(0)
            }
        elif has_mps:
            gpu_info = {
                'name': 'Apple Silicon GPU',
                'total_memory_gb': 4.0,  # Эвристика для M1/M2
                'compute_capability': (1, 0)
            }

        # Детектирование типа устройства (ноутбук/десктоп)
        is_laptop = self._detect_laptop()

        # Детектирование производительности CPU
        cpu_count = psutil.cpu_count(logical=True)
        cpu_freq = psutil.cpu_freq()
        cpu_max_freq = cpu_freq.max if cpu_freq else 0

        return {
            'ram_total_gb': ram_total,
            'has_dedicated_gpu': has_cuda or has_mps,
            'gpu_info': gpu_info,
            'is_laptop': is_laptop,
            'cpu_cores': cpu_count,
            'cpu_max_freq_mhz': cpu_max_freq,
            'platform': platform.system(),
            'platform_release': platform.release()
        }

    def _detect_laptop(self) -> bool:
        """Эвристическое определение ноутбука"""
        # Проверка через системные утилиты
        if platform.system() == 'Linux':
            try:
                result = subprocess.run(['dmidecode', '-s', 'chassis-type'],
                                        capture_output=True, text=True, timeout=2)
                output = result.stdout.lower()
                return any(keyword in output for keyword in ['laptop', 'notebook', 'portable'])
            except:
                pass

        # Проверка наличия батареи (надежный индикатор ноутбука)
        try:
            batteries = psutil.sensors_battery()
            return batteries is not None
        except:
            pass

        # Эвристика по названию модели (для Windows/macOS)
        try:
            if platform.system() == 'Windows':
                import wmi
                c = wmi.WMI()
                for system in c.Win32_ComputerSystem():
                    return 'laptop' in system.Model.lower() or 'notebook' in system.Model.lower()
            elif platform.system() == 'Darwin':
                result = subprocess.run(['system_profiler', 'SPHardwareDataType'],
                                        capture_output=True, text=True, timeout=2)
                return 'book' in result.stdout.lower()  # MacBook
        except:
            pass

        return False

    def detect_profile(self) -> str:
        """Определение профиля производительности на основе характеристик"""
        ram = self.hardware_info['ram_total_gb']
        has_gpu = self.hardware_info['has_dedicated_gpu']
        is_laptop = self.hardware_info['is_laptop']

        # Ультра-низкий профиль: <4 ГБ RAM
        if ram < 4:
            return 'ultra_low'

        # Низкий профиль: 4-8 ГБ без дискретной GPU (типично для ноутбуков)
        if ram < 8 and not has_gpu and is_laptop:
            return 'low_resource'

        # Сбалансированный профиль: 8-16 ГБ или ноутбук с 8+ ГБ
        if ram < 16 or (is_laptop and ram >= 8):
            return 'balanced'

        # Высокопроизводительный: 16+ ГБ с дискретной GPU
        if ram >= 16 and has_gpu:
            return 'high_performance'

        # Резервный вариант - сбалансированный
        return 'balanced'

    def get_profile_config(self, profile_name: Optional[str] = None) -> Dict[str, Any]:
        """Получение конфигурации профиля"""
        if profile_name is None:
            profile_name = self.detect_profile()

        profile = self.PROFILES.get(profile_name, self.PROFILES['balanced'])
        profile['name'] = profile_name
        profile['hardware_info'] = self.hardware_info

        return profile

    def save_profile_config(self, output_path: str = "config/profiles/auto_detected.json"):
        """Сохранение конфигурации профиля в файл"""
        profile_config = self.get_profile_config()
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(profile_config, f, indent=2, ensure_ascii=False)

        print(f"Авто-определенный профиль сохранен: {output_path}")
        print(f"Профиль: {profile_config['name']}")
        print(f"Описание: {profile_config['description']}")
        print(f"RAM: {self.hardware_info['ram_total_gb']:.1f} ГБ")
        print(f"GPU: {'Да' if self.hardware_info['has_dedicated_gpu'] else 'Нет'}")
        print(f"Тип устройства: {'Ноутбук' if self.hardware_info['is_laptop'] else 'Десктоп'}")

        return profile_config


def main():
    """CLI интерфейс для детектирования профиля"""
    import argparse

    parser = argparse.ArgumentParser(description='Авто-детектирование профиля производительности устройства')
    parser.add_argument('--output', '-o', default='config/profiles/auto_detected.json',
                        help='Путь для сохранения конфигурации профиля')
    parser.add_argument('--print', '-p', action='store_true',
                        help='Вывести информацию в консоль без сохранения')

    args = parser.parse_args()

    detector = DeviceProfileDetector()
    profile_config = detector.get_profile_config()

    if args.print:
        import json
        print(json.dumps(profile_config, indent=2, ensure_ascii=False))
    else:
        detector.save_profile_config(args.output)


if __name__ == "__main__":
    main()