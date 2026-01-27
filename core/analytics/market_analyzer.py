# AI_FREELANCE_AUTOMATION/core/analytics/market_analyzer.py
"""
Market Analyzer — анализирует рыночные тренды на фриланс-платформах:
- Средние ставки по категориям
- Конкуренция (число исполнителей, подавших заявки)
- Сезонность спроса
- Популярность навыков
- Динамика цен

Используется DecisionEngine и PredictiveAnalytics для принятия решений о ставках.
"""

import logging
import json
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass

from core.config.unified_config_manager import UnifiedConfigManager
from core.dependency.service_locator import ServiceLocator
from core.monitoring.intelligent_monitoring_system import MetricsCollector
from core.security.audit_logger import AuditLogger

logger = logging.getLogger("MarketAnalyzer")


@dataclass
class MarketInsight:
    category: str
    avg_bid: float
    median_bid: float
    min_bid: float
    max_bid: float
    competition_level: float  # 0.0–1.0 (0 = низкая, 1 = высокая)
    demand_trend: str  # "rising", "stable", "falling"
    skill_demand: Dict[str, int]  # {"Python": 120, "Copywriting": 85, ...}
    updated_at: str


class MarketAnalyzer:
    """
    Анализирует рынок фриланса на основе данных с платформ.
    Кэширует результаты, обновляет раз в N минут (настраивается).
    Поддерживает многоплатформенность через PlatformFactory.
    """

    def __init__(self, config: Optional[UnifiedConfigManager] = None):
        self.config = config or ServiceLocator.get("config")
        self.audit_logger = AuditLogger()
        self.metrics = MetricsCollector()
        self._cache: Dict[str, MarketInsight] = {}
        self._last_update: Dict[str, datetime] = {}

        # Загрузка параметров из конфига
        analytics_cfg = self.config.get("analytics", {})
        self.update_interval_minutes = analytics_cfg.get("market_update_interval_minutes", 30)
        self.enabled_platforms = self.config.get("platforms.enabled", ["upwork", "freelance_ru", "kwork"])

        logger.info("Intialized MarketAnalyzer with platforms: %s", self.enabled_platforms)

    def analyze_market(self, category: str, platform: Optional[str] = None) -> MarketInsight:
        """
        Возвращает актуальный анализ рынка для заданной категории.
        Если данные устарели или отсутствуют — запускает обновление.
        """
        cache_key = f"{platform or 'all'}_{category}"
        now = datetime.utcnow()

        # Проверка кэша
        if cache_key in self._cache:
            last_upd = self._last_update[cache_key]
            if (now - last_upd).total_seconds() < self.update_interval_minutes * 60:
                logger.debug("Using cached market insight for %s", cache_key)
                return self._cache[cache_key]

        # Обновление данных
        logger.info("Refreshing market data for %s", cache_key)
        insight = self._fetch_and_analyze(category, platform)
        self._cache[cache_key] = insight
        self._last_update[cache_key] = now

        # Логирование аналитики
        self.audit_logger.log("market_analysis", {
            "category": category,
            "platform": platform,
            "avg_bid": insight.avg_bid,
            "competition": insight.competition_level
        })

        # Метрики для мониторинга
        self.metrics.gauge("market.avg_bid", insight.avg_bid, tags={"category": category, "platform": platform})
        self.metrics.gauge("market.competition", insight.competition_level, tags={"category": category})

        return insight

    def _fetch_and_analyze(self, category: str, platform: Optional[str] = None) -> MarketInsight:
        """
        Собирает данные с платформ и вычисляет рыночные метрики.
        """
        try:
            platform_factory = ServiceLocator.get("platform_factory")
            all_bids: List[float] = []
            all_skills: Dict[str, int] = {}
            total_jobs = 0

            platforms_to_scan = [platform] if platform else self.enabled_platforms

            for plat_name in platforms_to_scan:
                try:
                    client = platform_factory.get_client(plat_name)
                    recent_jobs = client.get_recent_jobs(
                        category=category,
                        limit=100,
                        days_back=7
                    )
                    for job in recent_jobs:
                        if job.get("budget"):
                            all_bids.append(job["budget"])
                        if "skills" in job:
                            for skill in job["skills"]:
                                all_skills[skill] = all_skills.get(skill, 0) + 1
                        total_jobs += 1
                except Exception as e:
                    logger.warning("Failed to fetch data from platform %s: %s", plat_name, e)
                    continue

            if not all_bids:
                # Fallback на исторические данные или дефолтные значения
                logger.warning("No market data found for category %s. Using fallback.", category)
                return self._get_fallback_insight(category)

            # Расчет метрик
            all_bids.sort()
            n = len(all_bids)
            avg_bid = sum(all_bids) / n
            median_bid = all_bids[n // 2] if n % 2 == 1 else (all_bids[n // 2 - 1] + all_bids[n // 2]) / 2
            min_bid, max_bid = min(all_bids), max(all_bids)

            # Уровень конкуренции: отношение заявок к заказам (упрощённо — используем историю)
            # В реальной системе это берётся из job["applicants_count"]
            # Здесь эмулируем: чем больше заказов — тем выше конкуренция
            competition = min(1.0, total_jobs / 50.0) if total_jobs > 0 else 0.3

            # Тренд: сравниваем с неделей ранее (здесь упрощённо — стабильно)
            demand_trend = "stable"
            if len(all_bids) > 50:
                # Простой тренд: рост количества заказов → rising
                # (в продакшене — ML-модель из predictive_analytics)
                demand_trend = "rising"

            return MarketInsight(
                category=category,
                avg_bid=round(avg_bid, 2),
                median_bid=round(median_bid, 2),
                min_bid=min_bid,
                max_bid=max_bid,
                competition_level=round(competition, 2),
                demand_trend=demand_trend,
                skill_demand=all_skills,
                updated_at=datetime.utcnow().isoformat()
            )

        except Exception as e:
            logger.error("Critical error in market analysis: %s", e, exc_info=True)
            return self._get_fallback_insight(category)

    def _get_fallback_insight(self, category: str) -> MarketInsight:
        """Возвращает безопасные дефолтные значения."""
        fallback_map = {
            "transcription": MarketInsight(
                category="transcription",
                avg_bid=25.0,
                median_bid=22.0,
                min_bid=10.0,
                max_bid=60.0,
                competition_level=0.6,
                demand_trend="stable",
                skill_demand={"English": 100, "Transcription": 90, "Whisper": 70},
                updated_at=datetime.utcnow().isoformat()
            ),
            "translation": MarketInsight(
                category="translation",
                avg_bid=30.0,
                median_bid=28.0,
                min_bid=15.0,
                max_bid=80.0,
                competition_level=0.7,
                demand_trend="rising",
                skill_demand={"English": 120, "Russian": 100, "NLLB": 80},
                updated_at=datetime.utcnow().isoformat()
            ),
            "copywriting": MarketInsight(
                category="copywriting",
                avg_bid=40.0,
                median_bid=35.0,
                min_bid=20.0,
                max_bid=120.0,
                competition_level=0.8,
                demand_trend="stable",
                skill_demand={"SEO": 110, "Marketing": 95, "GPT": 90},
                updated_at=datetime.utcnow().isoformat()
            ),
        }
        return fallback_map.get(category, MarketInsight(
            category=category,
            avg_bid=30.0,
            median_bid=25.0,
            min_bid=10.0,
            max_bid=100.0,
            competition_level=0.5,
            demand_trend="unknown",
            skill_demand={},
            updated_at=datetime.utcnow().isoformat()
        ))

    def get_competitive_bid_range(self, category: str, platform: Optional[str] = None) -> Tuple[float, float]:
        """
        Возвращает рекомендуемый диапазон ставки для победы в конкурсе.
        Используется BidAutomator.
        """
        insight = self.analyze_market(category, platform)
        lower = max(insight.min_bid, insight.median_bid * 0.85)
        upper = min(insight.max_bid, insight.median_bid * 1.15)
        return round(lower, 2), round(upper, 2)

    def export_insight(self, category: str, platform: Optional[str] = None) -> Dict[str, Any]:
        """Экспорт данных в JSON-совместимый формат."""
        insight = self.analyze_market(category, platform)
        return {
            "category": insight.category,
            "avg_bid": insight.avg_bid,
            "median_bid": insight.median_bid,
            "min_bid": insight.min_bid,
            "max_bid": insight.max_bid,
            "competition_level": insight.competition_level,
            "demand_trend": insight.demand_trend,
            "top_skills": sorted(insight.skill_demand.items(), key=lambda x: -x[1])[:5],
            "updated_at": insight.updated_at
        }