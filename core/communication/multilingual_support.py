# AI_FREELANCE_AUTOMATION/core/communication/multilingual_support.py
"""
Модуль поддержки мультиязычности для автономного фрилансера.
Обеспечивает:
- Автоматическое определение языка входящего сообщения
- Перевод сообщений на целевой язык (обычно — язык клиента)
- Генерацию ответов на нужном языке с сохранением тона и стиля
- Поддержку 50+ языков через плагины AI-перевода
- Кэширование часто используемых переводов
- Интеграцию с sentiment_analyzer и tone_adjuster

Архитектурные требования:
- Не зависит от конкретной модели перевода (поддержка OpenAI, Google, local NLLB и др.)
- Работает через service locator или DI (в будущем)
- Безопасен: не логирует персональные данные
- Поддерживает hot-reload языковых конфигураций
"""

import logging
import json
from typing import Optional, Dict, Any, List, Tuple
from pathlib import Path

from core.config.unified_config_manager import UnifiedConfigManager
from core.dependency.service_locator import ServiceLocator
from core.security.audit_logger import AuditLogger
from core.performance.intelligent_cache_system import IntelligentCacheSystem

# Типизированные исключения
class LanguageDetectionError(Exception):
    """Ошибка при определении языка."""
    pass

class TranslationError(Exception):
    """Ошибка при переводе текста."""
    pass

class UnsupportedLanguageError(Exception):
    """Язык не поддерживается системой."""
    pass


