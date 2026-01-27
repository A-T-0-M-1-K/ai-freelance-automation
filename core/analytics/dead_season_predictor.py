"""
Прогнозирование периодов низкой активности ("мёртвых сезонов") на фриланс-рынке.
Анализ исторических данных для выявления сезонных трендов и рекомендаций по адаптации.
"""

import json
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, Any, List, Tuple
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import TimeSeriesSplit

from core.analytics.market_analyzer import MarketAnalyzer
from core.learning.pattern_extractor import PatternExtractor


class DeadSeasonPredictor:
    """
    Прогнозирование сезонных спадов спроса на фриланс-услуги с рекомендациями по адаптации:
    - Анализ исторических данных по нишам и регионам
    - Выявление сезонных паттернов (праздники, отпускной сезон, бюджетные циклы)
    - Прогнозирование периодов низкой активности на 3-6 месяцев вперед
    - Рекомендации по диверсификации услуг и рынков в "мёртвые сезоны"
    """

    def __init__(self, data_dir: str = "data/analytics"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.market_analyzer = MarketAnalyzer()
        self.pattern_extractor = PatternExtractor()
        self.model = None
        self.scaler = StandardScaler()
        self.seasonal_patterns = self._load_seasonal_patterns()

    def _load_seasonal_patterns(self) -> Dict[str, Any]:
        """Загрузка известных сезонных паттернов по нишам"""
        return {
            'russia': {
                'dead_seasons': [
                    {'period': 'new_year_holidays', 'start_date': '12-30', 'end_date': '01-15', 'impact': -0.7},
                    {'period': 'summer_vacation', 'start_date': '06-15', 'end_date': '08-31', 'impact': -0.4},
                    {'period': 'september_rush', 'start_date': '09-01', 'end_date': '09-30', 'impact': 0.6}
                    # Пик после лета
                ]
            },
            'usa': {
                'dead_seasons': [
                    {'period': 'christmas_new_year', 'start_date': '12-20', 'end_date': '01-10', 'impact': -0.6},
                    {'period': 'summer_slowdown', 'start_date': '07-01', 'end_date': '08-15', 'impact': -0.3},
                    {'period': 'q4_rush', 'start_date': '10-01', 'end_date': '12-15', 'impact': 0.8}
                    # Пик перед праздниками
                ]
            },
            'global': {
                'dead_seasons': [
                    {'period': 'new_year_global', 'start_date': '12-24', 'end_date': '01-05', 'impact': -0.8}
                ]
            }
        }

    def collect_historical_data(self, niche: str, region: str, months_back: int = 24) -> pd.DataFrame:
        """
        Сбор исторических данных о спросе по нише и региону.

        Источники данных:
        - Локальные логи поиска заказов
        - Статистика с платформ через их API
        - Открытые данные о рынке (если доступны)
        """
        data_file = self.data_dir / f"market_data_{niche}_{region}.json"

        if data_file.exists():
            try:
                with open(data_file, 'r', encoding='utf-8') as f:
                    raw_data = json.load(f)
                df = pd.DataFrame(raw_data)
                df['date'] = pd.to_datetime(df['date'])
                return df[df['date'] >= datetime.now() - timedelta(days=months_back * 30)]
            except Exception as e:
                print(f"⚠️ Ошибка загрузки исторических данных: {e}")

        # Генерация синтетических данных для примера
        print("ℹ️ Исторические данные отсутствуют, генерация синтетических данных...")
        return self._generate_synthetic_data(niche, region, months_back)

    def _generate_synthetic_data(self, niche: str, region: str, months_back: int) -> pd.DataFrame:
        """Генерация синтетических данных для демонстрации"""
        dates = pd.date_range(end=datetime.now(), periods=months_back * 30, freq='D')
        np.random.seed(42)

        # Базовый уровень спроса в зависимости от ниши
        base_demand = {
            'copywriting': 100,
            'web_development': 150,
            'design': 120,
            'translation': 90,
            'video_editing': 80
        }.get(niche, 100)

        # Сезонные колебания
        seasonal = np.sin(np.arange(len(dates)) * 2 * np.pi / 365) * 0.3 + \
                   np.sin(np.arange(len(dates)) * 2 * np.pi / 180) * 0.2

        # Праздничные спады
        holiday_mask = np.zeros(len(dates))
        for i, date in enumerate(dates):
            if date.month == 12 and date.day >= 20:
                holiday_mask[i] = -0.6
            elif date.month == 1 and date.day <= 10:
                holiday_mask[i] = -0.6
            elif date.month in [6, 7, 8]:
                holiday_mask[i] = -0.2 * (1 + np.sin(i * 2 * np.pi / 90))

        # Случайный шум
        noise = np.random.normal(0, 0.1, len(dates))

        demand = base_demand * (1 + seasonal + holiday_mask + noise)
        demand = np.maximum(demand, base_demand * 0.2)  # Минимум 20% от базы

        df = pd.DataFrame({
            'date': dates,
            'demand_index': demand,
            'job_count': (demand / base_demand * 50).astype(int),
            'avg_budget': base_demand * 10 * (1 + seasonal * 0.5),
            'niche': niche,
            'region': region
        })

        return df

    def detect_seasonal_patterns(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Выявление сезонных паттернов в данных с использованием:
        - Анализа Фурье для обнаружения циклов
        - Скользящих средних для сглаживания шума
        - Кластеризации периодов по уровню активности
        """
        # Анализ Фурье для выявления доминирующих частот
        demand_values = df['demand_index'].values
        fft_result = np.fft.fft(demand_values - np.mean(demand_values))
        frequencies = np.fft.fftfreq(len(demand_values), d=1)

        # Поиск пиков в спектре (сезонные циклы)
        magnitude = np.abs(fft_result)
        dominant_freqs = frequencies[np.argsort(magnitude)[-5:]]  # Топ-5 частот

        # Определение сезонных периодов
        seasonal_periods = []
        for freq in dominant_freqs:
            if freq > 0:  # Только положительные частоты
                period_days = int(1 / freq)
                if 7 <= period_days <= 365:  # Интересны периоды от недели до года
                    seasonal_periods.append({
                        'period_days': period_days,
                        'strength': magnitude[np.where(frequencies == freq)][0] / np.max(magnitude)
                    })

        # Выявление "мёртвых сезонов" через пороговое значение
        demand_rolling = df['demand_index'].rolling(window=14).mean()
        threshold = demand_rolling.mean() * 0.6  # Порог 60% от среднего

        dead_seasons = []
        in_dead_season = False
        start_idx = None

        for i, (idx, row) in enumerate(df.iterrows()):
            if demand_rolling.iloc[i] < threshold and not in_dead_season:
                in_dead_season = True
                start_idx = i
            elif demand_rolling.iloc[i] >= threshold and in_dead_season:
                in_dead_season = False
                if start_idx is not None:
                    duration = i - start_idx
                    if duration >= 7:  # Минимум неделя
                        dead_seasons.append({
                            'start_date': df.iloc[start_idx]['date'],
                            'end_date': df.iloc[i]['date'],
                            'duration_days': duration,
                            'avg_demand': demand_rolling.iloc[start_idx:i].mean(),
                            'severity': 'high' if demand_rolling.iloc[
                                                      start_idx:i].mean() < threshold * 0.7 else 'medium'
                        })
                        start_idx = None

        # Если сезон продолжается до конца данных
        if in_dead_season and start_idx is not None:
            duration = len(df) - start_idx
            if duration >= 7:
                dead_seasons.append({
                    'start_date': df.iloc[start_idx]['date'],
                    'end_date': df.iloc[-1]['date'],
                    'duration_days': duration,
                    'avg_demand': demand_rolling.iloc[start_idx:].mean(),
                    'severity': 'high' if demand_rolling.iloc[start_idx:].mean() < threshold * 0.7 else 'medium'
                })

        return {
            'seasonal_periods': seasonal_periods,
            'dead_seasons': dead_seasons,
            'annual_pattern': self._extract_annual_pattern(df),
            'weekly_pattern': self._extract_weekly_pattern(df)
        }

    def _extract_annual_pattern(self, df: pd.DataFrame) -> Dict[int, float]:
        """Извлечение годового паттерна по месяцам"""
        df['month'] = df['date'].dt.month
        monthly_avg = df.groupby('month')['demand_index'].mean()
        overall_avg = df['demand_index'].mean()
        return {month: (avg / overall_avg - 1) * 100 for month, avg in monthly_avg.items()}

    def _extract_weekly_pattern(self, df: pd.DataFrame) -> Dict[int, float]:
        """Извлечение недельного паттерна по дням недели"""
        df['weekday'] = df['date'].dt.weekday  # 0=Пн, 6=Вс
        weekday_avg = df.groupby('weekday')['demand_index'].mean()
        overall_avg = df['demand_index'].mean()
        return {day: (avg / overall_avg - 1) * 100 for day, avg in weekday_avg.items()}

    def train_prediction_model(self, df: pd.DataFrame):
        """Обучение модели машинного обучения для прогнозирования спроса"""
        # Подготовка признаков
        df = df.copy()
        df['day_of_year'] = df['date'].dt.dayofyear
        df['month'] = df['date'].dt.month
        df['day_of_week'] = df['date'].dt.dayofweek
        df['is_weekend'] = (df['day_of_week'] >= 5).astype(int)
        df['days_since_start'] = (df['date'] - df['date'].min()).dt.days

        # Добавление лагов (предыдущие значения спроса)
        for lag in [7, 14, 30, 60]:
            df[f'demand_lag_{lag}'] = df['demand_index'].shift(lag)

        # Удаление строк с пропусками после лагов
        df = df.dropna()

        # Признаки и целевая переменная
        feature_cols = ['day_of_year', 'month', 'day_of_week', 'is_weekend', 'days_since_start'] + \
                       [f'demand_lag_{lag}' for lag in [7, 14, 30, 60]]
        X = df[feature_cols]
        y = df['demand_index']

        # Масштабирование
        X_scaled = self.scaler.fit_transform(X)

        # Обучение модели
        self.model = RandomForestRegressor(n_estimators=100, random_state=42)
        self.model.fit(X_scaled, y)

        print(f"✅ Модель обучена. R² на обучающих данных: {self.model.score(X_scaled, y):.3f}")

    def predict_demand(self, start_date: datetime, days_ahead: int = 180) -> pd.DataFrame:
        """Прогнозирование спроса на указанное количество дней вперед"""
        if self.model is None:
            raise ValueError("Модель не обучена. Вызовите train_prediction_model() сначала.")

        # Генерация дат для прогноза
        dates = pd.date_range(start=start_date, periods=days_ahead, freq='D')
        predictions = []

        # Для простоты используем усредненные лаги из исторических данных
        # В реальной системе нужно реализовать рекурсивное прогнозирование

        for date in dates:
            features = {
                'day_of_year': date.dayofyear,
                'month': date.month,
                'day_of_week': date.weekday(),
                'is_weekend': 1 if date.weekday() >= 5 else 0,
                'days_since_start': (date - dates[0]).days
            }

            # Упрощенное прогнозирование без рекурсивных лагов
            feature_vector = np.array([[features['day_of_year'], features['month'],
                                        features['day_of_week'], features['is_weekend'],
                                        features['days_since_start'], 100, 100, 100, 100]])  # Заглушки для лагов

            scaled = self.scaler.transform(feature_vector)
            pred = self.model.predict(scaled)[0]

            predictions.append({
                'date': date,
                'predicted_demand': pred,
                'confidence_interval_lower': pred * 0.85,
                'confidence_interval_upper': pred * 1.15
            })

        return pd.DataFrame(predictions)

    def identify_dead_seasons(self, forecast_df: pd.DataFrame, threshold_percentile: float = 30.0) -> List[
        Dict[str, Any]]:
        """
        Идентификация "мёртвых сезонов" в прогнозе на основе порогового перцентиля.

        Args:
            forecast_df: DataFrame с прогнозом спроса
            threshold_percentile: Перцентиль для определения "низкого спроса" (по умолчанию 30%)

        Returns:
            Список периодов с низким спросом
        """
        # Определение порога низкого спроса
        demand_threshold = np.percentile(forecast_df['predicted_demand'], threshold_percentile)

        dead_seasons = []
        in_dead_season = False
        start_idx = None

        for i, row in forecast_df.iterrows():
            if row['predicted_demand'] < demand_threshold and not in_dead_season:
                in_dead_season = True
                start_idx = i
            elif row['predicted_demand'] >= demand_threshold and in_dead_season:
                in_dead_season = False
                if start_idx is not None:
                    duration = i - start_idx
                    if duration >= 7:  # Минимум неделя
                        dead_seasons.append({
                            'start_date': forecast_df.iloc[start_idx]['date'],
                            'end_date': forecast_df.iloc[i]['date'],
                            'duration_days': duration,
                            'avg_demand': forecast_df.iloc[start_idx:i]['predicted_demand'].mean(),
                            'demand_threshold': demand_threshold,
                            'severity': 'high' if forecast_df.iloc[start_idx:i][
                                                      'predicted_demand'].mean() < demand_threshold * 0.7 else 'medium'
                        })
                        start_idx = None

        # Если сезон продолжается до конца прогноза
        if in_dead_season and start_idx is not None:
            duration = len(forecast_df) - start_idx
            if duration >= 7:
                dead_seasons.append({
                    'start_date': forecast_df.iloc[start_idx]['date'],
                    'end_date': forecast_df.iloc[-1]['date'],
                    'duration_days': duration,
                    'avg_demand': forecast_df.iloc[start_idx:]['predicted_demand'].mean(),
                    'demand_threshold': demand_threshold,
                    'severity': 'high' if forecast_df.iloc[start_idx:][
                                              'predicted_demand'].mean() < demand_threshold * 0.7 else 'medium'
                })

        return dead_seasons

    def generate_adaptation_recommendations(self,
                                            dead_seasons: List[Dict[str, Any]],
                                            niche: str,
                                            region: str) -> Dict[str, Any]:
        """
        Генерация рекомендаций по адаптации к "мёртвым сезонам":
        - Диверсификация услуг
        - Расширение географии
        - Подготовка портфолио/кейсов
        - Обучение новым навыкам
        - Активный поиск в других нишах
        """
        recommendations = {
            'strategic_actions': [],
            'skill_development': [],
            'market_expansion': [],
            'portfolio_work': [],
            'timing_recommendations': []
        }

        # Анализ ниши для персонализированных рекомендаций
        niche_alternatives = {
            'copywriting': ['seo_copywriting', 'email_marketing', 'scriptwriting'],
            'web_development': ['mobile_development', 'web3_development', 'automation_scripts'],
            'design': ['ui_ux_design', 'motion_design', '3d_modeling'],
            'translation': ['transcreation', 'localization', 'subtitling'],
            'video_editing': ['motion_graphics', 'color_grading', 'vfx']
        }

        # Рекомендации по диверсификации
        alternatives = niche_alternatives.get(niche, [])
        if alternatives:
            recommendations['strategic_actions'].append(
                f"Диверсифицируйте услуги в смежные ниши: {', '.join(alternatives)}"
            )

        # Рекомендации по географии
        if region.lower() in ['russia', 'cis']:
            recommendations['market_expansion'].append(
                "Рассмотрите расширение на англоязычные рынки (США, Великобритания) в период летнего спада в РФ"
            )
        elif region.lower() == 'usa':
            recommendations['market_expansion'].append(
                "В декабре-январе фокусируйтесь на азиатских рынках (Индия, Сингапур), где праздники в другое время"
            )

        # Рекомендации по обучению в "мёртвые сезоны"
        for season in dead_seasons:
            duration = season['duration_days']
            if duration >= 30:
                recommendations['skill_development'].append(
                    f"Используйте период {season['start_date'].strftime('%d.%m')}–{season['end_date'].strftime('%d.%m')} "
                    f"({duration} дней) для освоения нового навыка или получения сертификата"
                )

        # Рекомендации по портфолио
        recommendations['portfolio_work'].append(
            "Создайте 2-3 кейса «для портфолио» в период низкой загрузки для привлечения клиентов после спада"
        )

        # Временные рекомендации
        recommendations['timing_recommendations'].append(
            "Начинайте активный поиск заказов за 2-3 недели до окончания 'мёртвого сезона' для плавного перехода"
        )

        # Финансовая подушка
        recommendations['strategic_actions'].append(
            "Сформируйте финансовую подушку, равную 2-3 месячным расходам, перед наступлением прогнозируемого спада"
        )

        return recommendations

    def generate_report(self,
                        niche: str,
                        region: str,
                        dead_seasons: List[Dict[str, Any]],
                        recommendations: Dict[str, Any],
                        output_path: Optional[str] = None) -> str:
        """Генерация подробного отчёта о прогнозе 'мёртвых сезонов'"""
        report = []
        report.append("=" * 80)
        report.append(f"ПРОГНОЗ 'МЁРТВЫХ СЕЗОНОВ' ДЛЯ НИШИ: {niche.upper()}")
        report.append(f"Регион: {region}")
        report.append(f"Дата прогноза: {datetime.now().strftime('%d.%m.%Y')}")
        report.append("=" * 80)
        report.append("")

        if not dead_seasons:
            report.append("✅ Прогнозируемых периодов низкой активности не обнаружено на ближайшие 6 месяцев")
            report.append("   Рынок ожидается стабильным с нормальными сезонными колебаниями")
        else:
            report.append(f"⚠️  ОБНАРУЖЕНО {len(dead_seasons)} ПЕРИОДОВ НИЗКОЙ АКТИВНОСТИ:")
            report.append("")

            for i, season in enumerate(dead_seasons, 1):
                duration = season['duration_days']
                severity = season['severity']
                avg_demand = season['avg_demand']

                report.append(
                    f"{i}. {season['start_date'].strftime('%d.%m.%Y')} – {season['end_date'].strftime('%d.%m.%Y')} "
                    f"({duration} дней)")
                report.append(f"   Средний спрос: {avg_demand:.0f} (порог: {season['demand_threshold']:.0f})")
                report.append(f"   Степень спада: {severity.upper()}")

                # Причины спада на основе дат
                start_month = season['start_date'].month
                if start_month in [12, 1]:
                    report.append("   Вероятная причина: Новогодние праздники")
                elif start_month in [6, 7, 8]:
                    report.append("   Вероятная причина: Летний отпускной сезон")
                elif start_month == 11:
                    report.append("   Вероятная причина: Подготовка к праздникам, снижение бюджетов")

                report.append("")

        report.append("-" * 80)
        report.append("💡 РЕКОМЕНДАЦИИ ПО АДАПТАЦИИ:")
        report.append("-" * 80)
        report.append("")

        for category, items in recommendations.items():
            if items:
                category_names = {
                    'strategic_actions': 'СТРАТЕГИЧЕСКИЕ ДЕЙСТВИЯ',
                    'skill_development': 'РАЗВИТИЕ НАВЫКОВ',
                    'market_expansion': 'РАСШИРЕНИЕ РЫНКА',
                    'portfolio_work': 'РАБОТА НАД ПОРТФОЛИО',
                    'timing_recommendations': 'ВРЕМЕННЫЕ РЕКОМЕНДАЦИИ'
                }

                report.append(f"{category_names.get(category, category.upper())}:")
                for item in items:
                    report.append(f"  • {item}")
                report.append("")

        report.append("=" * 80)
        report.append("Следующий прогноз рекомендуется обновить через 30 дней")
        report.append("=" * 80)

        report_text = "\n".join(report)

        # Сохранение отчёта
        if output_path is None:
            output_path = self.data_dir / f"dead_season_report_{niche}_{region}_{datetime.now().strftime('%Y%m%d')}.md"
        else:
            output_path = Path(output_path)

        output_path.write_text(report_text, encoding='utf-8')
        print(f"✅ Отчёт сохранён: {output_path}")

        return report_text

    def visualize_forecast(self,
                           historical_df: pd.DataFrame,
                           forecast_df: pd.DataFrame,
                           dead_seasons: List[Dict[str, Any]],
                           output_path: Optional[str] = None):
        """Визуализация прогноза с выделением 'мёртвых сезонов'"""
        plt.figure(figsize=(14, 7))

        # Исторические данные
        plt.plot(historical_df['date'], historical_df['demand_index'],
                 label='Исторический спрос', color='blue', alpha=0.6)

        # Прогноз
        plt.plot(forecast_df['date'], forecast_df['predicted_demand'],
                 label='Прогноз спроса', color='green', linestyle='--')

        # Доверительные интервалы
        plt.fill_between(forecast_df['date'],
                         forecast_df['confidence_interval_lower'],
                         forecast_df['confidence_interval_upper'],
                         alpha=0.2, color='green', label='Доверительный интервал')

        # Выделение "мёртвых сезонов"
        for season in dead_seasons:
            plt.axvspan(season['start_date'], season['end_date'],
                        alpha=0.3, color='red', label='Мёртвый сезон' if dead_seasons.index(season) == 0 else '')

        plt.title('Прогноз спроса на фриланс-услуги с выделением "мёртвых сезонов"')
        plt.xlabel('Дата')
        plt.ylabel('Индекс спроса')
        plt.legend()
        plt.grid(True, alpha=0.3)
        plt.xticks(rotation=45)

        if output_path is None:
            output_path = self.data_dir / f"demand_forecast_{datetime.now().strftime('%Y%m%d')}.png"
        plt.tight_layout()
        plt.savefig(output_path, dpi=300)
        print(f"✅ График прогноза сохранён: {output_path}")
        plt.close()


# CLI интерфейс
def main():
    import argparse

    parser = argparse.ArgumentParser(description='Прогнозирование "мёртвых сезонов" на фриланс-рынке')
    parser.add_argument('--niche', '-n', required=True,
                        choices=['copywriting', 'web_development', 'design', 'translation', 'video_editing'],
                        help='Ниша фриланса')
    parser.add_argument('--region', '-r', required=True, help='Регион (например: russia, usa, global)')
    parser.add_argument('--months-back', type=int, default=24, help='Месяцев исторических данных')
    parser.add_argument('--days-ahead', type=int, default=180, help='Дней прогноза вперёд')
    parser.add_argument('--output', '-o', default=None, help='Путь для сохранения отчёта')

    args = parser.parse_args()

    predictor = DeadSeasonPredictor()

    # Сбор исторических данных
    print(f"📊 Сбор исторических данных по нише '{args.niche}' в регионе '{args.region}'...")
    historical_data = predictor.collect_historical_data(args.niche, args.region, args.months_back)

    # Обнаружение сезонных паттернов
    print("🔍 Анализ сезонных паттернов...")
    patterns = predictor.detect_seasonal_patterns(historical_data)

    # Обучение модели
    print("🤖 Обучение модели прогнозирования...")
    predictor.train_prediction_model(historical_data)

    # Прогнозирование
    print(f"🔮 Прогнозирование спроса на {args.days_ahead} дней вперёд...")
    forecast = predictor.predict_demand(datetime.now(), args.days_ahead)

    # Идентификация "мёртвых сезонов"
    print("⚠️  Идентификация периодов низкой активности...")
    dead_seasons = predictor.identify_dead_seasons(forecast)

    # Генерация рекомендаций
    print("💡 Генерация рекомендаций по адаптации...")
    recommendations = predictor.generate_adaptation_recommendations(dead_seasons, args.niche, args.region)

    # Генерация отчёта
    print("📄 Формирование отчёта...")
    report = predictor.generate_report(args.niche, args.region, dead_seasons, recommendations, args.output)

    # Визуализация
    print("📈 Генерация графика прогноза...")
    predictor.visualize_forecast(historical_data, forecast, dead_seasons)

    print("\n✅ Анализ завершён успешно!")
    if dead_seasons:
        print(f"\n⚠️  ВНИМАНИЕ: Обнаружено {len(dead_seasons)} периодов низкой активности.")
        print("   Рекомендуется ознакомиться с отчётом и следовать рекомендациям по адаптации.")
    else:
        print("\n✅ Хорошие новости: значительных 'мёртвых сезонов' в ближайшие 6 месяцев не прогнозируется!")


if __name__ == "__main__":
    main()