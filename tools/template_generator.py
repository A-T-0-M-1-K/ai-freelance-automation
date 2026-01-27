# tools/template_generator.py
"""
Template Generator — инструмент для динамической генерации текстовых шаблонов
на основе JSON-конфигураций и переменных контекста.

Поддерживает:
- Шаблоны проектов (transcription, translation, copywriting и др.)
- Шаблоны email, отчётов, ответов клиентам
- Расширение через пользовательские шаблоны
- Безопасную подстановку переменных (защита от injection)

Использует шаблоны из директории `templates/`.
"""

import json
import logging
import os
from pathlib import Path
from string import Template
from typing import Any, Dict, Optional, Union

# Используем абсолютные пути относительно корня проекта
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
TEMPLATES_DIR = PROJECT_ROOT / "templates"
LOGS_DIR = PROJECT_ROOT / "logs" / "app"

# Настройка логгера
logger = logging.getLogger("TemplateGenerator")
if not logger.handlers:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(LOGS_DIR / "application.log")
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


class TemplateGenerator:
    """
    Генератор шаблонов на основе безопасной подстановки переменных.
    Поддерживает как .txt, так и .json шаблоны.
    """

    def __init__(self, templates_root: Optional[Union[str, Path]] = None):
        self.templates_root = Path(templates_root) if templates_root else TEMPLATES_DIR
        if not self.templates_root.exists():
            raise FileNotFoundError(f"Templates directory not found: {self.templates_root}")
        logger.info(f"Intialized TemplateGenerator with root: {self.templates_root}")

    def _load_template_file(self, template_path: Path) -> str:
        """Загружает содержимое шаблонного файла."""
        try:
            with open(template_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            logger.error(f"Failed to load template file '{template_path}': {e}")
            raise ValueError(f"Cannot load template: {template_path}") from e

    def _render_string_template(self, template_str: str, context: Dict[str, Any]) -> str:
        """Рендерит строковый шаблон с использованием string.Template (безопасно)."""
        try:
            # Экранируем потенциально опасные символы в значениях
            safe_context = {
                k: str(v).replace("$", "$$") if isinstance(v, str) else v
                for k, v in context.items()
            }
            template = Template(template_str)
            return template.safe_substitute(safe_context)
        except Exception as e:
            logger.error(f"Template rendering failed with context {context}: {e}")
            raise ValueError("Template rendering error") from e

    def generate(
        self,
        category: str,
        template_name: str,
        context: Dict[str, Any],
        output_format: str = "text"
    ) -> Union[str, Dict[str, Any]]:
        """
        Генерирует шаблон по категории и имени.

        Args:
            category (str): Категория шаблона (например: 'project', 'email', 'response')
            template_name (str): Имя шаблона без расширения (например: 'transcription_template')
            context (dict): Контекст для подстановки
            output_format (str): 'text' или 'json'

        Returns:
            str или dict — результат рендеринга

        Raises:
            FileNotFoundError: если шаблон не найден
            ValueError: при ошибках рендеринга
        """
        if output_format not in ("text", "json"):
            raise ValueError("output_format must be 'text' or 'json'")

        extension = ".json" if output_format == "json" else ".txt"
        template_path = self.templates_root / category / f"{template_name}{extension}"

        if not template_path.exists():
            logger.warning(f"Template not found: {template_path}")
            raise FileNotFoundError(f"Template '{template_name}' in category '{category}' not found.")

        raw_content = self._load_template_file(template_path)

        if output_format == "json":
            try:
                # Сначала рендерим как строку, затем парсим JSON
                rendered_str = self._render_string_template(raw_content, context)
                return json.loads(rendered_str)
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON after rendering template {template_path}: {e}")
                raise ValueError("Rendered template is not valid JSON") from e
        else:
            return self._render_string_template(raw_content, context)

    def list_available_templates(self, category: str) -> list:
        """Возвращает список доступных шаблонов в категории."""
        category_path = self.templates_root / category
        if not category_path.exists():
            return []
        files = category_path.glob("*")
        return sorted([f.stem for f in files if f.is_file() and f.suffix in ('.txt', '.json')])


# Утилита для быстрого использования
def generate_template(
    category: str,
    template_name: str,
    context: Dict[str, Any],
    output_format: str = "text"
) -> Union[str, Dict[str, Any]]:
    """
    Удобная функция-обёртка для генерации шаблона без создания экземпляра.
    """
    generator = TemplateGenerator()
    return generator.generate(category, template_name, context, output_format)


# Пример использования (не запускается при импорте)
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        result = generate_template(
            category="response",
            template_name="bid",
            context={"client_name": "Алексей", "service": "транскрибация", "price": "1500 руб."},
            output_format="text"
        )
        print("Сгенерированный шаблон:")
        print(result)
    except Exception as e:
        logger.exception("Ошибка при тестовой генерации шаблона")