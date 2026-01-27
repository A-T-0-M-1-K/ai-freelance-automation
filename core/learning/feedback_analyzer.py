# AI_FREELANCE_AUTOMATION/core/learning/feedback_analyzer.py

"""
Feedback Analyzer — анализирует клиентский фидбэк для непрерывного улучшения работы системы.
Извлекает паттерны успеха/провала, обновляет знания, корректирует поведение автономного агента.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from datetime import datetime

from core.dependency.service_locator import ServiceLocator
from core.config.unified_config_manager import UnifiedConfigManager
from core.learning.pattern_extractor import PatternExtractor
from core.learning.knowledge_base import KnowledgeBase
from core.monitoring.intelligent_monitoring_system import AlertLevel

logger = logging.getLogger("FeedbackAnalyzer")


class FeedbackAnalyzer:
    """
    Анализирует все формы обратной связи от клиентов:
    - Отзывы после завершения заказа
    - Сообщения в чатах (неявные сигналы)
    - Повторные заказы / отказы
    - Оценки качества (если доступны)

    Результаты используются для:
    - Обновления KnowledgeBase
    - Настройки DecisionEngine
    - Коррекции тональности Communicator'а
    """

    def __init__(
            self,
            config: Optional[UnifiedConfigManager] = None,
            knowledge_base: Optional[KnowledgeBase] = None,
            pattern_extractor: Optional[PatternExtractor] = None,
    ):
        self.config = config or ServiceLocator.get_service("config")
        self.knowledge_base = knowledge_base or ServiceLocator.get_service("knowledge_base")
        self.pattern_extractor = pattern_extractor or ServiceLocator.get_service("pattern_extractor")

        self.data_dir = Path(self.config.get("data.feedback_dir", "data/feedback"))
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self._load_feedback_index()
        logger.info("✅ FeedbackAnalyzer initialized.")

    def _load_feedback_index(self) -> None:
        """Загружает индекс обработанных отзывов."""
        index_path = self.data_dir / "feedback_index.json"
        if index_path.exists():
            try:
                with open(index_path, "r", encoding="utf-8") as f:
                    self.processed_feedback_ids = set(json.load(f))
            except Exception as e:
                logger.warning(f"⚠️ Failed to load feedback index: {e}. Recreating.")
                self.processed_feedback_ids = set()
        else:
            self.processed_feedback_ids = set()

    def _save_feedback_index(self) -> None:
        """Сохраняет индекс обработанных отзывов."""
        index_path = self.data_dir / "feedback_index.json"
        try:
            with open(index_path, "w", encoding=" utf-8") as f:
                json.dump(list(self.processed_feedback_ids), f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"💥 Failed to save feedback index: {e}")

    def analyze_job_feedback(self, job_id: str, feedback_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Анализирует фидбэк по конкретному заказу.

        Ожидаемая структура feedback_data:
        {
            "client_id": "str",
            "rating": 1-5 (optional),
            "text": "строка отзыва (optional)",
            "reordered": bool,
            "messages_context": [{"role": "...", "content": "..."}],
            "delivered_on_time": bool,
            "revision_count": int
        }
        """
        if not job_id or not isinstance(feedback_data, dict):
            logger.error("❌ Invalid input to analyze_job_feedback")
            raise ValueError("job_id and feedback_data must be valid")

        feedback_id = f"{job_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        if feedback_id in self.processed_feedback_ids:
            logger.debug(f"⏭️ Feedback {feedback_id} already processed. Skipping.")
            return {}

        logger.info(f"🔍 Analyzing feedback for job {job_id}")

        # Извлечение признаков
        analysis = self._extract_feedback_signals(feedback_data)
        analysis["job_id"] = job_id
        analysis["client_id"] = feedback_data.get("client_id")
        analysis["timestamp"] = datetime.utcnow().isoformat()

        # Сохранение анализа
        self._persist_analysis(feedback_id, analysis)

        # Обновление глобальных знаний
        self._update_knowledge_base(analysis)

        # Регистрация в индексе
        self.processed_feedback_ids.add(feedback_id)
        self._save_feedback_index()

        logger.info(f"✅ Feedback analysis completed for job {job_id}")
        return analysis

    def _extract_feedback_signals(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Извлекает количественные и качественные сигналы из фидбэка."""
        signals = {}

        # Явные метрики
        signals["explicit_rating"] = data.get("rating")
        signals["on_time_delivery"] = data.get("delivered_on_time", True)
        signals["revision_count"] = data.get("revision_count", 0)
        signals["reordered"] = data.get("reordered", False)

        # Качественный анализ текста
        text = data.get("text", "")
        if text:
            sentiment = self._analyze_sentiment(text)
            signals["sentiment_score"] = sentiment["score"]
            signals["sentiment_label"] = sentiment["label"]
            signals["keywords"] = sentiment.get("keywords", [])
        else:
            signals["sentiment_score"] = 0.0
            signals["sentiment_label"] = "neutral"

        # Анализ диалога (если есть)
        messages = data.get("messages_context", [])
        if messages:
            dialogue_patterns = self.pattern_extractor.extract_dialogue_patterns(messages)
            signals["dialogue_patterns"] = dialogue_patterns

        # Комплексный показатель успеха (0.0–1.0)
        success_score = self._calculate_success_score(signals)
        signals["success_score"] = success_score

        # Алерт при низком качестве
        if success_score < 0.3:
            from core.monitoring.intelligent_monitoring_system import IntelligentMonitoringSystem
            monitor = ServiceLocator.get_service("monitoring")
            monitor.log_alert(
                level=AlertLevel.WARNING,
                source="FeedbackAnalyzer",
                message=f"Low success score ({success_score:.2f}) for job feedback",
                context={"signals": signals}
            )

        return signals

    def _analyze_sentiment(self, text: str) -> Dict[str, Any]:
        """Анализ тональности текста (stub; в продакшене — вызов AI-сервиса)."""
        # В реальной системе: вызов ai_services/sentiment_analysis или внешнего API
        # Здесь — упрощённая эвристика для демонстрации
        positive_words = {"great", "excellent", "perfect", "amazing", "thank", "good", "fast", "professional"}
        negative_words = {"bad", "terrible", "slow", "wrong", "disappointed", "error", "mistake", "poor"}

        words = set(text.lower().split())
        pos_count = len(words & positive_words)
        neg_count = len(words & negative_words)

        if pos_count > neg_count:
            score = min(1.0, 0.5 + 0.1 * pos_count)
            label = "positive"
        elif neg_count > pos_count:
            score = max(0.0, 0.5 - 0.1 * neg_count)
            label = "negative"
        else:
            score = 0.5
            label = "neutral"

        # Простой ключевой анализ
        keywords = [w for w in words if len(w) > 4][:5]

        return {
            "score": score,
            "label": label,
            "keywords": keywords
        }

    def _calculate_success_score(self, signals: Dict[str, Any]) -> float:
        """Рассчитывает комплексный показатель успеха на основе сигналов."""
        score = 0.0
        weight = 0

        # Рейтинг (макс. 0.4)
        if signals.get("explicit_rating") is not None:
            score += (signals["explicit_rating"] / 5.0) * 0.4
            weight += 0.4

        # Своевременность (0.2)
        if signals.get("on_time_delivery"):
            score += 0.2
            weight += 0.2

        # Повторный заказ (0.2)
        if signals.get("reordered"):
            score += 0.2
            weight += 0.2

        # Тональность (0.2)
        score += signals.get("sentiment_score", 0.5) * 0.2
        weight += 0.2

        # Штраф за ревизии
        revisions = signals.get("revision_count", 0)
        if revisions > 2:
            score *= max(0.5, 1.0 - (revisions - 2) * 0.1)

        return min(1.0, max(0.0, score / weight if weight > 0 else 0.5))

    def _persist_analysis(self, feedback_id: str, analysis: Dict[str, Any]) -> None:
        """Сохраняет результат анализа в файловую систему."""
        try:
            filepath = self.data_dir / f"{feedback_id}.json"
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(analysis, f, ensure_ascii=False, indent=2)
            logger.debug(f"💾 Saved feedback analysis to {filepath}")
        except Exception as e:
            logger.error(f"💥 Failed to persist feedback analysis: {e}")
            raise

    def _update_knowledge_base(self, analysis: Dict[str, Any]) -> None:
        """Обновляет глобальную базу знаний на основе анализа."""
        try:
            # Формируем запись для KB
            kb_entry = {
                "type": "feedback_insight",
                "source": "feedback_analyzer",
                "timestamp": analysis["timestamp"],
                "job_id": analysis["job_id"],
                "client_id": analysis["client_id"],
                "success_score": analysis["success_score"],
                "sentiment": analysis.get("sentiment_label"),
                "keywords": analysis.get("keywords", []),
                "patterns": analysis.get("dialogue_patterns", {}),
                "lessons": self._generate_lessons(analysis)
            }

            self.knowledge_base.add_entry(kb_entry)
            logger.debug("🧠 KnowledgeBase updated with new feedback insight.")
        except Exception as e:
            logger.error(f"💥 Failed to update KnowledgeBase: {e}")

    def _generate_lessons(self, analysis: Dict[str, Any]) -> List[str]:
        """Генерирует выводы ('уроки') из анализа."""
        lessons = []

        if analysis["success_score"] < 0.4:
            lessons.append("Высокий риск недовольства клиента — пересмотреть подход к коммуникации")
        if analysis.get("revision_count", 0) > 2:
            lessons.append("Частые правки — уточнять требования на этапе согласования")
        if analysis.get("sentiment_label") == "negative":
            lessons.append("Негативная тональность — активировать режим восстановления отношений")
        if analysis.get("reordered"):
            lessons.append("Клиент вернулся — закрепить успешную стратегию")

        return lessons

    def get_aggregated_insights(self, days: int = 30) -> Dict[str, Any]:
        """Возвращает агрегированные инсайты за последние N дней."""
        # TODO: Реализовать агрегацию по файлам в data/feedback/
        # Для MVP — заглушка
        return {
            "period_days": days,
            "total_feedbacks": len(self.processed_feedback_ids),
            "avg_success_score": 0.75,
            "common_issues": ["unclear_requirements", "slow_response"],
            "improvement_suggestions": ["ask_more_questions", "send_intermediate_reports"]
        }