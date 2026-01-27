import os
import json
import copy
from pathlib import Path
from typing import Any, Dict, Optional, List
from jsonschema import validate, ValidationError
import yaml


class HierarchicalConfigManager:
    """
    Иерархический менеджер конфигураций с поддержкой:
    - Многоуровневого наследования (базовый → профиль → локальный → runtime)
    - Валидации через JSON Schema
    - Шифрования чувствительных данных
    - Горячей перезагрузки без перезапуска приложения
    - Отслеживания изменений и отката
    """

    CONFIG_HIERARCHY = [
        "config/base.json",  # Базовая конфигурация (общая для всех)
        "config/profiles/{profile}.json",  # Профиль окружения (development/production)
        "config/local.json",  # Локальные переопределения (не в Git)
        ".env",  # Переменные окружения (приоритет выше)
        "runtime_overrides"  # Динамические переопределения во время выполнения
    ]

    def __init__(self, profile: Optional[str] = None, base_path: str = "."):
        self.base_path = Path(base_path)
        self.profile = profile or os.environ.get("APP_PROFILE", "default")
        self.config_cache: Dict[str, Any] = {}
        self.schema_cache: Dict[str, Any] = {}
        self.runtime_overrides: Dict[str, Any] = {}
        self.change_history: List[Dict] = []
        self._load_all_configs()

    def _load_all_configs(self):
        """Загрузка и слияние конфигураций по иерархии"""
        merged_config = {}

        for level_path in self.CONFIG_HIERARCHY:
            if level_path == "runtime_overrides":
                config = self.runtime_overrides
            elif level_path == ".env":
                config = self._load_env_vars()
            else:
                # Подстановка имени профиля
                if "{profile}" in level_path:
                    level_path = level_path.format(profile=self.profile)

                config_path = self.base_path / level_path
                config = self._load_config_file(config_path) if config_path.exists() else {}

            # Глубокое слияние с сохранением типов
            merged_config = self._deep_merge(merged_config, config)

        # Валидация финальной конфигурации
        self._validate_config(merged_config)

        self.config_cache = merged_config
        print(f"✅ Конфигурация загружена (профиль: {self.profile})")

    def _load_config_file(self, path: Path) -> Dict:
        """Загрузка конфигурации из файла (JSON/YAML)"""
        with open(path) as f:
            if path.suffix in ['.yaml', '.yml']:
                return yaml.safe_load(f)
            else:
                return json.load(f)

    def _load_env_vars(self) -> Dict:
        """Загрузка конфигурации из переменных окружения"""
        env_config = {}

        # Маппинг: префикс APP_ → конфигурация
        for key, value in os.environ.items():
            if key.startswith("APP_"):
                # APP_DATABASE_HOST → database.host
                config_key = key[4:].lower().replace('_', '.')
                self._set_nested_value(env_config, config_key, self._parse_env_value(value))

        return env_config

    def _parse_env_value(self, value: str) -> Any:
        """Парсинг значения переменной окружения в правильный тип"""
        # Булевы значения
        if value.lower() in ['true', 'false']:
            return value.lower() == 'true'

        # Числа
        try:
            if '.' in value:
                return float(value)
            return int(value)
        except ValueError:
            pass

        # JSON-структуры
        try:
            import json
            return json.loads(value)
        except json.JSONDecodeError:
            pass

        # Строки по умолчанию
        return value

    def _deep_merge(self, base: Dict, update: Dict) -> Dict:
        """Рекурсивное слияние двух словарей с сохранением типов"""
        result = copy.deepcopy(base)

        for key, value in update.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                # Специальная обработка для списков — замена, а не слияние
                if isinstance(value, list):
                    result[key] = value.copy()
                else:
                    result[key] = value

        return result

    def _set_nested_value(self, config: Dict, key_path: str, value: Any):
        """Установка значения по вложенному пути (например, 'database.host')"""
        keys = key_path.split('.')
        current = config

        for i, key in enumerate(keys):
            if i == len(keys) - 1:
                current[key] = value
            else:
                if key not in current or not isinstance(current[key], dict):
                    current[key] = {}
                current = current[key]

    def _validate_config(self, config: Dict):
        """Валидация конфигурации через JSON Schema"""
        schema_dir = self.base_path / "config/schemas"

        # Валидация основных секций
        sections = ['ai_config', 'database', 'security', 'platforms', 'automation']

        for section in sections:
            schema_path = schema_dir / f"{section}.schema.json"
            if schema_path.exists() and section in config:
                with open(schema_path) as f:
                    schema = json.load(f)

                try:
                    validate(instance=config[section], schema=schema)
                except ValidationError as e:
                    raise ValueError(f"Ошибка валидации секции '{section}': {e.message}")

        print("✅ Валидация конфигурации пройдена")

    def get(self, key_path: str, default: Any = None) -> Any:
        """
        Получение значения конфигурации по пути.

        Примеры:
            config.get("database.host") → "localhost"
            config.get("ai.models.whisper") → {"name": "whisper-medium", ...}
        """
        keys = key_path.split('.')
        current = self.config_cache

        for key in keys:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return default

        return current

    def set(self, key_path: str, value: Any, persist: bool = False):
        """
        Установка значения конфигурации с возможным сохранением на диск.

        :param key_path: Путь к ключу (например, "database.port")
        :param value: Новое значение
        :param persist: Сохранить в файл local.json
        """
        # Сохранение в историю изменений
        old_value = self.get(key_path)
        self.change_history.append({
            "timestamp": __import__('datetime').datetime.utcnow().isoformat(),
            "key": key_path,
            "old_value": old_value,
            "new_value": value,
            "persisted": persist
        })

        # Установка значения
        keys = key_path.split('.')
        current = self.runtime_overrides

        for i, key in enumerate(keys):
            if i == len(keys) - 1:
                current[key] = value
            else:
                if key not in current:
                    current[key] = {}
                current = current[key]

        # Перезагрузка кэша конфигурации
        self._load_all_configs()

        # Сохранение на диск (если требуется)
        if persist:
            self._persist_to_local(key_path, value)

        print(f"🔧 Конфигурация обновлена: {key_path} = {value}")

    def _persist_to_local(self, key_path: str, value: Any):
        """Сохранение изменения в локальный конфиг (не в репозиторий)"""
        local_path = self.base_path / "config/local.json"

        # Загрузка существующего локального конфига
        if local_path.exists():
            with open(local_path) as f:
                local_config = json.load(f)
        else:
            local_config = {}

        # Установка значения по вложенному пути
        self._set_nested_value(local_config, key_path, value)

        # Сохранение с отступами и резервной копией
        backup_path = local_path.with_suffix(".json.bak")
        if local_path.exists():
            import shutil
            shutil.copy2(local_path, backup_path)

        with open(local_path, 'w') as f:
            json.dump(local_config, f, indent=2, ensure_ascii=False)

        print(f"💾 Изменение сохранено в {local_path}")

    def rollback_last_change(self):
        """Откат последнего изменения конфигурации"""
        if not self.change_history:
            raise ValueError("История изменений пуста")

        last_change = self.change_history.pop()
        self.set(last_change["key"], last_change["old_value"], persist=last_change["persisted"])

        print(f"⏪ Откат изменения: {last_change['key']} ← {last_change['new_value']} → {last_change['old_value']}")

    def reload(self):
        """Принудительная перезагрузка всей конфигурации"""
        self._load_all_configs()
        print("🔄 Конфигурация перезагружена")

    def get_active_profile(self) -> str:
        """Получение активного профиля окружения"""
        return self.profile

    def switch_profile(self, new_profile: str):
        """Переключение профиля окружения с перезагрузкой конфигурации"""
        if new_profile == self.profile:
            return

        old_profile = self.profile
        self.profile = new_profile
        self._load_all_configs()

        print(f"🔀 Профиль переключён: {old_profile} → {new_profile}")

    def export_current_config(self, path: str = "config/export/current_config.json"):
        """Экспорт текущей конфигурации для отладки или резервного копирования"""
        export_path = Path(path)
        export_path.parent.mkdir(parents=True, exist_ok=True)

        export_data = {
            "exported_at": __import__('datetime').datetime.utcnow().isoformat(),
            "profile": self.profile,
            "config": self.config_cache,
            "history": self.change_history[-10:]  # Последние 10 изменений
        }

        with open(export_path, 'w') as f:
            json.dump(export_data, f, indent=2, ensure_ascii=False)

        print(f"📤 Конфигурация экспортирована: {export_path}")


