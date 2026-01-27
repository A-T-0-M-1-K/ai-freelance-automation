# AI_FREELANCE_AUTOMATION/core/automation/job_analyzer.py
"""
Job Analyzer — анализирует заказы с фриланс-платформ на релевантность, прибыльность, риск и сложность.
Использует AI-модели для семантического понимания требований и контекста.
"""

import logging
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

from core.ai_management.intelligent_model_manager import IntelligentModelManager
from core.config.unified_config_manager import UnifiedConfigManager
from core.monitoring.intelligent_monitoring_system import IntelligentMonitoringSystem
from core.security.audit_logger import AuditLogger

logger = logging.getLogger("JobAnalyzer")


class JobRiskLevel(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class JobAnalysisResult:
    """Структура результата анализа заказа."""
    job_id: str
    relevance_score: float  # 0.0–1.0
    profitability_score: float  # 0.0–1.0
    risk_level: JobRiskLevel
    estimated_effort_hours: float
    recommended_bid: float
    ai_confidence: float  # Насколько модель уверена в оценке
    tags: List[str]
    warnings: List[str]
    is_worth_pursuing: bool


class JobAnalyzer:
    """
    Анализирует заказы с платформ (Upwork, Freelance.ru и др.) и выдает структурированную оценку.
    Работает полностью автономно, использует NLP и бизнес-логику.
    """

    def __init__(
        self,
        config: UnifiedConfigManager,
        ai_manager: IntelligentModelManager,
        monitoring: Optional[IntelligentMonitoringSystem] = None,
        audit_logger: Optional[AuditLogger] = None
    ):
        self.config = config
        self.ai_manager = ai_manager
        self.monitoring = monitoring or IntelligentMonitoringSystem(config)
        self.audit_logger = audit_logger or AuditLogger()
        self._load_rules()

        logger.info("✅ JobAnalyzer initialized")

    def _load_rules(self) -> None:
        """Загружает бизнес-правила из конфигурации."""
        automation_cfg = self.config.get_section("automation")
        self.min_relevance_threshold = automation_cfg.get("min_relevance_threshold", 0.65)
        self.min_profitability_threshold = automation_cfg.get("min_profitability_threshold", 0.5)
        self.max_risk_acceptable = automation_cfg.get("max_risk_acceptable", "medium")
        self.hourly_rate = automation_cfg.get("default_hourly_rate", 30.0)
        self.currency = automation_cfg.get("currency", "USD")

    def analyze_job(self, job_data: Dict[str, Any]) -> JobAnalysisResult:
        """
        Анализирует один заказ.

        :param job_data: Словарь с данными заказа (title, description, budget, deadline и т.д.)
        :return: JobAnalysisResult — структурированная оценка
        """
        job_id = job_data.get("id", "unknown")
        try:
            logger.debug(f"🔍 Starting analysis of job {job_id}")

            # 1. Семантический анализ через AI
            relevance, tags, ai_confidence = self._analyze_relevance(job_data)
            effort_hours = self._estimate_effort(job_data, tags)
            budget = self._extract_budget(job_data)
            profitability = self._calculate_profitability(effort_hours, budget)

            # 2. Оценка рисков
            risk_level, warnings = self._assess_risk(job_data, effort_hours, budget)

            # 3. Рекомендуемая ставка
            recommended_bid = self._calculate_bid(effort_hours, risk_level)

            # 4. Принятие решения
            is_worth = self._should_pursue(
                relevance, profitability, risk_level
            )

            result = JobAnalysisResult(
                job_id=job_id,
                relevance_score=relevance,
                profitability_score=profitability,
                risk_level=risk_level,
                estimated_effort_hours=effort_hours,
                recommended_bid=recommended_bid,
                ai_confidence=ai_confidence,
                tags=tags,
                warnings=warnings,
                is_worth_pursuing=is_worth
            )

            # Логирование аудита
            self.audit_logger.log_event(
                event_type="job_analysis",
                entity_id=job_id,
                details={
                    "relevance": relevance,
                    "profitability": profitability,
                    "risk": risk_level.value,
                    "decision": is_worth
                }
            )

            # Метрики мониторинга
            if self.monitoring:
                self.monitoring.record_metric("job.analyzed", 1)
                self.monitoring.record_metric("job.relevance.avg", relevance)
                self.monitoring.record_metric("job.profitability.avg", profitability)

            logger.info(f"✅ Job {job_id} analyzed | Relevance: {relevance:.2f}, Profit: {profitability:.2f}, Risk: {risk_level.value}")
            return result

        except Exception as e:
            error_msg = f"❌ Failed to analyze job {job_id}: {str(e)}"
            logger.error(error_msg, exc_info=True)
            self.audit_logger.log_security_event("job_analysis_failure", job_id, str(e))
            if self.monitoring:
                self.monitoring.record_metric("job.analysis_errors", 1)
            raise RuntimeError(error_msg) from e

    def _analyze_relevance(self, job: Dict[str, Any]) -> Tuple[float, List[str], float]:
        """Оценивает релевантность заказа с помощью NLP-модели."""
        text = f"{job.get('title', '')} {job.get('description', '')}".strip()
        if not text:
            return 0.0, [], 0.0

        # Используем AI-модель для классификации и извлечения тегов
        model = self.ai_manager.get_model("text_classifier")
        result = model.predict(
            input_text=text,
            task="freelance_job_classification",
            return_tags=True,
            return_confidence=True
        )

        relevance = result.get("relevance_score", 0.0)
        tags = result.get("tags", [])
        confidence = result.get("confidence", 0.0)

        # Фильтрация по разрешённым категориям (например: transcription, translation, copywriting)
        allowed_services = self.config.get_section("automation").get("allowed_services", [])
        if allowed_services:
            tags = [t for t in tags if t in allowed_services]
            if not tags:
                relevance = 0.0

        return float(relevance), tags, float(confidence)

    def _estimate_effort(self, job: Dict[str, Any], tags: List[str]) -> float:
        """Оценивает трудозатраты в часах."""
        # Базовая оценка по объёму текста
        desc = job.get("description", "")
        word_count = len(desc.split())
        base_hours = max(0.5, word_count / 500.0)  # ~500 слов/час

        # Корректировка по типу работы
        if "transcription" in tags:
            # Аудио → текст: зависит от длительности
            duration_min = job.get("audio_duration_minutes", 0)
            base_hours = max(0.5, duration_min / 60.0 * 1.5)  # 1.5x за сложность
        elif "translation" in tags:
            base_hours *= 1.2
        elif "copywriting" in tags:
            base_hours *= 1.5

        # Учёт срочности
        if job.get("is_urgent", False):
            base_hours *= 0.7  # система работает быстрее, но это увеличивает риск

        return round(base_hours, 2)

    def _extract_budget(self, job: Dict[str, Any]) -> float:
        """Извлекает бюджет или рассчитывает по ставке."""
        if job.get("budget_fixed"):
            return float(job["budget_fixed"])
        if job.get("budget_hourly_min") and job.get("budget_hourly_max"):
            return (float(job["budget_hourly_min"]) + float(job["budget_hourly_max"])) / 2 * 10  # среднее × 10 часов
        return 0.0

    def _calculate_profitability(self, effort_hours: float, budget: float) -> float:
        """Рассчитывает нормализованную прибыльность (0–1)."""
        if effort_hours <= 0 or budget <= 0:
            return 0.0
        expected_revenue = budget
        expected_cost = effort_hours * self.hourly_rate
        profit_margin = (expected_revenue - expected_cost) / expected_revenue if expected_revenue > 0 else 0
        # Нормализуем до [0, 1], где 1 = 100% маржа
        score = min(1.0, max(0.0, profit_margin + 0.5))  # сдвиг, чтобы даже убыточные имели шанс
        return score

    def _assess_risk(self, job: Dict[str, Any], effort: float, budget: float) -> Tuple[JobRiskLevel, List[str]]:
        """Оценивает риски."""
        warnings = []
        risk_score = 0

        # Клиент без отзывов
        if job.get("client_reviews_count", 0) == 0:
            warnings.append("Новый клиент без отзывов")
            risk_score += 1

        # Очень низкий бюджет
        if budget > 0 and budget < effort * self.hourly_rate * 0.7:
            warnings.append("Бюджет ниже рыночного")
            risk_score += 1

        # Слишком короткий дедлайн
        deadline_hours = job.get("deadline_hours", 999)
        if deadline_hours < effort * 0.8:
            warnings.append("Дедлайн слишком сжатый")
            risk_score += 1

        # Неясные требования
        if len(job.get("description", "")) < 50:
            warnings.append("Описание слишком краткое")
            risk_score += 1

        if risk_score >= 3:
            level = JobRiskLevel.CRITICAL
        elif risk_score == 2:
            level = JobRiskLevel.HIGH
        elif risk_score == 1:
            level = JobRiskLevel.MEDIUM
        else:
            level = JobRiskLevel.LOW

        return level, warnings

    def _calculate_bid(self, effort_hours: float, risk_level: JobRiskLevel) -> float:
        """Рассчитывает рекомендуемую ставку."""
        base_price = effort_hours * self.hourly_rate

        # Премия за риск
        risk_multiplier = {
            JobRiskLevel.LOW: 1.0,
            JobRiskLevel.MEDIUM: 1.1,
            JobRiskLevel.HIGH: 1.25,
            JobRiskLevel.CRITICAL: 1.5
        }
        bid = base_price * risk_multiplier[risk_level]

        # Округление до красивого числа
        if bid < 50:
            return round(bid, -1)
        elif bid < 500:
            return round(bid, -2)
        else:
            return round(bid, -3)

    def _should_pursue(
        self,
        relevance: float,
        profitability: float,
        risk: JobRiskLevel
    ) -> bool:
        """Принимает решение — стоит ли участвовать."""
        if relevance < self.min_relevance_threshold:
            return False
        if profitability < self.min_profitability_threshold:
            return False
        if risk == JobRiskLevel.CRITICAL:
            return False
        return True