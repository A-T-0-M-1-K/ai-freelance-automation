# AI_FREELANCE_AUTOMATION/services/ai_services/summarization_service.py
"""
Сервис автоматического суммирования текста.
Поддерживает длинные тексты, мультиязычность, адаптивную длину и сохранение ключевых деталей.
Используется в workflow для подготовки отчётов, резюме заказов, анализа переписок.
"""

import logging
import time
from typing import Optional, Dict, Any, Union
from pathlib import Path

from core.dependency.service_locator import ServiceLocator
from core.config.unified_config_manager import UnifiedConfigManager
from core.ai_management.intelligent_model_manager import IntelligentModelManager
from core.monitoring.intelligent_monitoring_system import MetricsCollector
from core.security.audit_logger import AuditLogger

logger = logging.getLogger("AIServices.Summarization")
audit_log = AuditLogger("summarization_service")


class SummarizationService:
    """
    Автономный сервис суммирования текста на основе управляемых AI-моделей.
    Поддерживает:
      - абстрактное и экстрактивное суммирование
      - контроль длины (в % или токенах)
      - мультиязычность (автоопределение языка)
      - fallback при ошибках модели
    """

    def __init__(
        self,
        config_manager: Optional[UnifiedConfigManager] = None,
        model_manager: Optional[IntelligentModelManager] = None,
        metrics_collector: Optional[MetricsCollector] = None
    ):
        self.config_manager = config_manager or ServiceLocator.get("config_manager")
        self.model_manager = model_manager or ServiceLocator.get("model_manager")
        self.metrics = metrics_collector or ServiceLocator.get("metrics_collector")

        # Загрузка конфигурации сервиса
        self.service_config = self.config_manager.get_section("ai_services.summarization") or {}
        self.max_retries = self.service_config.get("max_retries", 3)
        self.default_length_ratio = self.service_config.get("default_length_ratio", 0.3)
        self.supported_languages = set(self.service_config.get("supported_languages", ["en", "ru", "es", "fr", "de"]))

        # Инициализация метрик
        self.metrics.register_counter("summarization.requests_total")
        self.metrics.register_counter("summarization.errors_total")
        self.metrics.register_histogram("summarization.latency_seconds")

        logger.info("Intialized SummarizationService with config: %s", self.service_config)

    def summarize(
        self,
        text: str,
        length_ratio: Optional[float] = None,
        target_language: Optional[str] = None,
        job_id: Optional[str] = None,
        client_id: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Генерирует краткое содержание текста.

        Args:
            text (str): Исходный текст.
            length_ratio (float, optional): Доля исходного текста (0.1–0.5). По умолчанию — из конфига.
            target_language (str, optional): Язык результата. Если не указан — как у исходника.
            job_id (str, optional): ID заказа для логирования.
            client_id (str, optional): ID клиента.
            **kwargs: Доп. параметры (например, стиль: 'formal', 'concise').

        Returns:
            dict: {
                "summary": str,
                "source_language": str,
                "target_language": str,
                "length_ratio": float,
                "model_used": str,
                "processing_time_sec": float
            }

        Raises:
            ValueError: Некорректные входные данные.
            RuntimeError: Не удалось выполнить суммирование после всех попыток.
        """
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Input text must be a non-empty string.")

        start_time = time.time()
        length_ratio = length_ratio or self.default_length_ratio
        if not (0.05 <= length_ratio <= 0.7):
            raise ValueError("length_ratio must be between 0.05 and 0.7")

        audit_log.log_action(
            action="summarize_request",
            actor="system",
            details={"job_id": job_id, "client_id": client_id, "text_length": len(text)}
        )

        self.metrics.increment("summarization.requests_total")
        error = None

        for attempt in range(1, self.max_retries + 1):
            try:
                # Определяем язык текста
                lang_detector = self.model_manager.get_model("language_detector")
                source_lang = lang_detector.detect(text) or "en"
                if source_lang not in self.supported_languages:
                    source_lang = "en"  # fallback

                target_lang = target_language or source_lang

                # Выбираем модель суммирования
                model_key = f"summarizer_{target_lang}"
                summarizer = self.model_manager.get_model(model_key)
                if not summarizer:
                    # fallback на универсальную модель
                    summarizer = self.model_manager.get_model("summarizer_multilingual")
                    if not summarizer:
                        raise RuntimeError(f"No summarizer available for language: {target_lang}")

                # Выполняем суммирование
                summary = summarizer.summarize(
                    text=text,
                    length_ratio=length_ratio,
                    **kwargs
                )

                processing_time = time.time() - start_time
                self.metrics.observe("summarization.latency_seconds", processing_time)

                result = {
                    "summary": summary,
                    "source_language": source_lang,
                    "target_language": target_lang,
                    "length_ratio": length_ratio,
                    "model_used": summarizer.model_id,
                    "processing_time_sec": round(processing_time, 2),
                    "job_id": job_id,
                    "client_id": client_id
                }

                audit_log.log_action(
                    action="summarize_success",
                    actor="system",
                    details=result
                )
                logger.info("✅ Summarization completed for job=%s in %.2fs", job_id, processing_time)
                return result

            except Exception as e:
                error = e
                logger.warning(
                    "⚠️ Summarization attempt %d/%d failed for job=%s: %s",
                    attempt, self.max_retries, job_id, str(e)
                )
                self.metrics.increment("summarization.errors_total")
                if attempt < self.max_retries:
                    time.sleep(2 ** attempt)  # экспоненциальная задержка
                else:
                    break

        # Все попытки исчерпаны
        self.metrics.increment("summarization.errors_total")
        audit_log.log_action(
            action="summarize_failure",
            actor="system",
            details={"job_id": job_id, "error": str(error), "attempts": self.max_retries}
        )
        logger.error("❌ Summarization failed after %d attempts for job=%s", self.max_retries, job_id)
        raise RuntimeError(f"Summarization failed after {self.max_retries} attempts: {error}")

    def batch_summarize(self, texts: list, **kwargs) -> list:
        """Пакетная обработка нескольких текстов."""
        return [self.summarize(text, **kwargs) for text in texts]


# Регистрация сервиса в глобальном реестре (если используется)
def register_service():
    from services.service_registry import ServiceRegistry
    registry = ServiceRegistry.get_instance()
    registry.register("summarization_service", SummarizationService)


# Автоматическая регистрация при импорте (опционально)
# register_service()