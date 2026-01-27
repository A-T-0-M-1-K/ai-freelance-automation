"""
Гибридная система загрузки моделей: локально при достаточной VRAM,
иначе через облачные сервисы или Hugging Face Inference API.
"""

import os
import json
import time
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
import torch
import psutil
import requests
from transformers import AutoModel, AutoTokenizer

from core.security.encryption_engine import EncryptionEngine


class HybridModelLoader:
    """
    Гибридная загрузка моделей с автоматическим выбором стратегии:
    - Полная локальная загрузка при достаточной VRAM (>8 ГБ)
    - Частичная загрузка (базовые слои локально, тяжелые — в облако) при средней VRAM (4-8 ГБ)
    - Полностью облачная загрузка при малой VRAM (<4 ГБ)
    """

    def __init__(self,
                 local_models_dir: str = "ai/models",
                 cloud_providers: Optional[Dict[str, Dict[str, str]]] = None):
        self.local_models_dir = Path(local_models_dir)
        self.cloud_providers = cloud_providers or {
            'huggingface': {
                'api_url': 'https://api-inference.huggingface.co/models',
                'api_key_env': 'HUGGINGFACE_API_KEY'
            },
            'replicate': {
                'api_url': 'https://api.replicate.com/v1/predictions',
                'api_key_env': 'REPLICATE_API_KEY'
            }
        }
        self.encryption_engine = EncryptionEngine()
        self.device_info = self._detect_hardware()

    def _detect_hardware(self) -> Dict[str, Any]:
        """Детектирование доступных ресурсов"""
        has_cuda = torch.cuda.is_available()
        has_mps = hasattr(torch.backends, 'mps') and torch.backends.mps.is_available()

        vram_gb = 0.0
        if has_cuda:
            vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
        elif has_mps:
            # MPS не предоставляет прямой доступ к информации о памяти
            vram_gb = 4.0  # Эвристика для Apple Silicon

        ram_gb = psutil.virtual_memory().total / (1024 ** 3)

        return {
            'has_cuda': has_cuda,
            'has_mps': has_mps,
            'vram_gb': vram_gb,
            'ram_gb': ram_gb,
            'device': 'cuda' if has_cuda else ('mps' if has_mps else 'cpu')
        }

    def load_model(self,
                   model_name: str,
                   model_size_gb: float,
                   task_type: str,
                   force_strategy: Optional[str] = None) -> Tuple[Any, str]:
        """
        Загрузка модели с автоматическим выбором стратегии.

        Args:
            model_name: Имя модели (Hugging Face ID или локальный путь)
            model_size_gb: Ожидаемый размер модели в ГБ
            task_type: Тип задачи
            force_strategy: Принудительная стратегия ('local', 'hybrid', 'cloud')

        Returns:
            Кортеж (модель_или_клиент, стратегия_загрузки)
        """
        # Определение стратегии
        strategy = force_strategy or self._select_strategy(model_size_gb)
        self._log(f"Выбрана стратегия загрузки '{strategy}' для модели {model_name} ({model_size_gb} ГБ)")

        if strategy == 'local':
            return self._load_local(model_name, task_type), 'local'
        elif strategy == 'hybrid':
            return self._load_hybrid(model_name, task_type), 'hybrid'
        else:  # cloud
            return self._load_cloud(model_name, task_type), 'cloud'

    def _select_strategy(self, model_size_gb: float) -> str:
        """Выбор стратегии загрузки на основе доступных ресурсов"""
        vram = self.device_info['vram_gb']
        ram = self.device_info['ram_gb']

        # Полная локальная загрузка при достаточной памяти
        if vram >= 8.0 or (vram == 0 and ram >= 16.0 and model_size_gb <= ram * 0.6):
            return 'local'

        # Гибридная загрузка при средних ресурсах
        if vram >= 4.0 or (vram == 0 and ram >= 8.0):
            return 'hybrid'

        # Облачная загрузка при ограниченных ресурсах
        return 'cloud'

    def _load_local(self, model_name: str, task_type: str) -> Any:
        """Полная локальная загрузка модели"""
        self._log(f"Локальная загрузка модели {model_name}")

        # Проверка наличия локальной копии
        local_path = self.local_models_dir / model_name.replace('/', '_')
        if local_path.exists():
            model_path = str(local_path)
        else:
            model_path = model_name  # Загрузка напрямую из Hugging Face

        if task_type == 'text_generation':
            tokenizer = AutoTokenizer.from_pretrained(model_path)
            model = AutoModel.from_pretrained(model_path)
            if self.device_info['device'] != 'cpu':
                model.to(self.device_info['device'])
            return {'model': model, 'tokenizer': tokenizer}
        else:
            # Другие типы задач...
            return AutoModel.from_pretrained(model_path)

    def _load_hybrid(self, model_name: str, task_type: str) -> Any:
        """
        Гибридная загрузка: базовые слои локально, тяжелые операции в облаке.
        Для упрощения примера используем локальную загрузку с квантизацией.
        """
        self._log(f"Гибридная загрузка модели {model_name} (квантизация int8)")

        # Загрузка с квантизацией для экономии памяти
        if task_type == 'text_generation':
            from transformers import BitsAndBytesConfig
            quantization_config = BitsAndBytesConfig(load_in_8bit=True)

            tokenizer = AutoTokenizer.from_pretrained(model_name)
            model = AutoModel.from_pretrained(
                model_name,
                quantization_config=quantization_config,
                device_map="auto"
            )
            return {'model': model, 'tokenizer': tokenizer, 'hybrid_mode': True}
        else:
            # Для других типов задач используем стандартную загрузку с квантизацией
            return AutoModel.from_pretrained(model_name, load_in_8bit=True)

    def _load_cloud(self, model_name: str, task_type: str) -> Any:
        """Облачная загрузка через Hugging Face Inference API"""
        self._log(f"Облачная загрузка модели {model_name} через Hugging Face API")

        api_key = os.environ.get(self.cloud_providers['huggingface']['api_key_env'])
        if not api_key:
            raise ValueError("Требуется HUGGINGFACE_API_KEY для облачной загрузки")

        # Возвращаем клиент для облачных запросов
        return CloudModelClient(
            model_name=model_name,
            api_url=self.cloud_providers['huggingface']['api_url'],
            api_key=api_key,
            task_type=task_type
        )

    def _log(self, message: str, level: str = 'INFO'):
        timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
        print(f"[{timestamp}] [HybridModelLoader] [{level}] {message}")


class CloudModelClient:
    """Клиент для работы с облачными моделями"""

    def __init__(self, model_name: str, api_url: str, api_key: str, task_type: str):
        self.model_name = model_name
        self.api_url = f"{api_url}/{model_name}"
        self.api_key = api_key
        self.task_type = task_type
        self.headers = {"Authorization": f"Bearer {api_key}"}

    def generate(self, prompt: str, **kwargs) -> str:
        """Генерация текста через облачный API"""
        payload = {
            "inputs": prompt,
            "parameters": kwargs
        }

        response = requests.post(self.api_url, headers=self.headers, json=payload)
        response.raise_for_status()

        result = response.json()
        return result[0]['generated_text'] if isinstance(result, list) else result.get('generated_text', '')

    def __call__(self, *args, **kwargs):
        """Поддержка вызова как функции"""
        return self.generate(*args, **kwargs)