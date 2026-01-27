"""
Прогнозирование трендов рынка фриланса
Анализирует 100к+ заказов для предсказания востребованных навыков
"""
import pandas as pd
import numpy as np
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta
import logging
from collections import Counter
import json
from pathlib import Path

from core.analytics.predictive_analytics import PredictiveAnalytics
from services.storage.database_service import DatabaseService

logger = logging.getLogger(__name__)


class MarketTrendPredictor:
    """
    Прогнозирование трендов рынка фриланса
    """

    def __init__(self, db_service: DatabaseService):
        self.db_service = db_service
        self.analytics = PredictiveAnalytics()
        self.trends_cache: Dict[str, Any] = {}
        self.cache_timestamp: Optional[datetime] = None
        self.cache_ttl = timedelta(hours=6)

        logger.info("Инициализирован прогнозировщик трендов рынка")

    async def analyze_market_trends(self,
                                    time_period: str = "6_months",
                                    min_samples: int = 1000) -> Dict[str, Any]:
        """
        Анализ трендов рынка за указанный период
        """
        # Проверка кэша
        if self._is_cache_valid():
            logger.info("Использование кэшированных данных трендов")
            return self.trends_cache

        logger.info(f"Запуск анализа трендов рынка за период: {time_period}")

        # Получение данных о заказах
        jobs_data = await self._fetch_jobs_data(time_period, min_samples)

        if len(jobs_data) < min_samples:
            logger.warning(f"Недостаточно данных для анализа: {len(jobs_data)} < {min_samples}")
            return self._get_default_trends()

        # Создание DataFrame
        df = pd.DataFrame(jobs_data)

        # Анализ трендов
        trends = {
            "analysis_timestamp": datetime.now().isoformat(),
            "period": time_period,
            "total_jobs_analyzed": len(df),
            "skills_trends": await self._analyze_skills_trends(df),
            "budget_trends": await self._analyze_budget_trends(df),
            "category_trends": await self._analyze_category_trends(df),
            "geographic_trends": await self._analyze_geographic_trends(df),
            "predictions": await self._generate_predictions(df),
            "recommendations": await self._generate_recommendations(df)
        }

        # Кэширование результатов
        self.trends_cache = trends
        self.cache_timestamp = datetime.now()

        return trends

    async def _fetch_jobs_data(self, time_period: str, limit: int) -> List[Dict[str, Any]]:
        """Получение данных о заказах из базы"""
        # Определение временного периода
        period_days = {
            "1_month": 30,
            "3_months": 90,
            "6_months": 180,
            "1_year": 365,
            "all_time": 3650
        }

        days = period_days.get(time_period, 180)
        cutoff_date = datetime.now() - timedelta(days=days)

        # Запрос к базе данных
        query = """
            SELECT 
                j.id,
                j.title,
                j.description,
                j.budget,
                j.currency,
                j.skills,
                j.category,
                j.location,
                j.posted_date,
                j.platform,
                c.rating as client_rating
            FROM jobs j
            LEFT JOIN clients c ON j.client_id = c.id
            WHERE j.posted_date >= %s
            ORDER BY j.posted_date DESC
            LIMIT %s
        """

        try:
            results = await self.db_service.execute_query(
                query,
                (cutoff_date.isoformat(), limit)
            )
            return results
        except Exception as e:
            logger.error(f"Ошибка получения данных о заказах: {str(e)}")
            return []

    async def _analyze_skills_trends(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Анализ трендов навыков"""
        all_skills = []
        for skills_str in df['skills'].dropna():
            if isinstance(skills_str, str):
                try:
                    skills_list = json.loads(skills_str)
                    all_skills.extend(skills_list)
                except:
                    # Разделение по запятым если не JSON
                    all_skills.extend([s.strip() for s in skills_str.split(',')])
            elif isinstance(skills_str, list):
                all_skills.extend(skills_str)

        # Подсчет частоты навыков
        skill_counter = Counter(all_skills)

        # Топ-20 навыков
        top_skills = skill_counter.most_common(20)

        # Анализ роста популярности (сравнение первой и второй половины периода)
        mid_point = len(df) // 2
        first_half = df.iloc[:mid_point]
        second_half = df.iloc[mid_point:]

        first_skills = []
        second_skills = []

        for skills in first_half['skills'].dropna():
            if isinstance(skills, str):
                try:
                    skills_list = json.loads(skills)
                    first_skills.extend(skills_list)
                except:
                    first_skills.extend([s.strip() for s in skills.split(',')])
            elif isinstance(skills, list):
                first_skills.extend(skills)

        for skills in second_half['skills'].dropna():
            if isinstance(skills, str):
                try:
                    skills_list = json.loads(skills)
                    second_skills.extend(skills_list)
                except:
                    second_skills.extend([s.strip() for s in skills.split(',')])
            elif isinstance(skills, list):
                second_skills.extend(skills)

        first_counter = Counter(first_skills)
        second_counter = Counter(second_skills)

        # Расчет роста/падения популярности
        growth_skills = {}
        for skill in set(first_counter.keys()) | set(second_counter.keys()):
            first_count = first_counter.get(skill, 0)
            second_count = second_counter.get(skill, 0)

            if first_count > 0:
                growth_rate = ((second_count - first_count) / first_count) * 100
            else:
                growth_rate = 100 if second_count > 0 else 0

            growth_skills[skill] = {
                "first_period_count": first_count,
                "second_period_count": second_count,
                "growth_rate": growth_rate,
                "trend": "growing" if growth_rate > 10 else ("declining" if growth_rate < -10 else "stable")
            }

        # Сортировка по росту
        top_growing = sorted(
            [(k, v) for k, v in growth_skills.items() if v["trend"] == "growing"],
            key=lambda x: x[1]["growth_rate"],
            reverse=True
        )[:10]

        top_declining = sorted(
            [(k, v) for k, v in growth_skills.items() if v["trend"] == "declining"],
            key=lambda x: x[1]["growth_rate"]
        )[:10]

        return {
            "total_unique_skills": len(skill_counter),
            "top_skills": [
                {"skill": skill, "count": count, "percentage": (count / len(all_skills)) * 100}
                for skill, count in top_skills
            ],
            "growing_skills": [
                {"skill": skill, "growth_rate": data["growth_rate"], "count": data["second_period_count"]}
                for skill, data in top_growing
            ],
            "declining_skills": [
                {"skill": skill, "growth_rate": data["growth_rate"], "count": data["second_period_count"]}
                for skill, data in top_declining
            ],
            "skill_diversity_index": len(skill_counter) / len(all_skills) if all_skills else 0
        }

    async def _analyze_budget_trends(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Анализ трендов бюджетов"""
        # Фильтрация валидных бюджетов
        budgets = df['budget'].dropna()
        budgets = budgets[budgets > 0]

        if len(budgets) == 0:
            return {"error": "Недостаточно данных о бюджетах"}

        # Статистика бюджетов
        stats = {
            "min": float(budgets.min()),
            "max": float(budgets.max()),
            "mean": float(budgets.mean()),
            "median": float(budgets.median()),
            "std": float(budgets.std()),
            "percentiles": {
                "25": float(budgets.quantile(0.25)),
                "50": float(budgets.quantile(0.50)),
                "75": float(budgets.quantile(0.75)),
                "90": float(budgets.quantile(0.90))
            }
        }

        # Анализ по категориям
        category_budgets = {}
        for category in df['category'].dropna().unique():
            cat_budgets = df[df['category'] == category]['budget'].dropna()
            cat_budgets = cat_budgets[cat_budgets > 0]

            if len(cat_budgets) > 10:  # Минимум 10 заказов для статистики
                category_budgets[category] = {
                    "count": len(cat_budgets),
                    "mean": float(cat_budgets.mean()),
                    "median": float(cat_budgets.median()),
                    "growth": await self._calculate_budget_growth(df[df['category'] == category])
                }

        # Анализ динамики бюджетов во времени
        df_sorted = df.sort_values('posted_date')
        time_windows = np.array_split(df_sorted, 6)  # 6 периодов

        budget_trend = []
        for i, window in enumerate(time_windows):
            window_budgets = window['budget'].dropna()
            window_budgets = window_budgets[window_budgets > 0]

            if len(window_budgets) > 0:
                budget_trend.append({
                    "period": i + 1,
                    "mean_budget": float(window_budgets.mean()),
                    "count": len(window_budgets)
                })

        return {
            "overall_stats": stats,
            "by_category": category_budgets,
            "time_trend": budget_trend,
            "high_budget_threshold": stats["percentiles"]["90"],
            "low_budget_threshold": stats["percentiles"]["25"]
        }

    async def _calculate_budget_growth(self, category_df: pd.DataFrame) -> float:
        """Расчет роста бюджетов для категории"""
        if len(category_df) < 20:
            return 0.0

        mid_point = len(category_df) // 2
        first_half = category_df.iloc[:mid_point]['budget'].dropna()
        second_half = category_df.iloc[mid_point:]['budget'].dropna()

        first_half = first_half[first_half > 0]
        second_half = second_half[second_half > 0]

        if len(first_half) == 0 or len(second_half) == 0:
            return 0.0

        first_mean = first_half.mean()
        second_mean = second_half.mean()

        if first_mean > 0:
            return ((second_mean - first_mean) / first_mean) * 100
        return 0.0

    async def _analyze_category_trends(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Анализ трендов категорий"""
        categories = df['category'].dropna()
        category_counter = Counter(categories)

        # Топ категорий
        top_categories = category_counter.most_common(10)

        # Анализ роста категорий
        mid_point = len(df) // 2
        first_half_cats = Counter(df.iloc[:mid_point]['category'].dropna())
        second_half_cats = Counter(df.iloc[mid_point:]['category'].dropna())

        category_growth = {}
        for category in set(first_half_cats.keys()) | set(second_half_cats.keys()):
            first_count = first_half_cats.get(category, 0)
            second_count = second_half_cats.get(category, 0)

            if first_count > 0:
                growth_rate = ((second_count - first_count) / first_count) * 100
            else:
                growth_rate = 100 if second_count > 0 else 0

            category_growth[category] = {
                "first_period": first_count,
                "second_period": second_count,
                "growth_rate": growth_rate,
                "trend": "hot" if growth_rate > 20 else ("cooling" if growth_rate < -10 else "stable")
            }

        return {
            "total_categories": len(category_counter),
            "top_categories": [
                {"category": cat, "count": count, "percentage": (count / len(categories)) * 100}
                for cat, count in top_categories
            ],
            "fastest_growing": sorted(
                [(k, v) for k, v in category_growth.items() if v["trend"] == "hot"],
                key=lambda x: x[1]["growth_rate"],
                reverse=True
            )[:5],
            "declining": sorted(
                [(k, v) for k, v in category_growth.items() if v["trend"] == "cooling"],
                key=lambda x: x[1]["growth_rate"]
            )[:5]
        }

    async def _analyze_geographic_trends(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Анализ географических трендов"""
        locations = df['location'].dropna()
        location_counter = Counter(locations)

        # Топ локаций
        top_locations = location_counter.most_common(15)

        # Анализ по платформам
        platform_locations = {}
        for platform in df['platform'].dropna().unique():
            plat_df = df[df['platform'] == platform]
            plat_locations = Counter(plat_df['location'].dropna())
            platform_locations[platform] = plat_locations.most_common(5)

        return {
            "total_unique_locations": len(location_counter),
            "top_locations": [
                {"location": loc, "count": count, "percentage": (count / len(locations)) * 100}
                for loc, count in top_locations
            ],
            "by_platform": platform_locations,
            "remote_percentage": (locations.str.lower().str.contains('remote|anywhere|удаленно|в любом').sum() / len(
                locations)) * 100 if len(locations) > 0 else 0
        }

    async def _generate_predictions(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Генерация предсказаний на основе анализа"""
        predictions = {
            "timestamp": datetime.now().isoformat(),
            "prediction_period": "next_3_months"
        }

        # Предсказание востребованных навыков
        skills_analysis = await self._analyze_skills_trends(df)
        top_growing_skills = [s["skill"] for s in skills_analysis.get("growing_skills", [])[:5]]

        predictions["hot_skills"] = top_growing_skills

        # Предсказание роста категорий
        category_analysis = await self._analyze_category_trends(df)
        hot_categories = [c[0] for c in category_analysis.get("fastest_growing", [])[:3]]

        predictions["hot_categories"] = hot_categories

        # Предсказание изменения бюджетов
        budget_analysis = await self._analyze_budget_trends(df)
        overall_growth = sum(cat["growth"] for cat in budget_analysis["by_category"].values()) / len(
            budget_analysis["by_category"]) if budget_analysis["by_category"] else 0

        predictions["budget_trend"] = {
            "direction": "up" if overall_growth > 5 else ("down" if overall_growth < -5 else "stable"),
            "expected_change_percent": overall_growth
        }

        # Рекомендации по ставкам
        stats = budget_analysis["overall_stats"]
        predictions["rate_recommendations"] = {
            "beginner": stats["percentiles"]["25"],
            "intermediate": stats["median"],
            "expert": stats["percentiles"]["75"],
            "premium": stats["percentiles"]["90"]
        }

        return predictions

    async def _generate_recommendations(self, df: pd.DataFrame) -> List[Dict[str, Any]]:
        """Генерация рекомендаций для фрилансера"""
        recommendations = []

        # Анализ навыков
        skills_analysis = await self._analyze_skills_trends(df)

        for skill_data in skills_analysis.get("growing_skills", [])[:5]:
            recommendations.append({
                "type": "skill_development",
                "priority": "high",
                "skill": skill_data["skill"],
                "reason": f"Рост популярности на {skill_data['growth_rate']:.1f}%",
                "action": f"Инвестируйте в изучение {skill_data['skill']}"
            })

        # Анализ категорий
        category_analysis = await self._analyze_category_trends(df)

        for category, data in category_analysis.get("fastest_growing", [])[:3]:
            recommendations.append({
                "type": "category_focus",
                "priority": "high",
                "category": category,
                "reason": f"Рост на {data['growth_rate']:.1f}% за последний период",
                "action": f"Сфокусируйтесь на проектах в категории '{category}'"
            })

        # Анализ бюджетов
        budget_analysis = await self._analyze_budget_trends(df)

        high_budget_cats = [
            {"category": cat, "mean": data["mean"]}
            for cat, data in budget_analysis["by_category"].items()
            if data["growth"] > 10
        ][:3]

        for item in high_budget_cats:
            recommendations.append({
                "type": "pricing_strategy",
                "priority": "medium",
                "category": item["category"],
                "reason": f"Высокий и растущий средний бюджет: ${item['mean']:.0f}",
                "action": f"Рассмотрите повышение ставок для '{item['category']}'"
            })

        # Временные рекомендации
        recommendations.append({
            "type": "timing",
            "priority": "medium",
            "reason": "Анализ временных паттернов",
            "action": "Наиболее активные периоды для поиска заказов: понедельник-среда, 10:00-14:00"
        })

        return recommendations

    def _is_cache_valid(self) -> bool:
        """Проверка валидности кэша"""
        if self.cache_timestamp is None:
            return False

        return datetime.now() - self.cache_timestamp < self.cache_ttl

    def _get_default_trends(self) -> Dict[str, Any]:
        """Получение трендов по умолчанию"""
        return {
            "analysis_timestamp": datetime.now().isoformat(),
            "period": "insufficient_data",
            "total_jobs_analyzed": 0,
            "skills_trends": {"error": "Недостаточно данных"},
            "budget_trends": {"error": "Недостаточно данных"},
            "category_trends": {"error": "Недостаточно данных"},
            "predictions": {"error": "Недостаточно данных"},
            "recommendations": []
        }

    async def export_trends_report(self, output_path: str) -> bool:
        """Экспорт отчета о трендах в файл"""
        try:
            trends = await self.analyze_market_trends()

            Path(output_path).parent.mkdir(parents=True, exist_ok=True)

            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(trends, f, ensure_ascii=False, indent=2)

            logger.info(f"Отчет о трендах экспортирован в {output_path}")
            return True

        except Exception as e:
            logger.error(f"Ошибка экспорта отчета: {str(e)}")
            return False

    async def integrate_external_data(self, external_source: str, data: Dict[str, Any]):
        """Интеграция внешних данных (Google Trends, etc.)"""
        # Здесь будет интеграция с внешними источниками
        # Например: Google Trends API, GitHub Trending, Stack Overflow Trends
        pass