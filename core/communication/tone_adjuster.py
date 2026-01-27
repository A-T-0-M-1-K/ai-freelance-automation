# AI_FREELANCE_AUTOMATION/core/communication/tone_adjuster.py
"""
Tone Adjuster — модуль для динамической настройки тональности сообщений
в зависимости от контекста, настроения клиента и стратегии общения.

Цели:
- Поддерживать профессиональный, дружелюбный или формальный тон по ситуации.
- Избегать тональных ошибок (например, излишней фамильярности при конфликте).
- Адаптироваться под предпочтения клиента и историю взаимодействия.
- Работать в связке с sentiment_analyzer.py и context_manager.py.

Архитектурные требования:
- Безопасность: не хранит чувствительные данные в памяти дольше необходимого.
- Логирование: все изменения тона логируются для аудита и обучения.
- Расширяемость: поддержка новых стилей через плагины или конфигурацию.
- Отказоустойчивость: при ошибке возвращает нейтральный тон.
"""

import logging
from typing import Dict, Any, Optional, Literal
from pathlib import Path

from core.config.unified_config_manager import UnifiedConfigManager
from core.security.audit_logger import AuditLogger
from core.dependency.service_locator import ServiceLocator

# Типы тональности
ToneStyle = Literal[
    "professional",
    "friendly",
    "formal",
    "empathetic",
    "concise",
    "enthusiastic",
    "neutral"
]

# Уровни уверенности
ConfidenceLevel = Literal["low", "medium", "high"]

