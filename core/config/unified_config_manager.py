"""
Универсальный менеджер конфигурации с поддержкой:
- Иерархической загрузки (переменные окружения > .env > JSON конфиги > значения по умолчанию)
- Автоматической подстановки секретов из защищенного хранилища
- Валидации по JSON Schema
- Горячей перезагрузки без перезапуска системы
- Обратной совместимости со старыми конфигами
"""
import os
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional, List
from datetime import datetime
import re

from core.security.secret_vault import secret_vault

logger = logging.getLogger(__name__)


class UnifiedConfigManager:
    """
    Единая точка доступа ко всем конфигурациям системы
    """

    def __init__(self, base_path: str = "."):
        self.base_path = Path(base_path)
        self.configs: Dict[str, Any] = {}
        self.layers: Dict[str, Dict] = {}
        self.schema_validators: Dict[str, Any] = {}
        self._encryption_key = None
        self._last_reload = datetime.now()

        # Загрузка всех конфигураций при инициализации
        self._load_schemas()
        self.load_all_configs()

        logger.info("Универсальный менеджер конфигурации инициализирован")

    def _load_schemas(self):
        """Загрузка JSON Schema для валидации"""
        schemas_path = self.base_path / "config" / "schemas"

        if not schemas_path.exists():
            logger.warning(f"Директория схем не найдена: {schemas_path}")
            return

        for schema_file in schemas_path.glob("*.schema.json"):
            try:
                with open(schema_file, 'r', encoding='utf-8') as f:
                    schema_name = schema_file.stem.replace('.schema', '')
                    self.schema_validators[schema_name] = json.load(f)
                    logger.debug(f"Загружена схема: {schema_name}")
            except Exception as e:
                logger.warning(f"Ошибка загрузки схемы {schema_file}: {str(e)}")

    def load_all_configs(self):
        """Полная загрузка всех конфигураций с приоритезацией"""
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

        # Слияние слоев
        self._merge_layers()

        # Автоматическая подстановка секретов
        self._inject_secrets()

        # Валидация
        self._validate_configs()

        self._last_reload = datetime.now()
        logger.info(f"Загружено {len(self.configs)} конфигурационных секций")

    def _load_env_layer(self):
        """Загрузка переменных окружения с префиксом AIFA_"""
        env_data = {}
        prefix = "AIFA_"

        for key, value in os.environ.items():
            if key.startswith(prefix):
                # Преобразование AIFA_DB_HOST → db.host
                clean_key = key[len(prefix):].lower().replace('_', '.')
                env_data[clean_key] = self._auto_convert_type(value)

        if env_data:
            self.layers['env'] = {
                'source': 'env',
                'priority': 100,
                'data': env_data
            }
            logger.debug(f"Загружено {len(env_data)} параметров из переменных окружения")

    def _load_env_file(self, filename: str, priority: int):
        """Загрузка .env файла"""
        env_path = self.base_path / filename

        if not env_path.exists():
            return

        env_data = {}
        try:
            with open(env_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        key = key.strip()
                        value = value.strip().strip('"').strip("'")
                        env_data[key.lower()] = self._auto_convert_type(value)

            if env_data:
                self.layers[filename] = {
                    'source': filename,
                    'priority': priority,
                    'data': env_data
                }
                logger.debug(f"Загружено {len(env_data)} параметров из {filename}")
        except Exception as e:
            logger.error(f"Ошибка загрузки {filename}: {str(e)}")

    def _load_json_configs(self):
        """Загрузка JSON конфигураций"""
        config_dir = self.base_path / "config"
        json_data = {}

        # Список основных конфигов для загрузки
        main_configs = [
            "ai_config.json", "automation.json", "database.json",
            "security.json", "platforms.json", "performance.json",
            "logging.json", "notifications.json", "backup_config.json"
        ]

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
            self.layers['json_configs'] = {
                'source': 'json_configs',
                'priority': 50,
                'data': json_data
            }
            logger.debug(f"Загружено {len(json_data)} JSON конфигураций")

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
                "quantization": "none",
                "cache_enabled": True,
                "max_concurrent_models": 2
            },
            "database": {
                "type": "sqlite",
                "path": "data/app.db",
                "pool_size": 5,
                "echo_sql": False
            },
            "security": {
                "jwt_algorithm": "HS256",
                "access_token_expire_minutes": 30,
                "rate_limit_requests": 100,
                "rate_limit_window": 60
            },
            "platforms": {
                "enabled": ["upwork", "freelance_ru", "kwork"],
                "auto_bid": False,
                "max_bids_per_day": 10
            },
            "performance": {
                "use_disk_cache": True,
                "disk_cache_size_gb": 2.0,
                "memory_limit_gb": 4.0,
                "aggressive_gc": False
            }
        }

        self.layers['defaults'] = {
            'source': 'defaults',
            'priority': 10,
            'data': defaults
        }
        logger.debug("Загружены значения по умолчанию")

    def _merge_layers(self):
        """Слияние всех слоев конфигурации с учетом приоритетов"""
        # Сортировка слоев по приоритету (от высшего к низшему)
        sorted_layers = sorted(
            self.layers.values(),
            key=lambda x: x['priority'],
            reverse=True
        )

        merged = {}

        for layer in sorted_layers:
            # Рекурсивное слияние с перезаписью более приоритетными значениями
            merged = self._deep_merge(merged, layer['data'])

        self.configs = merged

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

    def _inject_secrets(self):
        """Автоматическая подстановка секретов из защищенного хранилища"""
        # Секреты платформ
        if "platforms" in self.configs and isinstance(self.configs["platforms"], dict):
            platforms = self.configs["platforms"]
            for platform_name, config in platforms.items():
                if not isinstance(config, dict):
                    continue

                sensitive_fields = ['api_key', 'token', 'secret', 'password', 'client_secret', 'client_id']
                for field in sensitive_fields:
                    if field in config and config[field] == "***SECRET***":
                        secret_key = f"platform_{platform_name}_{field}"
                        secret_value = secret_vault.get_secret(secret_key)
                        if secret_value:
                            config[field] = secret_value
                            secret_vault.audit_access(secret_key, "config_manager", "inject")
                            logger.debug(f"Подставлен секрет для {platform_name}.{field}")
                        else:
                            logger.warning(f"Секрет {secret_key} не найден в хранилище")

        # Секреты безопасности
        if "security" in self.configs and isinstance(self.configs["security"], dict):
            security = self.configs["security"]
            secret_mapping = {
                'secret_key': 'security_secret_key',
                'jwt_secret': 'security_jwt_secret',
                'encryption_key': 'security_encryption_key',
                'db_password': 'database_password',
                'smtp_password': 'smtp_password'
            }

            for config_key, secret_key in secret_mapping.items():
                if config_key in security and security[config_key] == "***SECRET***":
                    secret_value = secret_vault.get_secret(secret_key)
                    if secret_value:
                        security[config_key] = secret_value
                        secret_vault.audit_access(secret_key, "config_manager", "inject")
                        logger.debug(f"Подставлен секрет {config_key}")

    def _validate_configs(self):
        """Валидация конфигурации по схемам"""
        if not self.schema_validators:
            logger.debug("Схемы валидации не загружены, пропускаем валидацию")
            return

        errors = []

        for schema_name, schema in self.schema_validators.items():
            section = self.configs.get(schema_name)
            if section:
                try:
                    self._validate_section(section, schema, schema_name)
                    logger.debug(f"Секция '{schema_name}' прошла валидацию")
                except Exception as e:
                    errors.append(f"{schema_name}: {str(e)}")

        if errors:
            logger.error("Ошибки валидации конфигурации:")
            for error in errors:
                logger.error(f"  - {error}")
            # Не прерываем работу, но логируем ошибки
            # В продакшене можно добавить: raise ValueError("Конфигурация содержит ошибки валидации")

    def _validate_section(self, data: Any, schema: Dict, section_name: str):
        """Валидация секции конфигурации по схеме"""
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
                    self._validate_section(data[prop_name], prop_schema, f"{section_name}.{prop_name}")

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
        Примеры:
            config.get('ai.embedding_model')
            config.get('database.host')
            config.get('platforms.upwork.api_key')
        """
        keys = key.split('.')
        value = self.configs

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
        target = self.configs

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
            try:
                with open(env_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        if '=' in line and not line.startswith('#'):
                            k, v = line.split('=', 1)
                            env_vars[k.strip()] = v.strip().strip('"').strip("'")
            except Exception as e:
                logger.error(f"Ошибка чтения {env_path}: {str(e)}")

        # Форматирование ключа для .env (AIFA_AI_EMBEDDING_MODEL)
        env_key = f"AIFA_{key.upper().replace('.', '_')}"

        # Форматирование значения
        if isinstance(value, (list, dict)):
            env_value = json.dumps(value)
        elif isinstance(value, str) and re.search(r'\s', value):
            env_value = f'"{value}"'
        else:
            env_value = str(value)

        env_vars[env_key] = env_value

        # Запись обратно в файл
        try:
            with open(env_path, 'w', encoding='utf-8') as f:
                for k, v in sorted(env_vars.items()):
                    f.write(f"{k}={v}\n")
            logger.info(f"Параметр {key} сохранен в .env.local")
        except Exception as e:
            logger.error(f"Ошибка сохранения в .env.local: {str(e)}")

    def reload(self):
        """Горячая перезагрузка конфигурации без перезапуска системы"""
        logger.info("Начата горячая перезагрузка конфигурации...")
        old_configs = self.configs.copy()

        # Перезагрузка слоев
        self.layers = {}
        self.load_all_configs()

        # Обнаружение изменений
        changes = self._detect_changes(old_configs, self.configs)

        if changes:
            logger.info(f"Обнаружено {len(changes)} изменений в конфигурации:")
            for change in changes[:10]:  # Первые 10 изменений
                logger.info(f"  - {change}")
        else:
            logger.info("Конфигурация не изменилась")

        self._last_reload = datetime.now()

    def _detect_changes(self, old: Dict, new: Dict) -> List[str]:
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

    def save(self):
        """Сохранение конфигурации с извлечением секретов"""
        # Извлечение секретов перед сохранением
        self._extract_secrets()

        # Сохранение конфигов
        config_dir = self.base_path / "config"
        for section_name, config_data in self.configs.items():
            if isinstance(config_data, dict):
                path = config_dir / f"{section_name}.json"
                try:
                    with open(path, 'w', encoding='utf-8') as f:
                        json.dump(config_data, f, ensure_ascii=False, indent=2)
                    logger.debug(f"Конфигурация '{section_name}' сохранена в {path}")
                except Exception as e:
                    logger.error(f"Ошибка сохранения {path}: {str(e)}")

        # Возврат секретов после сохранения
        self._inject_secrets()

    def _extract_secrets(self):
        """Извлечение секретов из конфигурации перед сохранением"""
        # Платформы
        if "platforms" in self.configs and isinstance(self.configs["platforms"], dict):
            platforms = self.configs["platforms"]
            for platform_name, config in platforms.items():
                if not isinstance(config, dict):
                    continue

                sensitive_fields = ['api_key', 'token', 'secret', 'password', 'client_secret', 'client_id']
                for field in sensitive_fields:
                    if field in config and config[field] != "***SECRET***":
                        secret_key = f"platform_{platform_name}_{field}"
                        secret_vault.store_secret(secret_key, config[field])
                        config[field] = "***SECRET***"
                        logger.debug(f"Секрет извлечен для {platform_name}.{field}")

        # Безопасность
        if "security" in self.configs and isinstance(self.configs["security"], dict):
            security = self.configs["security"]
            secret_mapping = {
                'secret_key': 'security_secret_key',
                'jwt_secret': 'security_jwt_secret',
                'encryption_key': 'security_encryption_key',
                'db_password': 'database_password',
                'smtp_password': 'smtp_password'
            }

            for config_key, secret_key in secret_mapping.items():
                if config_key in security and security[config_key] != "***SECRET***":
                    secret_vault.store_secret(secret_key, security[config_key])
                    security[config_key] = "***SECRET***"
                    logger.debug(f"Секрет извлечен: {config_key}")

    def health_check(self) -> Dict[str, Any]:
        """Проверка здоровья системы конфигурации"""
        # Подсчет общего количества параметров
        total_params = len(self._flatten_dict(self.configs))

        # Проверка наличия критических секций
        critical_sections = ['ai', 'database', 'security', 'platforms']
        missing_sections = [s for s in critical_sections if s not in self.configs]

        return {
            "status": "healthy" if not missing_sections else "degraded",
            "last_reload": self._last_reload.isoformat(),
            "total_parameters": total_params,
            "config_sections": list(self.configs.keys()),
            "missing_critical_sections": missing_sections,
            "validation_errors": [] if self._is_valid() else ["Требуется проверка валидации"],
            "environment": self.get("environment", "unknown"),
            "debug_mode": self.get("debug", False),
            "secret_vault_status": secret_vault.health_check()
        }

    def _is_valid(self) -> bool:
        """Проверка валидности конфигурации"""
        # Минимальная проверка наличия критических секций
        critical_sections = ['ai', 'database', 'security']
        return all(section in self.configs for section in critical_sections)

    def _flatten_dict(self, d: Dict, parent_key: str = '', sep: str = '.') -> Dict:
        """Преобразование вложенного словаря в плоский"""
        items = []
        for k, v in d.items():
            new_key = f"{parent_key}{sep}{k}" if parent_key else k
            if isinstance(v, dict):
                items.extend(self._flatten_dict(v, new_key, sep=sep).items())
            else:
                items.append((new_key, v))
        return dict(items)

    def export_to_env(self, output_path: str = ".env.exported"):
        """Экспорт текущей конфигурации в .env формат для аудита"""
        flat_config = self._flatten_dict(self.configs)

        # Фильтрация чувствительных данных
        sensitive_patterns = [
            'password', 'secret', 'token', 'key', 'api', 'jwt',
            'private', 'credential', 'auth'
        ]

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write("# Экспортированная конфигурация AI Freelance Automation\n")
            f.write(f"# Дата экспорта: {datetime.now().isoformat()}\n")
            f.write("# ВНИМАНИЕ: содержит чувствительные данные!\n\n")

            for key, value in sorted(flat_config.items()):
                # Пропускаем чувствительные данные
                if any(pattern in key.lower() for pattern in sensitive_patterns):
                    continue

                # Форматирование значения
                if isinstance(value, (list, dict)):
                    env_value = json.dumps(value)
                elif isinstance(value, str) and re.search(r'\s', value):
                    env_value = f'"{value}"'
                else:
                    env_value = str(value)

                env_key = f"AIFA_{key.upper().replace('.', '_')}"
                f.write(f"{env_key}={env_value}\n")

        logger.info(f"Конфигурация экспортирована в {output_path}")


# Глобальный экземпляр для использования в системе
config_manager = UnifiedConfigManager()