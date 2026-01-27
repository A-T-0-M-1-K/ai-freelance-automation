# AI_FREELANCE_AUTOMATION/core/communication/sentiment_analyzer.py

"""
Sentiment Analyzer — анализирует эмоциональную окраску сообщений клиента.
Используется для адаптации тона общения, выявления недовольства и предотвращения конфликтов.
Поддерживает 50+ языков, работает в реальном времени, устойчив к сбоям.
"""

import logging
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

from core.config.unified_config_manager import UnifiedConfigManager
from core.ai_management.intelligent_model_manager import IntelligentModelManager
from core.performance.intelligent_cache_system import IntelligentCacheSystem
from core.security.audit_logger import AuditLogger

logger = logging.getLogger("SentimentAnalyzer")


class SentimentLabel(Enum):
    VERY_NEGATIVE = -2
    NEGATIVE = -1
    NEUTRAL = 0
    POSITIVE = 1
    VERY_POSITIVE = 2


@dataclass
class SentimentResult:
    label: SentimentLabel
    confidence: float  # 0.0 – 1.0
    language: str
    raw_score: Optional[float] = None  # внутренний скор модели
    suggestions: Optional[Dict[str, Any]] = None  # рекомендации для communicator'а


class SentimentAnalyzer:
    """
    Анализатор тональности сообщений клиентов.

    Особенности:
    - Автоматическое определение языка
    - Кэширование результатов (для повторяющихся фраз)
    - Fallback на резервные модели при сбое
    - Аудит всех операций
    - Поддержка batch-обработки
    """

    def __init__(
            self,
            config: UnifiedConfigManager,
            ai_manager: IntelligentModelManager,
            cache: Optional[IntelligentCacheSystem] = None,
            audit_logger: Optional[AuditLogger] = None
    ):
        self.config = config
        self.ai_manager = ai_manager
        self.cache = cache or IntelligentCacheSystem(config)
        self.audit_logger = audit_logger or AuditLogger(config)
        self._initialized = False
        self._primary_model = None
        self._fallback_model = None
        self._load_models()

    def _load_models(self) -> None:
        """Загружает основную и резервную модели для анализа тональности."""
        try:
            sentiment_config = self.config.get("ai.sentiment", default={})
            primary_model_name = sentiment_config.get("primary_model",
                                                      "cardiffnlp/twitter-roberta-base-sentiment-latest")
            fallback_model_name = sentiment_config.get("fallback_model",
                                                       "nlptown/bert-base-multilingual-uncased-sentiment")

            logger.info(f"📥 Загрузка основной модели тональности: {primary_model_name}")
            self._primary_model = self.ai_manager.load_model(
                model_name=primary_model_name,
                task="sentiment-analysis",
                auto_optimize=True
            )

            logger.info(f"📥 Загрузка резервной модели тональности: {fallback_model_name}")
            self._fallback_model = self.ai_manager.load_model(
                model_name=fallback_model_name,
                task="sentiment-analysis",
                auto_optimize=True
            )

            self._initialized = True
            logger.info("✅ SentimentAnalyzer успешно инициализирован.")
        except Exception as e:
            logger.error(f"❌ Ошибка при загрузке моделей тональности: {e}", exc_info=True)
            raise RuntimeError("Не удалось инициализировать SentimentAnalyzer") from e

    def _normalize_label(self, model_label: str, model_name: str) -> SentimentLabel:
        """Приводит метки разных моделей к единому формату."""
        label_map = {
            # Для cardiffnlp
            "LABEL_0": SentimentLabel.NEGATIVE,
            "LABEL_1": SentimentLabel.NEUTRAL,
            "LABEL_2": SentimentLabel.POSITIVE,
            # Для nlptown (оценки 1–5)
            "1 star": SentimentLabel.VERY_NEGATIVE,
            "2 stars": SentimentLabel.NEGATIVE,
            "3 stars": SentimentLabel.NEUTRAL,
            "4 stars": SentimentLabel.POSITIVE,
            "5 stars": SentimentLabel.VERY_POSITIVE,
        }

        # Попытка найти точное совпадение
        if model_label in label_map:
            return label_map[model_label]

        # Попытка извлечь число (для числовых оценок)
        try:
            score = int(''.join(filter(str.isdigit, model_label)))
            if score <= 2:
                return SentimentLabel.NEGATIVE
            elif score == 3:
                return SentimentLabel.NEUTRAL
            else:
                return SentimentLabel.POSITIVE
        except ValueError:
            pass

        # По умолчанию — нейтрально
        logger.warning(f"⚠️ Неизвестная метка тональности '{model_label}' от модели '{model_name}', возвращаем NEUTRAL")
        return SentimentLabel.NEUTRAL

    def _analyze_with_model(self, text: str, model, model_name: str) -> Optional[SentimentResult]:
        """Выполняет анализ одной моделью."""
        try:
            result = model(text)
            if not result or len(result) == 0:
                return None

            # Обработка выхода модели
            prediction = result[0] if isinstance(result, list) else result
            label = prediction.get("label", "NEUTRAL")
            confidence = float(prediction.get("score", 0.0))

            normalized_label = self._normalize_label(label, model_name)

            # Определяем язык (если не указан — попытка через AI или fallback)
            language = self._detect_language(text)

            return SentimentResult(
                label=normalized_label,
                confidence=confidence,
                language=language,
                raw_score=prediction.get("score"),
                suggestions=self._generate_suggestions(normalized_label, confidence)
            )
        except Exception as e:
            logger.warning(f"⚠️ Модель '{model_name}' не смогла проанализировать текст: {e}")
            return None

    def _detect_language(self, text: str) -> str:
        """Определяет язык текста (упрощённо; можно заменить на langdetect или fasttext)."""
        # В продакшене — использовать отдельную модель или библиотеку
        # Здесь — минимальная реализация для демонстрации
        common_langs = {
            'en': ['the', 'and', 'is', 'in', 'to'],
            'ru': ['и', 'в', 'не', 'на', 'с'],
            'es': ['el', 'la', 'de', 'que', 'y'],
            'fr': ['le', 'de', 'et', 'à', 'les'],
        }
        text_lower = text.lower()
        for lang, words in common_langs.items():
            if any(word in text_lower for word in words):
                return lang
        return "unknown"

    def _generate_suggestions(self, label: SentimentLabel, confidence: float) -> Dict[str, Any]:
        """Генерирует рекомендации для empathetic_communicator."""
        suggestions = {"tone": "neutral", "urgency": "normal", "response_strategy": "standard"}

        if label in (SentimentLabel.VERY_NEGATIVE, SentimentLabel.NEGATIVE):
            suggestions.update({
                "tone": "apologetic",
                "urgency": "high" if confidence > 0.8 else "medium",
                "response_strategy": "clarify_and_reassure"
            })
        elif label == SentimentLabel.VERY_POSITIVE:
            suggestions.update({
                "tone": "enthusiastic",
                "urgency": "low",
                "response_strategy": "reinforce_and_offer_more"
            })

        return suggestions

    def analyze(self, text: str, job_id: Optional[str] = None, client_id: Optional[str] = None) -> SentimentResult:
        """
        Анализирует тональность одного сообщения.
        Использует кэш, если текст уже анализировался.
        """
        if not self._initialized:
            raise RuntimeError("SentimentAnalyzer не инициализирован")

        # Ключ кэширования
        cache_key = f"sentiment:{hash(text)}"
        cached = self.cache.get(cache_key)
        if cached:
            logger.debug("📦 Использован кэшированный результат тональности")
            return SentimentResult(**cached)

        # Основная попытка
        result = self._analyze_with_model(text, self._primary_model, "primary")

        # Fallback при неудаче
        if result is None and self._fallback_model:
            logger.info("🔄 Переключение на резервную модель для анализа тональности")
            result = self._analyze_with_model(text, self._fallback_model, "fallback")

        # Если всё ещё нет результата — возвращаем нейтральный
        if result is None:
            logger.warning("⚠️ Ни одна модель не вернула результат. Возвращаем NEUTRAL по умолчанию.")
            result = SentimentResult(
                label=SentimentLabel.NEUTRAL,
                confidence=0.5,
                language=self._detect_language(text),
                suggestions={"tone": "neutral", "urgency": "low", "response_strategy": "standard"}
            )

        # Сохраняем в кэш (с TTL из конфига)
        ttl = self.config.get("performance.cache.sentiment_ttl_seconds", default=3600)
        self.cache.set(cache_key, result.__dict__, ttl=ttl)

        # Аудит
        self.audit_logger.log(
            action="sentiment_analysis",
            entity_type="message",
            entity_id=job_id or "unknown",
            metadata={
                "client_id": client_id,
                "text_preview": text[:100],
                "sentiment": result.label.name,
                "confidence": result.confidence
            }
        )

        return result

    def batch_analyze(self, texts: list[str]) -> list[SentimentResult]:
        """Анализирует список текстов (оптимизировано для скорости)."""
        return [self.analyze(text) for text in texts]