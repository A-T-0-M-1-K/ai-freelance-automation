"""
AI Freelance Automation — Decision Engine
========================================

Автономный движок принятия решений для фриланс-заказов.
Оценивает прибыльность, риски, загрузку системы и принимает решения об участии в заказах.

Ключевые функции:
- Анализ заказа на основе AI-моделей
- Расчёт ROI и временных затрат
- Оценка репутации клиента и платформы
- Учёт текущей загрузки системы
- Принятие бинарного решения: участвовать / пропустить
- Самообучение на основе истории решений

Следует принципам:
✅ 100% автономности
✅ Самовосстановления (через health_monitor)
✅ Безопасности (все данные шифруются)
✅ Масштабируемости (асинхронная обработка)
✅ Соответствия GDPR/PCI DSS

Зависимости разрешаются через DI или service locator.
"""

import asyncio
import logging
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timedelta
import json

from core.config.unified_config_manager import UnifiedConfigManager
from core.security.audit_logger import AuditLogger
from core.monitoring.intelligent_monitoring_system import IntelligentMonitoringSystem
from core.ai_management.intelligent_model_manager import IntelligentModelManager
from core.learning.continuous_learning_system import ContinuousLearningSystem
from core.analytics.predictive_analytics import PredictiveAnalytics
from core.automation.job_analyzer import JobAnalyzer
from core.automation.reputation_manager import ReputationManager