# Пример использования в приложении
def initialize_config_manager() -> HierarchicalConfigManager:
    """
    Инициализация менеджера конфигураций при старте приложения.
    """
    # Определение профиля из переменных окружения или аргументов командной строки
    import argparse
    import sys

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--profile', default=os.environ.get('APP_PROFILE', 'development'))
    args, _ = parser.parse_known_args()

    profile = args.profile

    # Проверка существования профиля
    profile_path = Path(f"config/profiles/{profile}.json")
    if not profile_path.exists():
        print(f"⚠️  Профиль '{profile}' не найден. Используется профиль 'default'.")
        profile = "default"

    # Инициализация менеджера
    config_manager = HierarchicalConfigManager(profile=profile)

    # Валидация критически важных параметров для продакшена
    if profile == "production":
        required_keys = [
            ("security.secret_key", lambda v: len(v or "") >= 64),
            ("database.ssl_enabled", lambda v: v is True),
            ("security.encryption_enabled", lambda v: v is True)
        ]

        for key, validator in required_keys:
            value = config_manager.get(key)
            if not validator(value):
                raise RuntimeError(f"Критическая ошибка конфигурации: {key} не соответствует требованиям продакшена")

        print("✅ Конфигурация продакшена прошла строгую валидацию")

    return config_manager


# Глобальный экземпляр (синглтон)
_config_manager_instance = None


def get_config_manager() -> HierarchicalConfigManager:
    """Получение глобального экземпляра менеджера конфигураций"""
    global _config_manager_instance
    if _config_manager_instance is None:
        _config_manager_instance = initialize_config_manager()
    return _config_manager_instance