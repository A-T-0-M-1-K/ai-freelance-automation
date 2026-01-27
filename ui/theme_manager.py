# ui/theme_manager.py
"""
Theme Manager — управляет темами оформления интерфейса.
Поддерживает встроенные темы, пользовательские JSON-темы и плагины.
Обеспечивает горячую замену тем без перезапуска приложения.
"""

import json
import logging
import os
from pathlib import Path
from typing import Dict, Any, Optional, Union
from threading import Lock

from core.config.unified_config_manager import UnifiedConfigManager
from core.dependency.service_locator import ServiceLocator


class ThemeManager:
    """
    Централизованный менеджер тем оформления.
    Загружает, валидирует, применяет и переключает темы.
    Поддерживает:
      - Встроенные темы (из ui/themes/)
      - Пользовательские темы (из data/settings/custom_themes/)
      - Плагины тем (из plugins/theme_plugins/)
    """

    def __init__(self, config_manager: Optional[UnifiedConfigManager] = None):
        self.logger = logging.getLogger("ThemeManager")
        self._lock = Lock()
        self.config_manager = config_manager or ServiceLocator.get_service("config_manager")
        self._current_theme_name: str = "default"
        self._current_theme: Dict[str, Any] = {}
        self._builtin_theme_dir = Path(__file__).parent / "themes"
        self._custom_theme_dir = Path("data/settings/custom_themes")
        self._ensure_custom_theme_dir()

        # Загрузка начальной темы
        self._load_initial_theme()

    def _ensure_custom_theme_dir(self) -> None:
        """Создаёт директорию для пользовательских тем, если её нет."""
        self._custom_theme_dir.mkdir(parents=True, exist_ok=True)

    def _load_initial_theme(self) -> None:
        """Загружает тему, указанную в конфигурации."""
        try:
            theme_name = self.config_manager.get("ui.theme", default="dark")
            self.set_theme(theme_name)
            self.logger.info(f"✅ Начальная тема загружена: {theme_name}")
        except Exception as e:
            self.logger.warning(f"⚠️ Не удалось загрузить начальную тему: {e}. Используется 'dark'.")
            self.set_theme("dark")

    def list_available_themes(self) -> Dict[str, str]:
        """
        Возвращает словарь доступных тем: {название: источник}.
        Источники: 'builtin', 'custom', 'plugin'
        """
        themes = {}

        # Встроенные темы
        for file in self._builtin_theme_dir.glob("*.json"):
            name = file.stem
            themes[name] = "builtin"

        # Пользовательские темы
        for file in self._custom_theme_dir.glob("*.json"):
            name = file.stem
            themes[name] = "custom"

        # TODO: Интеграция с PluginManager для плагинов тем
        # plugin_manager = ServiceLocator.get_service("plugin_manager", optional=True)
        # if plugin_manager:
        #     for plugin in plugin_manager.get_theme_plugins():
        #         themes[plugin.name] = "plugin"

        return themes

    def get_theme(self, name: str) -> Optional[Dict[str, Any]]:
        """
        Загружает тему по имени из любого источника.
        Возвращает словарь темы или None, если не найдено.
        """
        # 1. Проверяем пользовательские темы
        custom_path = self._custom_theme_dir / f"{name}.json"
        if custom_path.exists():
            return self._load_theme_from_file(custom_path)

        # 2. Проверяем встроенные темы
        builtin_path = self._builtin_theme_dir / f"{name}.json"
        if builtin_path.exists():
            return self._load_theme_from_file(builtin_path)

        # 3. Плагины (в будущем)
        # plugin_manager = ServiceLocator.get_service("plugin_manager", optional=True)
        # if plugin_manager:
        #     theme = plugin_manager.get_theme(name)
        #     if theme:
        #         return theme

        self.logger.warning(f"Тема '{name}' не найдена.")
        return None

    def _load_theme_from_file(self, path: Path) -> Optional[Dict[str, Any]]:
        """Загружает и валидирует тему из JSON-файла."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                theme = json.load(f)
            if not isinstance(theme, dict):
                raise ValueError("Тема должна быть объектом JSON")
            if "name" not in theme:
                theme["name"] = path.stem
            self.logger.debug(f"Тема загружена из {path}")
            return theme
        except Exception as e:
            self.logger.error(f"Ошибка при загрузке темы из {path}: {e}")
            return None

    def set_theme(self, name: str) -> bool:
        """
        Устанавливает текущую тему по имени.
        Возвращает True при успехе, False при ошибке.
        """
        with self._lock:
            theme = self.get_theme(name)
            if theme is None:
                self.logger.error(f"❌ Невозможно установить тему '{name}': не найдена.")
                return False

            self._current_theme = theme
            self._current_theme_name = name

            # Обновляем конфигурацию
            self.config_manager.set("ui.theme", name)
            self.config_manager.save()

            self.logger.info(f"🎨 Тема успешно изменена на: {name}")
            self._notify_ui_about_change()
            return True

    def _notify_ui_about_change(self) -> None:
        """
        Уведомляет UI-компоненты об изменении темы.
        В реальной системе это может вызывать сигналы, события или обновление стилей.
        """
        # Пример: отправка события через EventBus (будет реализовано в UI)
        event_bus = ServiceLocator.get_service("event_bus", optional=True)
        if event_bus:
            event_bus.emit("theme_changed", {"theme": self._current_theme})
        else:
            # Fallback: логируем
            self.logger.debug("UI уведомлён о смене темы (event_bus недоступен)")

    def get_current_theme(self) -> Dict[str, Any]:
        """Возвращает текущую активную тему."""
        return self._current_theme.copy()

    def get_current_theme_name(self) -> str:
        """Возвращает имя текущей темы."""
        return self._current_theme_name

    def save_custom_theme(self, name: str, theme_data: Dict[str, Any]) -> bool:
        """
        Сохраняет пользовательскую тему в файл.
        Перезаписывает существующую, если нужно.
        """
        if not isinstance(theme_data, dict):
            self.logger.error("❌ Данные темы должны быть словарём.")
            return False

        try:
            theme_data["name"] = name
            path = self._custom_theme_dir / f"{name}.json"
            with open(path, "w", encoding="utf-8") as f:
                json.dump(theme_data, f, indent=4, ensure_ascii=False)
            self.logger.info(f"💾 Пользовательская тема сохранена: {name}")
            return True
        except Exception as e:
            self.logger.error(f"❌ Ошибка при сохранении темы '{name}': {e}")
            return False

    def delete_custom_theme(self, name: str) -> bool:
        """Удаляет пользовательскую тему."""
        if name in ("dark", "light", "blue"):  # Защита от удаления встроенных
            self.logger.warning("❌ Нельзя удалить встроенную тему.")
            return False

        path = self._custom_theme_dir / f"{name}.json"
        if not path.exists():
            self.logger.warning(f"Тема '{name}' не существует.")
            return False

        try:
            path.unlink()
            self.logger.info(f"🗑️ Тема '{name}' удалена.")
            return True
        except Exception as e:
            self.logger.error(f"❌ Ошибка при удалении темы '{name}': {e}")
            return False