class MultilingualSupport:
    """
    Централизованная система мультиязычной поддержки.
    Используется модулями communication, automation, client_service.
    """

    # Поддерживаемые языки (ISO 639-1)
    SUPPORTED_LANGUAGES = {
        'en', 'ru', 'es', 'fr', 'de', 'pt', 'it', 'nl', 'pl', 'uk',
        'tr', 'ar', 'zh', 'ja', 'ko', 'hi', 'bn', 'fa', 'th', 'vi',
        'id', 'ms', 'tl', 'sv', 'no', 'da', 'fi', 'el', 'he', 'cs',
        'sk', 'hu', 'ro', 'bg', 'hr', 'sr', 'sl', 'et', 'lv', 'lt',
        'is', 'mt', 'ga', 'cy', 'eu', 'gl', 'ca', 'eo', 'sw', 'ur'
    }

    def __init__(self, config_manager: Optional[UnifiedConfigManager] = None):
        self.logger = logging.getLogger("MultilingualSupport")
        self.config = config_manager or UnifiedConfigManager()
        self.cache = IntelligentCacheSystem(namespace="multilingual")
        self.audit = AuditLogger()

        # Загрузка настроек
        self._load_language_settings()
        self.logger.info("✅ MultilingualSupport initialized with %d supported languages", len(self.SUPPORTED_LANGUAGES))

    def _load_language_settings(self):
        """Загружает дополнительные настройки из конфигурации."""
        lang_config = self.config.get("communication.multilingual", {})
        custom_langs = lang_config.get("custom_languages", [])
        for lang in custom_langs:
            if isinstance(lang, str) and len(lang) == 2:
                self.SUPPORTED_LANGUAGES.add(lang.lower())
        self.fallback_language = lang_config.get("fallback_language", "en")

    def detect_language(self, text: str) -> str:
        """
        Определяет язык текста с использованием AI-сервиса.
        Возвращает код языка в формате ISO 639-1 (например, 'en', 'ru').

        Raises:
            LanguageDetectionError: если не удалось определить язык
        """
        if not text.strip():
            return self.fallback_language

        cache_key = f"lang_detect:{hash(text)}"
        cached = self.cache.get(cache_key)
        if cached:
            return cached

        try:
            # Получаем сервис перевода через ServiceLocator
            translation_service = ServiceLocator.get_service("translation_service")
            detected_lang = translation_service.detect_language(text)

            if detected_lang not in self.SUPPORTED_LANGUAGES:
                self.logger.warning("⚠️ Detected unsupported language: %s. Falling back to %s", detected_lang, self.fallback_language)
                detected_lang = self.fallback_language

            self.cache.set(cache_key, detected_lang, ttl=3600)
            self.audit.log("language_detection", {"input_hash": hash(text), "detected": detected_lang})
            return detected_lang

        except Exception as e:
            self.logger.error("❌ Language detection failed: %s", e)
            raise LanguageDetectionError(f"Failed to detect language: {e}") from e

    def translate(
        self,
        text: str,
        target_lang: str,
        source_lang: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Переводит текст на целевой язык.
        Если source_lang не указан — определяется автоматически.

        Args:
            text: Исходный текст
            target_lang: Целевой язык (ISO 639-1)
            source_lang: Исходный язык (опционально)
            context: Контекст для улучшения качества перевода (например, стиль, домен)

        Returns:
            Переведённый текст

        Raises:
            UnsupportedLanguageError: если язык не поддерживается
            TranslationError: при ошибке перевода
        """
        if not text.strip():
            return text

        if target_lang not in self.SUPPORTED_LANGUAGES:
            raise UnsupportedLanguageError(f"Target language '{target_lang}' is not supported")

        if source_lang is None:
            source_lang = self.detect_language(text)

        if source_lang == target_lang:
            return text

        cache_key = f"translate:{source_lang}:{target_lang}:{hash(text)}"
        cached = self.cache.get(cache_key)
        if cached:
            return cached

        try:
            translation_service = ServiceLocator.get_service("translation_service")
            translated = translation_service.translate(
                text=text,
                source_lang=source_lang,
                target_lang=target_lang,
                context=context
            )

            self.cache.set(cache_key, translated, ttl=86400)  # кэш на 24 часа
            self.audit.log("translation", {
                "source_lang": source_lang,
                "target_lang": target_lang,
                "text_length": len(text),
                "context_keys": list(context.keys()) if context else []
            })
            return translated

        except Exception as e:
            self.logger.error("❌ Translation failed: %s", e)
            raise TranslationError(f"Translation error: {e}") from e

    def generate_response_in_language(
        self,
        prompt: str,
        target_lang: str,
        style: str = "professional",
        tone: str = "neutral"
    ) -> str:
        """
        Генерирует ответ на заданном языке с учётом стиля и тона.
        Используется для генерации ответов клиенту без предварительного перевода.
        """
        if target_lang not in self.SUPPORTED_LANGUAGES:
            raise UnsupportedLanguageError(f"Generation language '{target_lang}' is not supported")

        # Формируем промпт с указанием языка
        enriched_prompt = (
            f"Respond in {target_lang} language only. "
            f"Style: {style}. Tone: {tone}. "
            f"Content: {prompt}"
        )

        try:
            copywriting_service = ServiceLocator.get_service("copywriting_service")
            response = copywriting_service.generate_text(enriched_prompt, lang=target_lang)
            self.audit.log("response_generation", {
                "target_lang": target_lang,
                "style": style,
                "tone": tone
            })
            return response
        except Exception as e:
            self.logger.error("❌ Response generation failed: %s", e)
            raise TranslationError(f"Response generation error: {e}") from e

    def get_supported_languages(self) -> List[str]:
        """Возвращает список поддерживаемых языков."""
        return sorted(list(self.SUPPORTED_LANGUAGES))

    def is_language_supported(self, lang_code: str) -> bool:
        """Проверяет, поддерживается ли язык."""
        return lang_code.lower() in self.SUPPORTED_LANGUAGES


# Singleton-like доступ (опционально, для совместимости)
_multilingual_instance: Optional[MultilingualSupport] = None

def get_multilingual_support() -> MultilingualSupport:
    """Глобальная точка доступа к экземпляру (для legacy-кода)."""
    global _multilingual_instance
    if _multilingual_instance is None:
        _multilingual_instance = MultilingualSupport()
    return _multilingual_instance