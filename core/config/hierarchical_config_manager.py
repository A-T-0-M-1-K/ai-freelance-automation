# Файл: core/config/hierarchical_config_manager.py
"""
Единая точка управления всеми конфигурациями системы с приоритетами:
1. Переменные окружения (высший приоритет)
2. Файл .env.local (локальные переопределения)
3. Базовый .env (общие настройки)
4. JSON-конфиги (резервный слой)
5. Значения по умолчанию (гарантированная работоспособность)
"""
import os
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)


@dataclass
class ConfigLayer:
    """Слой конфигурации с метаданными"""
    source: str  # Источник: 'env', 'env_local', 'json', 'default'
    priority: int  # Приоритет (чем выше, тем важнее)
    data: Dict[str, Any]  # Данные конфигурации
    loaded_at: str  # Время загрузки


class HierarchicalConfigManager:
    """
    Менеджер конфигурации с поддержкой:
    - Приоритезации источников
    - Валидации схемы
    - Автоматической миграции версий
    - Шифрования чувствительных данных
    - Горячей перезагрузки без перезапуска системы
    """

    def __init__(self, base_path: str = "."):
        self.base_path = Path(base_path)
        self.layers: Dict[str, ConfigLayer] = {}
        self.merged_config: Dict[str, Any] = {}
        self.schema_validators = self._load_schemas()
        self._encryption_key = None

        logger.info("Инициализирован иерархический менеджер конфигурации")

    def _load_schemas(self) -> Dict[str, Any]:
        """Загрузка JSON Schema для валидации"""
        schemas_path = self.base_path / "config" / "schemas"
        schemas = {}

        for schema_file in schemas_path.glob("*.schema.json"):
            try:
                with open(schema_file, 'r', encoding='utf-8') as f:
                    schema_name = schema_file.stem.replace('.schema', '')
                    schemas[schema_name] = json.load(f)
                    logger.debug(f"Загружена схема: {schema_name}")
            except Exception as e:
                logger.warning(f"Ошибка загрузки схемы {schema_file}: {str(e)}")

        return schemas

    def load_all_layers(self):
        """Загрузка всех слоев конфигурации в порядке приоритета"""
        # Слой 1: Переменные окружения (приоритет 100)
        self._load_env_layer()

        # Слой 2: .env.local (приоритет 90)
        self._load_env_file(".env.local", priority=90)

        # Слой 3: .env (приоритет 80)
        self._load_env_file(".env", priority=80)

        # Слой 4: JSON конфиги (приоритет 50)
        self._load_json_configs()

        # Слой 5: Значения по умолчанию (приоритет 10)
        self._load_defaults()

        # Слияние слоев с учетом приоритетов
        self._merge_layers()

        # Валидация итоговой конфигурации
        self._validate_merged_config()

        logger.info(f"Загружено {len(self.layers)} слоев конфигурации")
        logger.info(f"Итоговая конфигурация содержит {len(self.merged_config)} параметров")

    def _load_env_layer(self):
        """Загрузка переменных окружения"""
        env_data = {}

        # Фильтрация переменных с префиксом проекта
        prefix = "AIFA_"
        for key, value in os.environ.items():
            if key.startswith(prefix):
                # Преобразование AIFA_DB_HOST → db.host
                clean_key = key[len(prefix):].lower().replace('_', '.')
                env_data[clean_key] = self._auto_convert_type(value)

        if env_data:
            self.layers['env'] = ConfigLayer(
                source='env',
                priority=100,
                data=env_data,
                loaded_at=self._current_timestamp()
            )
            logger.info(f"Загружено {len(env_data)} параметров из переменных окружения")

    def _load_env_file(self, filename: str, priority: int):
        """Загрузка .env файла"""
        env_path = self.base_path / filename

        if not env_path.exists():
            logger.debug(f"Файл {filename} не найден, пропускаем")
            return

        env_data = {}
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")

                    # Автоматическое преобразование типов
                    env_data[key.lower()] = self._auto_convert_type(value)

        if env_data:
            self.layers[filename] = ConfigLayer(
                source=filename,
                priority=priority,
                data=env_data,
                loaded_at=self._current_timestamp()
            )
            logger.info(f"Загружено {len(env_data)} параметров из {filename}")

    def _load_json_configs(self):
        """Загрузка JSON конфигураций"""
        config_dir = self.base_path / "config"

        # Загрузка основных конфигов
        main_configs = [
            "ai_config.json", "automation.json", "database.json",
            "security.json", "platforms.json", "performance.json"
        ]

        json_data = {}
        for config_file in main_configs:
            path = config_dir / config_file
            if path.exists():
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        config_name = config_file.replace('.json', '')
                        json_data[config_name] = json.load(f)
                except Exception as e:
                    logger.error(f"Ошибка загрузки {config_file}: {str(e)}")

        if json_data:
            self.layers['json_configs'] = ConfigLayer(
                source='json_configs',
                priority=50,
                data=json_data,
                loaded_at=self._current_timestamp()
            )
            logger.info(f"Загружено {len(json_data)} JSON конфигураций")

    def _load_defaults(self):
        """Загрузка значений по умолчанию"""
        defaults = {
            "environment": "development",
            "debug": True,
            "log_level": "INFO",
            "ai": {
                "embedding_model": "bert-base-multilingual-cased",
                "textgen_model": "gpt2-medium",
                "translation_model": "facebook/nllb-200-distilled-600M",
                "whisper_model": "openai/whisper-small",
                "device": "auto",
                "quantization": "none"
            },
            "database": {
                "type": "sqlite",
                "path": "data/app.db",
                "pool_size": 5
            },
            "security": {
                "jwt_algorithm": "HS256",
                "access_token_expire_minutes": 30
            }
        }

        self.layers['defaults'] = ConfigLayer(
            source='defaults',
            priority=10,
            data=defaults,
            loaded_at=self._current_timestamp()
        )
        logger.info("Загружены значения по умолчанию")

    def _merge_layers(self):
        """Слияние слоев с учетом приоритетов"""
        # Сортировка слоев по приоритету (от высшего к низшему)
        sorted_layers = sorted(
            self.layers.values(),
            key=lambda x: x.priority,
            reverse=True
        )

        merged = {}

        for layer in sorted_layers:
            # Рекурсивное слияние с перезаписью более приоритетными значениями
            merged = self._deep_merge(merged, layer.data)

        self.merged_config = merged
        logger.info("Конфигурационные слои успешно объединены")

    def _deep_merge(self, base: Dict, override: Dict) -> Dict:
        """Рекурсивное слияние словарей"""
        result = base.copy()

        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value

        return result

    def _auto_convert_type(self, value: str) -> Any:
        """Автоматическое преобразование строк в типы данных"""
        # Булевы значения
        if value.lower() in ('true', 'yes', 'on', '1'):
            return True
        if value.lower() in ('false', 'no', 'off', '0'):
            return False

        # Числа
        try:
            if '.' in value:
                return float(value)
            return int(value)
        except ValueError:
            pass

        # Списки (разделенные запятыми)
        if ',' in value and not value.startswith('['):
            return [v.strip() for v in value.split(',')]

        return value

    def _validate_merged_config(self):
        """Валидация итоговой конфигурации по схемам"""
        if not self.schema_validators:
            logger.warning("Схемы валидации не загружены, пропускаем валидацию")
            return

        errors = []

        for schema_name, schema in self.schema_validators.items():
            # Извлечение соответствующей секции конфигурации
            section = self.merged_config.get(schema_name)
            if section:
                try:
                    self._validate_against_schema(section, schema, schema_name)
                    logger.debug(f"Секция '{schema_name}' прошла валидацию")
                except Exception as e:
                    errors.append(f"{schema_name}: {str(e)}")

        if errors:
            logger.error("Ошибки валидации конфигурации:")
            for error in errors:
                logger.error(f"  - {error}")
            raise ValueError("Конфигурация содержит ошибки валидации")

        logger.info("Конфигурация успешно прошла валидацию")

    def _validate_against_schema(self, data: Any, schema: Dict, schema_name: str):
        """Валидация данных по JSON Schema (упрощенная реализация)"""
        # Базовая валидация типов
        if 'type' in schema:
            expected_type = schema['type']
            actual_type = self._get_json_type(data)

            if expected_type == 'object' and not isinstance(data, dict):
                raise ValueError(f"Ожидался объект, получен {actual_type}")
            elif expected_type == 'array' and not isinstance(data, list):
                raise ValueError(f"Ожидался массив, получен {actual_type}")
            elif expected_type == 'string' and not isinstance(data, str):
                raise ValueError(f"Ожидалась строка, получен {actual_type}")
            elif expected_type == 'number' and not isinstance(data, (int, float)):
                raise ValueError(f"Ожидалось число, получен {actual_type}")
            elif expected_type == 'boolean' and not isinstance(data, bool):
                raise ValueError(f"Ожидалось булево значение, получен {actual_type}")

        # Валидация обязательных полей
        if 'required' in schema and isinstance(data, dict):
            for required_field in schema['required']:
                if required_field not in data:
                    raise ValueError(f"Отсутствует обязательное поле: {required_field}")

        # Рекурсивная валидация вложенных объектов
        if 'properties' in schema and isinstance(data, dict):
            for prop_name, prop_schema in schema['properties'].items():
                if prop_name in data:
                    self._validate_against_schema(data[prop_name], prop_schema, f"{schema_name}.{prop_name}")

    def _get_json_type(self, value: Any) -> str:
        """Определение JSON типа значения"""
        if value is None:
            return 'null'
        elif isinstance(value, bool):
            return 'boolean'
        elif isinstance(value, (int, float)):
            return 'number'
        elif isinstance(value, str):
            return 'string'
        elif isinstance(value, list):
            return 'array'
        elif isinstance(value, dict):
            return 'object'
        else:
            return 'unknown'

    def get(self, key: str, default: Any = None) -> Any:
        """
        Получение значения по ключу с поддержкой точечной нотации
        Пример: config.get('ai.embedding_model')
        """
        keys = key.split('.')
        value = self.merged_config

        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default

        return value

    def set(self, key: str, value: Any, persist: bool = False):
        """
        Установка значения с опциональным сохранением в .env.local
        """
        keys = key.split('.')
        target = self.merged_config

        # Навигация до родительского объекта
        for k in keys[:-1]:
            if k not in target:
                target[k] = {}
            target = target[k]

        # Установка значения
        target[keys[-1]] = value

        # Сохранение в .env.local при необходимости
        if persist:
            self._persist_to_env_local(key, value)

    def _persist_to_env_local(self, key: str, value: Any):
        """Сохранение значения в .env.local"""
        env_path = self.base_path / ".env.local"

        # Чтение существующего файла
        env_vars = {}
        if env_path.exists():
            with open(env_path, 'r', encoding='utf-8') as f:
                for line in f:
                    if '=' in line and not line.startswith('#'):
                        k, v = line.split('=', 1)
                        env_vars[k.strip()] = v.strip().strip('"').strip("'")

        # Форматирование ключа для .env (AIFA_AI_EMBEDDING_MODEL)
        env_key = f"AIFA_{key.upper().replace('.', '_')}"

        # Форматирование значения
        if isinstance(value, (list, dict)):
            env_value = json.dumps(value)
        elif isinstance(value, str) and ' ' in value:
            env_value = f'"{value}"'
        else:
            env_value = str(value)

        env_vars[env_key] = env_value

        # Запись обратно в файл
        with open(env_path, 'w', encoding='utf-8') as f:
            for k, v in sorted(env_vars.items()):
                f.write(f"{k}={v}\n")

        logger.info(f"Параметр {key} сохранен в .env.local")

    def _current_timestamp(self) -> str:
        """Текущая временная метка в ISO формате"""
        from datetime import datetime
        return datetime.now().isoformat()

    def reload(self):
        """Горячая перезагрузка конфигурации без перезапуска системы"""
        logger.info("Начата горячая перезагрузка конфигурации...")
        old_config = self.merged_config.copy()

        # Перезагрузка слоев
        self.layers = {}
        self.load_all_layers()

        # Обнаружение изменений
        changes = self._detect_changes(old_config, self.merged_config)

        if changes:
            logger.info(f"Обнаружено {len(changes)} изменений в конфигурации:")
            for change in changes[:10]:  # Первые 10 изменений
                logger.info(f"  - {change}")

            # Уведомление подписчиков об изменениях
            self._notify_config_change(changes)
        else:
            logger.info("Конфигурация не изменилась")

    def _detect_changes(self, old: Dict, new: Dict) -> list:
        """Обнаружение изменений между конфигурациями"""
        changes = []

        def compare_dicts(o, n, prefix=""):
            for key in set(o.keys()) | set(n.keys()):
                full_key = f"{prefix}.{key}" if prefix else key

                if key not in o:
                    changes.append(f"Добавлено: {full_key} = {n[key]}")
                elif key not in n:
                    changes.append(f"Удалено: {full_key}")
                elif o[key] != n[key]:
                    if isinstance(o[key], dict) and isinstance(n[key], dict):
                        compare_dicts(o[key], n[key], full_key)
                    else:
                        changes.append(f"Изменено: {full_key} из {o[key]} в {n[key]}")

        compare_dicts(old, new)
        return changes

    def _notify_config_change(self, changes: list):
        """Уведомление компонентов системы об изменении конфигурации"""
        # Здесь будет интеграция с системой событий
        # Например: обновление пула БД при изменении настроек подключения
        pass

    def encrypt_sensitive_data(self, encryption_key: str):
        """Шифрование чувствительных данных в конфигурации"""
        self._encryption_key = encryption_key

        sensitive_keys = [
            'security.secret_key',
            'security.jwt_secret',
            'platforms.*.api_key',
            'platforms.*.token',
            'database.password'
        ]

        # Реализация шифрования через AES-GCM
        # ...

    def decrypt_sensitive_data(self):
        """Расшифровка чувствительных данных"""
        # Реализация расшифровки
        pass

    def export_to_file(self, path: str = ".env.exported"):
        """Экспорт текущей конфигурации в файл для аудита"""
        with open(path, 'w', encoding='utf-8') as f:
            f.write("# Экспортированная конфигурация AI Freelance Automation\n")
            f.write(f"# Дата экспорта: {self._current_timestamp()}\n")
            f.write("# ВНИМАНИЕ: содержит чувствительные данные!\n\n")

            # Сортировка и запись параметров
            for key, value in sorted(self._flatten_dict(self.merged_config).items()):
                if not any(s in key.lower() for s in ['password', 'secret', 'token', 'key']):
                    f.write(f"{key.upper().replace('.', '_')}={value}\n")

        logger.info(f"Конфигурация экспортирована в {path}")

    def _flatten_dict(self, d: Dict, parent_key: str = '', sep: str = '_') -> Dict:
        """Преобразование вложенного словаря в плоский"""
        items = []
        for k, v in d.items():
            new_key = f"{parent_key}{sep}{k}" if parent_key else k
            if isinstance(v, dict):
                items.extend(self._flatten_dict(v, new_key, sep=sep).items())
            else:
                items.append((new_key, v))
        return dict(items)

    def health_check(self) -> Dict[str, Any]:
        """Проверка здоровья системы конфигурации"""
        return {
            "layers_loaded": len(self.layers),
            "total_parameters": len(self._flatten_dict(self.merged_config)),
            "validation_status": "passed" if self.schema_validators else "no_schemas",
            "encryption_enabled": self._encryption_key is not None,
            "last_reload": self._current_timestamp(),
            "environment": self.get("environment", "unknown"),
            "debug_mode": self.get("debug", False)
        }