class DecisionEngine:
    """
    Главный AI-движок принятия решений о фриланс-заказах.
    """

    def __init__(
        self,
        config: UnifiedConfigManager,
        model_manager: IntelligentModelManager,
        monitoring: IntelligentMonitoringSystem,
        learning_system: Optional[ContinuousLearningSystem] = None,
        analytics: Optional[PredictiveAnalytics] = None,
        job_analyzer: Optional[JobAnalyzer] = None,
        reputation_manager: Optional[ReputationManager] = None,
    ):
        self.config = config
        self.model_manager = model_manager
        self.monitoring = monitoring
        self.learning_system = learning_system or ContinuousLearningSystem(config)
        self.analytics = analytics or PredictiveAnalytics(config)
        self.job_analyzer = job_analyzer or JobAnalyzer(config)
        self.reputation_manager = reputation_manager or ReputationManager(config)

        self.logger = logging.getLogger("DecisionEngine")
        self.audit_logger = AuditLogger("decision_engine")

        # Загрузка порогов из конфигурации
        self.min_acceptable_roi = self.config.get("automation.decision.min_roi", default=0.3)
        self.max_concurrent_jobs = self.config.get("automation.limits.max_concurrent_jobs", default=20)
        self.risk_tolerance = self.config.get("automation.decision.risk_tolerance", default="medium")  # low/medium/high

        self.logger.info("✅ Decision Engine initialized with risk tolerance: %s", self.risk_tolerance)

    async def evaluate_job(self, job_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Полная оценка заказа. Возвращает структуру с рекомендацией.

        Args:
            job_data (dict): Сырые данные заказа от платформы.

        Returns:
            dict: {
                "decision": "accept" | "reject",
                "confidence": float [0.0–1.0],
                "reasons": List[str],
                "estimated_time_hours": float,
                "estimated_profit_usd": float,
                "risk_score": float [0.0–1.0]
            }
        """
        job_id = job_data.get("id", "unknown")
        self.logger.info("🔍 Evaluating job %s", job_id)

        try:
            # 1. Анализ содержания заказа
            analysis = await self.job_analyzer.analyze(job_data)
            self.logger.debug("Job analysis for %s: %s", job_id, analysis)

            # 2. Проверка текущей загрузки
            current_load = await self._get_current_system_load()
            if current_load >= self.max_concurrent_jobs:
                return self._make_rejection(
                    job_id, ["System at maximum capacity"], risk_score=0.95
                )

            # 3. Оценка клиента
            client_risk = await self.reputation_manager.assess_client_risk(
                client_id=job_data.get("client_id"),
                platform=job_data.get("platform")
            )

            # 4. Прогноз прибыли и времени
            profit, time_est = await self._predict_profit_and_time(analysis, job_data)

            # 5. Расчёт ROI
            roi = self._calculate_roi(profit, time_est)

            # 6. Комплексная оценка риска
            risk_score = self._aggregate_risk_score(
                client_risk=client_risk,
                complexity=analysis.get("complexity", 0.5),
                deadline_risk=self._assess_deadline_risk(job_data),
                platform_risk=self._assess_platform_risk(job_data.get("platform"))
            )

            # 7. Принятие решения
            should_accept = (
                roi >= self.min_acceptable_roi and
                risk_score <= self._get_max_risk_threshold() and
                profit > 0
            )

            reasons = []
            if roi < self.min_acceptable_roi:
                reasons.append(f"ROI too low ({roi:.2%} < {self.min_acceptable_roi:.2%})")
            if risk_score > self._get_max_risk_threshold():
                reasons.append(f"Risk too high ({risk_score:.2f})")
            if profit <= 0:
                reasons.append("Non-profitable")

            decision = "accept" if should_accept else "reject"
            confidence = max(0.0, min(1.0, 1.0 - abs(risk_score - 0.5)))

            result = {
                "decision": decision,
                "confidence": round(confidence, 3),
                "reasons": reasons if not should_accept else [],
                "estimated_time_hours": round(time_est, 2),
                "estimated_profit_usd": round(profit, 2),
                "risk_score": round(risk_score, 3),
                "timestamp": datetime.utcnow().isoformat()
            }

            # Аудит решения
            self.audit_logger.log_decision(
                job_id=job_id,
                decision=decision,
                metadata=result
            )

            # Обучение на решении
            if self.learning_system:
                await self.learning_system.record_decision(
                    job_data=job_data,
                    analysis=analysis,
                    decision_result=result
                )

            self.logger.info("✅ Decision for job %s: %s (confidence: %.2f)", job_id, decision, confidence)
            return result

        except Exception as e:
            self.logger.error("💥 Error evaluating job %s: %s", job_id, e, exc_info=True)
            self.monitoring.report_error("decision_engine.evaluate_job", str(e))
            return self._make_rejection(job_id, ["Internal error during evaluation"], risk_score=1.0)

    async def _get_current_system_load(self) -> int:
        """Возвращает текущее количество активных заказов."""
        # В реальной системе это может читаться из базы или кэша
        # Здесь — заглушка. В продакшене заменить на реальный источник.
        active_jobs = self.config.get_runtime_stat("active_jobs_count", default=0)
        return int(active_jobs)

    async def _predict_profit_and_time(self, analysis: Dict[str, Any], job_data: Dict[str, Any]) -> Tuple[float, float]:
        """Прогнозирует прибыль и время выполнения."""
        # Используем AI-модель для точной оценки
        payload = {
            "job_type": analysis.get("category"),
            "complexity": analysis.get("complexity", 0.5),
            "word_count": analysis.get("word_count", 0),
            "language_pair": analysis.get("language_pair"),
            "deadline_hours": self._get_deadline_hours(job_data),
            "platform": job_data.get("platform")
        }

        try:
            model = await self.model_manager.get_model("profit_predictor")
            prediction = await model.infer(payload)
            profit = float(prediction.get("profit_usd", 0.0))
            time_est = float(prediction.get("time_hours", 1.0))
            return max(0.0, profit), max(0.1, time_est)
        except Exception as e:
            self.logger.warning("⚠️ Profit prediction failed, using fallback: %s", e)
            # Fallback логика
            base_rate = 10.0  # $/час
            time_est = analysis.get("complexity", 0.5) * 5.0  # до 5 часов
            budget = float(job_data.get("budget", 0))
            profit = budget * 0.7  # 70% маржи
            return profit, time_est

    def _calculate_roi(self, profit: float, time_hours: float) -> float:
        """Рассчитывает ROI (Return on Investment)."""
        if time_hours <= 0:
            return 0.0
        hourly_value = profit / time_hours
        baseline_hourly = self.config.get("automation.baseline_hourly_rate", default=15.0)
        return (hourly_value - baseline_hourly) / baseline_hourly if baseline_hourly > 0 else 0.0

    def _assess_deadline_risk(self, job_data: Dict[str, Any]) -> float:
        """Оценивает риск срыва дедлайна (0.0 = безопасно, 1.0 = критично)."""
        deadline_str = job_data.get("deadline")
        if not deadline_str:
            return 0.3  # неопределённость = средний риск

        try:
            deadline = datetime.fromisoformat(deadline_str.replace("Z", "+00:00"))
            now = datetime.utcnow()
            hours_left = (deadline - now).total_seconds() / 3600
            if hours_left < 1:
                return 1.0
            elif hours_left < 6:
                return 0.8
            elif hours_left < 24:
                return 0.5
            else:
                return 0.1
        except Exception:
            return 0.4

    def _assess_platform_risk(self, platform: str) -> float:
        """Оценка риска по платформе (например, Fiverr vs Upwork)."""
        risk_map = {
            "upwork": 0.2,
            "freelance_ru": 0.3,
            "kwork": 0.4,
            "fiverr": 0.35,
            "unknown": 0.5
        }
        return risk_map.get(platform.lower(), 0.5)

    def _aggregate_risk_score(self, client_risk: float, complexity: float, deadline_risk: float, platform_risk: float) -> float:
        """Агрегирует все факторы риска в единый скор."""
        weights = {
            "client": 0.3,
            "complexity": 0.25,
            "deadline": 0.25,
            "platform": 0.2
        }
        score = (
            weights["client"] * client_risk +
            weights["complexity"] * complexity +
            weights["deadline"] * deadline_risk +
            weights["platform"] * platform_risk
        )
        return min(1.0, max(0.0, score))

    def _get_max_risk_threshold(self) -> float:
        """Возвращает максимальный допустимый уровень риска."""
        thresholds = {"low": 0.3, "medium": 0.6, "high": 0.8}
        return thresholds.get(self.risk_tolerance, 0.6)

    def _make_rejection(self, job_id: str, reasons: List[str], risk_score: float = 1.0) -> Dict[str, Any]:
        """Утилита для формирования отказа."""
        return {
            "decision": "reject",
            "confidence": 0.99,
            "reasons": reasons,
            "estimated_time_hours": 0.0,
            "estimated_profit_usd": 0.0,
            "risk_score": risk_score,
            "timestamp": datetime.utcnow().isoformat()
        }