class ToneAdjuster:
    """
    Интеллектуальный регулятор тональности сообщений.
    Использует контекст диалога, настроение клиента и бизнес-правила
    для выбора оптимального стиля общения.
    """

    def __init__(self, config_manager: Optional[UnifiedConfigManager] = None):
        self.logger = logging.getLogger("ToneAdjuster")
        self.config_manager = config_manager or ServiceLocator.get("config_manager")
        self.audit_logger = AuditLogger()
        self._load_tone_profiles()

    def _load_tone_profiles(self) -> None:
        """Загружает профили тональности из конфигурации."""
        try:
            tone_config_path = Path("config") / "communication" / "tone_profiles.json"
            if tone_config_path.exists():
                import json
                with open(tone_config_path, "r", encoding="utf-8") as f:
                    self.tone_profiles = json.load(f)
                self.logger.info("✅ Загружены пользовательские профили тональности.")
            else:
                # Встроенные профили по умолчанию
                self.tone_profiles = self._get_default_tone_profiles()
                self.logger.info("ℹ️ Используются встроенные профили тональности.")
        except Exception as e:
            self.logger.error(f"❌ Ошибка загрузки профилей тональности: {e}")
            self.tone_profiles = self._get_default_tone_profiles()

    def _get_default_tone_profiles(self) -> Dict[str, Dict[str, Any]]:
        """Возвращает стандартные профили тональности."""
        return {
            "professional": {
                "formality": 0.8,
                "empathy": 0.5,
                "enthusiasm": 0.3,
                "keywords": ["уважаемый", "благодарю", "готов помочь", "профессионально"],
                "avoid": ["приветик", "чувак", "короче"]
            },
            "friendly": {
                "formality": 0.3,
                "empathy": 0.7,
                "enthusiasm": 0.8,
                "keywords": ["привет!", "супер", "отлично", "давай разберёмся"],
                "avoid": ["уважаемый клиент", "согласно договору"]
            },
            "formal": {
                "formality": 0.95,
                "empathy": 0.2,
                "enthusiasm": 0.1,
                "keywords": ["уважаемый заказчик", "направляю", "прошу подтвердить"],
                "avoid": ["привет", "круто", "ок"]
            },
            "empathetic": {
                "formality": 0.6,
                "empathy": 0.9,
                "enthusiasm": 0.4,
                "keywords": ["понимаю ваше беспокойство", "сожалею", "сделаю всё возможное"],
                "avoid": ["это не моя вина", "вы сами виноваты"]
            },
            "neutral": {
                "formality": 0.5,
                "empathy": 0.4,
                "enthusiasm": 0.2,
                "keywords": ["сообщение", "информация", "данные", "результат"],
                "avoid": []
            }
        }

    def select_tone(
        self,
        client_sentiment: Optional[str] = None,
        conversation_context: Optional[Dict[str, Any]] = None,
        urgency: bool = False,
        client_history: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Выбирает подходящий стиль тональности на основе входных данных.

        Args:
            client_sentiment: 'positive', 'negative', 'neutral'
            conversation_context: метаданные диалога (этап, тип задачи и т.д.)
            urgency: срочность задачи
            client_history: предпочтения клиента (например, любит краткость)

        Returns:
            Словарь с ключами: style (ToneStyle), confidence (ConfidenceLevel), profile (dict)
        """
        try:
            # Базовый стиль — нейтральный
            selected_style: ToneStyle = "neutral"
            confidence: ConfidenceLevel = "low"

            # Приоритет 1: Настроение клиента
            if client_sentiment == "negative":
                selected_style = "empathetic"
                confidence = "high"
            elif client_sentiment == "positive":
                selected_style = "friendly"
                confidence = "medium"

            # Приоритет 2: Контекст (например, этап "переговоры" → formal)
            if conversation_context:
                stage = conversation_context.get("stage")
                job_type = conversation_context.get("job_type")

                if stage == "contract_negotiation":
                    selected_style = "formal"
                    confidence = "high"
                elif stage == "delivery" and job_type == "copywriting":
                    selected_style = "enthusiastic"
                    confidence = "medium"

            # Приоритет 3: История клиента
            if client_history and "preferred_tone" in client_history:
                preferred = client_history["preferred_tone"]
                if preferred in self.tone_profiles:
                    selected_style = preferred
                    confidence = "high"

            # Приоритет 4: Срочность → concise
            if urgency:
                selected_style = "concise"
                # Создаём временный профиль, если его нет
                if "concise" not in self.tone_profiles:
                    self.tone_profiles["concise"] = {
                        "formality": 0.4,
                        "empathy": 0.3,
                        "enthusiasm": 0.1,
                        "keywords": ["кратко", "по делу", "сразу к сути"],
                        "avoid": ["подробно", "давайте обсудим детали"]
                    }

            profile = self.tone_profiles.get(selected_style, self.tone_profiles["neutral"])

            result = {
                "style": selected_style,
                "confidence": confidence,
                "profile": profile
            }

            self.audit_logger.log(
                action="tone_selection",
                details=result,
                severity="info"
            )
            self.logger.debug(f"Выбран тон: {selected_style} (уверенность: {confidence})")

            return result

        except Exception as e:
            self.logger.error(f"Ошибка в select_tone: {e}", exc_info=True)
            # Безопасный fallback
            fallback = {
                "style": "neutral",
                "confidence": "low",
                "profile": self.tone_profiles["neutral"]
            }
            self.audit_logger.log(
                action="tone_selection_fallback",
                details={"error": str(e)},
                severity="warning"
            )
            return fallback

    def adjust_message(
        self,
        message: str,
        target_tone: Dict[str, Any],
        language: str = "ru"
    ) -> str:
        """
        Применяет выбранный тон к сообщению.
        На данный момент использует правило замены ключевых фраз.
        В будущем может использовать fine-tuned LLM.

        Args:
            message: исходное сообщение
            target_tone: результат select_tone()
            language: язык сообщения

        Returns:
            Отредактированное сообщение с нужной тональностью
        """
        try:
            profile = target_tone["profile"]
            adjusted = message

            # Удаление нежелательных слов
            for word in profile.get("avoid", []):
                if word.lower() in adjusted.lower():
                    # Заменяем на нейтральный аналог или удаляем
                    adjusted = adjusted.replace(word, "[...]")
                    self.logger.debug(f"Удалено нежелательное слово: {word}")

            # Добавление характерных фраз (в начало или конец)
            keywords = profile.get("keywords", [])
            if keywords and len(adjusted.split()) > 5:
                # Добавляем только если сообщение достаточно длинное
                intro = keywords[0]
                if not adjusted.startswith(intro):
                    adjusted = f"{intro}. {adjusted}"

            self.logger.debug(f"Сообщение скорректировано под тон '{target_tone['style']}'")
            return adjusted

        except Exception as e:
            self.logger.error(f"Ошибка в adjust_message: {e}", exc_info=True)
            self.audit_logger.log(
                action="message_adjustment_failed",
                details={"original": message, "error": str(e)},
                severity="warning"
            )
            return message  # Возвращаем оригинал при ошибке

# === Инициализация по умолчанию (для DI) ===
def create_tone_adjuster() -> ToneAdjuster:
    """Фабричная функция для внедрения зависимостей."""
    return ToneAdjuster()