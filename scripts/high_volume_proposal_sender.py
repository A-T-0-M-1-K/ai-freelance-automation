#!/usr/bin/env python3
"""
МАКСИМАЛЬНО АГРЕССИВНАЯ СТРАТЕГИЯ: 15-20 откликов/день на ОДНОЙ платформе
для получения 5-10 заказов/день при конверсии 30-40%.

ВАЖНО: Используйте ТОЛЬКО на платформах с разрешенной автоматизацией
или с ручным подтверждением каждого отклика для избежания бана.
"""

import json
import time
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional
import sys

from platforms.platform_factory import PlatformFactory
from platforms.universal_scraper_adapter import get_scraper_adapter
from core.ai_management.ai_model_hub import get_ai_model_hub
from core.security.encryption_engine import EncryptionEngine
from services.notification.telegram_service import TelegramService


class HighVolumeProposalSender:
    """
    Система массовой отправки откликов с интеллектуальной оптимизацией:
    - Адаптивное время отправки (пик активности клиентов)
    - Персонализированные отклики через ИИ
    - Обход рейт-лимитов через рандомизацию
    - Автоматическое определение "горячих" заказов
    """

    # Оптимальные временные окна для отправки откликов (МСК)
    OPTIMAL_WINDOWS = [
        (9, 11),  # Утро: клиенты проверяют заказы
        (13, 15),  # После обеда: активность растет
        (18, 20)  # Вечер: финальный поиск перед завершением дня
    ]

    def __init__(self,
                 platform_name: str,
                 daily_limit: int = 15,
                 min_budget: float = 800.0,
                 use_scraper: bool = False,
                 human_approval: bool = True):
        self.platform_name = platform_name
        self.daily_limit = daily_limit
        self.min_budget = min_budget
        self.use_scraper = use_scraper
        self.human_approval = human_approval  # КРИТИЧЕСКИ ВАЖНО: требовать подтверждения

        # Инициализация компонентов
        if use_scraper:
            self.platform = get_scraper_adapter(platform_name)
        else:
            self.platform = PlatformFactory.get_adapter(platform_name)

        self.ai_hub = get_ai_model_hub()
        self.encryption_engine = EncryptionEngine()
        self.telegram = TelegramService()

        # Статистика
        self.stats = self._load_stats()
        self.proposals_queue = []

    def _load_stats(self) -> Dict[str, Any]:
        """Загрузка статистики отправленных откликов"""
        stats_file = Path(f"data/stats/proposals_{self.platform_name}.json")
        if stats_file.exists():
            try:
                return json.loads(stats_file.read_text(encoding='utf-8'))
            except:
                pass

        return {
            'date': datetime.now().date().isoformat(),
            'sent_today': 0,
            'sent_total': 0,
            'accepted_count': 0,
            'conversion_rate': 0.0,
            'avg_budget': 0.0,
            'last_reset': datetime.now().isoformat()
        }

    def _save_stats(self):
        """Сохранение статистики"""
        stats_file = Path(f"data/stats/proposals_{self.platform_name}.json")
        stats_file.parent.mkdir(parents=True, exist_ok=True)
        stats_file.write_text(json.dumps(self.stats, indent=2, ensure_ascii=False), encoding='utf-8')

    def _reset_daily_stats(self):
        """Сброс дневной статистики при смене дня"""
        today = datetime.now().date().isoformat()
        if self.stats['date'] != today:
            self.stats['date'] = today
            self.stats['sent_today'] = 0
            self.stats['last_reset'] = datetime.now().isoformat()
            self._save_stats()
            print(f"🔄 Сброс дневной статистики для {self.platform_name}")

    def can_send_proposal(self) -> bool:
        """Проверка возможности отправки отклика"""
        self._reset_daily_stats()

        if self.stats['sent_today'] >= self.daily_limit:
            print(f"🛑 Достигнут дневной лимит откликов ({self.daily_limit})")
            return False

        # Проверка оптимального временного окна
        now = datetime.now()
        current_hour = now.hour

        in_optimal_window = any(
            start <= current_hour < end
            for start, end in self.OPTIMAL_WINDOWS
        )

        if not in_optimal_window and not self.human_approval:
            print(f"⏰ Вне оптимального окна отправки. Текущее время: {now.strftime('%H:%M')}")
            print(f"   Оптимальные окна: {', '.join(f'{s}:00-{e}:00' for s, e in self.OPTIMAL_WINDOWS)}")
            return False

        return True

    def search_and_queue_proposals(self, niches: List[str] = None):
        """
        Поиск заказов и добавление в очередь на отправку.
        С фильтрацией через ИИ для повышения конверсии.
        """
        if not self.can_send_proposal():
            return

        print(f"\n🔍 Поиск заказов на {self.platform_name}...")

        # Аутентификация
        if not self.platform.is_authenticated:
            if not self.platform.authenticate():
                print("❌ Ошибка аутентификации")
                return

        # Поиск заказов
        try:
            jobs = self.platform.search_jobs(
                query=" ".join(niches) if niches else "копирайтинг рерайтинг тексты",
                filters={'min_budget': self.min_budget},
                max_results=50  # Ищем больше для фильтрации
            )

            print(f"✅ Найдено {len(jobs)} заказов")

            # Фильтрация и сортировка по приоритету
            prioritized_jobs = self._prioritize_jobs(jobs)

            # Добавление в очередь
            added = 0
            for job in prioritized_jobs:
                if len(self.proposals_queue) >= self.daily_limit:
                    break

                # Генерация персонализированного отклика
                proposal = self._generate_smart_proposal(job)

                self.proposals_queue.append({
                    'job': job,
                    'proposal_text': proposal,
                    'priority': job.get('ai_analysis', {}).get('priority', 0.5),
                    'generated_at': datetime.now().isoformat()
                })

                added += 1

            print(f"📥 Добавлено {added} заказов в очередь на отправку")

        except Exception as e:
            print(f"❌ Ошибка поиска заказов: {e}")
            import traceback
            traceback.print_exc()

    def _prioritize_jobs(self, jobs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Сортировка заказов по приоритету для максимальной конверсии"""
        # Фильтрация низкобюджетных и спама
        filtered = [
            job for job in jobs
            if job['budget']['amount'] >= self.min_budget
               and job.get('ai_analysis', {}).get('spam_probability', 0) < 0.5
        ]

        # Сортировка по приоритету ИИ
        filtered.sort(
            key=lambda x: x.get('ai_analysis', {}).get('priority', 0.5),
            reverse=True
        )

        return filtered[:self.daily_limit * 2]  # Берем с запасом

    def _generate_smart_proposal(self, job: Dict[str, Any]) -> str:
        """Генерация персонализированного отклика с использованием ИИ"""
        # Анализ требований клиента
        title = job['title']
        description = job.get('description', '')
        budget = job['budget']['amount']
        skills = ", ".join(job.get('skills', [])[:3])

        # Формирование контекста для ИИ
        context = {
            'job_title': title,
            'job_description': description[:300],
            'budget': budget,
            'skills': skills,
            'platform': self.platform_name,
            'your_expertise': self._get_user_expertise(),
            'success_cases': self._get_success_cases()
        }

        # Формирование промпта
        prompt = f"""Ты — профессиональный фрилансер с опытом работы.
Напиши краткий, но убедительный отклик на заказ.

ЗАКАЗ:
Название: {context['job_title']}
Бюджет: {context['budget']} ₽
Ключевые навыки: {context['skills']}

ОПИСАНИЕ (первые 300 символов):
{context['job_description']}

ТВОИ ПРЕИМУЩЕСТВА:
{context['your_expertise']}

УСПЕШНЫЕ КЕЙСЫ:
{context['success_cases']}

ТРЕБОВАНИЯ К ОТКЛИКУ:
- 4-6 предложений
- Покажи понимание задачи
- Упомяни 1-2 релевантных навыка
- Предложи конкретный подход
- Будь дружелюбным, но профессиональным
- Не упоминай, что ты студент или новичок

Отклик:"""

        # Генерация через ИИ
        try:
            model = self.ai_hub.get_model(task_type='text_generation', language='ru')
            response = model(prompt, max_length=400, temperature=0.7)

            # Очистка результата
            proposal = response[0]['generated_text'] if isinstance(response, list) else response
            proposal = proposal.strip()

            # Удаление артефактов
            if "Отклик:" in proposal:
                proposal = proposal.split("Отклик:", 1)[-1].strip()

            return proposal[:500]  # Ограничение длины

        except Exception as e:
            print(f"⚠️ Ошибка генерации отклика, использую шаблон: {e}")
            return self._generate_fallback_proposal(job)

    def _get_user_expertise(self) -> str:
        """Получение информации об экспертизе пользователя"""
        # Загрузка из профиля
        profile_path = Path("data/settings/user_settings.json")
        if profile_path.exists():
            try:
                profile = json.loads(profile_path.read_text(encoding='utf-8'))
                return profile.get('expertise_summary',
                                   'Опытный фрилансер с 2+ годами работы в сфере копирайтинга и рерайтинга.')
            except:
                pass

        return "Опытный фрилансер с 2+ годами работы в сфере копирайтинга и рерайтинга."

    def _get_success_cases(self) -> str:
        """Получение успешных кейсов"""
        return """- Написал серию статей для блога о недвижимости (+30% трафика)
- Создал продающие тексты для интернет-магазина (конверсия +15%)
- Подготовил контент для запуска нового SaaS-продукта"""

    def _generate_fallback_proposal(self, job: Dict[str, Any]) -> str:
        """Резервный шаблон отклика"""
        return f"""Здравствуйте!

Ваш заказ "{job['title']}" меня заинтересовал. Имею опыт в этой сфере и готов качественно выполнить задачу в срок.

Моя цена: {job['budget']['amount']} ₽. Срок выполнения: 2-3 дня.

Готов приступить к работе сразу после подтверждения. Буду рад обсудить детали!

С уважением,
Профессиональный фрилансер"""

    def send_proposals_from_queue(self):
        """Отправка откликов из очереди с ручным подтверждением"""
        if not self.proposals_queue:
            print("📭 Очередь откликов пуста")
            return

        print(f"\n📤 Отправка откликов из очереди ({len(self.proposals_queue)} заказов)...")

        sent_count = 0
        for item in self.proposals_queue[:]:
            if not self.can_send_proposal():
                break

            job = item['job']
            proposal_text = item['proposal_text']

            # Отображение заказа для подтверждения
            print("\n" + "=" * 60)
            print(f"📄 ЗАКАЗ: {job['title']}")
            print(f"💰 Бюджет: {job['budget']['amount']} ₽")
            print(f"🔗 URL: {job['url']}")
            print(f"\n📝 ОТКЛИК:")
            print(proposal_text)
            print("=" * 60)

            # Ручное подтверждение (КРИТИЧЕСКИ ВАЖНО для избежания бана)
            if self.human_approval:
                response = input("\nОтправить отклик? (y/n/skip): ").strip().lower()

                if response == 'n':
                    print("❌ Отправка отменена пользователем")
                    self.proposals_queue.remove(item)
                    continue
                elif response == 'skip':
                    print("⏭️ Пропущено пользователем")
                    self.proposals_queue.remove(item)
                    continue

            # Отправка отклика
            try:
                result = self.platform.submit_proposal(
                    job_id=job['job_id'],
                    proposal_text=proposal_text,
                    amount=job['budget']['amount']
                )

                if result.get('success'):
                    sent_count += 1
                    self.stats['sent_today'] += 1
                    self.stats['sent_total'] += 1

                    print(f"✅ Отклик #{sent_count} отправлен на заказ: {job['title'][:50]}...")

                    # Обновление статистики
                    self._save_stats()

                    # Удаление из очереди
                    self.proposals_queue.remove(item)

                    # Рандомная задержка между откликами (имитация человека)
                    delay = random.uniform(45, 90)  # 45-90 секунд
                    print(f"⏳ Следующий отклик через {delay:.0f} секунд...")
                    time.sleep(delay)

                else:
                    print(f"❌ Ошибка отправки: {result.get('error', 'Неизвестная ошибка')}")
                    # Не удаляем из очереди для повторной попытки

            except Exception as e:
                print(f"❌ Исключение при отправке: {e}")
                import traceback
                traceback.print_exc()

        print(f"\n✅ Отправлено {sent_count} откликов сегодня")

    def run_continuous_cycle(self, check_interval_minutes: int = 30):
        """
        Непрерывный цикл поиска и отправки откликов.

        Рекомендуемые настройки для максимальной конверсии:
        - Интервал проверки: 30 минут
        - Ежедневный лимит: 15-20 откликов
        - Время работы: 9:00 - 21:00 МСК
        """
        print(f"\n🚀 ЗАПУСК МАССОВОЙ ОТПРАВКИ ОТКЛИКОВ")
        print(f"   Платформа: {self.platform_name}")
        print(f"   Лимит в день: {self.daily_limit} откликов")
        print(f"   Минимальный бюджет: {self.min_budget} ₽")
        print(f"   Подтверждение человека: {'ДА' if self.human_approval else 'НЕТ'}")
        print(f"   Интервал проверки: {check_interval_minutes} минут")
        print("-" * 60)

        try:
            while True:
                current_time = datetime.now()

                # Проверка рабочего времени (9:00 - 21:00 МСК)
                if 9 <= current_time.hour < 21:
                    # Поиск новых заказов каждые N минут
                    self.search_and_queue_proposals(
                        niches=["копирайтинг", "рерайтинг", "тексты", "статьи"]
                    )

                    # Отправка откликов из очереди
                    if self.proposals_queue:
                        self.send_proposals_from_queue()

                else:
                    print(f"\n🌙 Вне рабочего времени ({current_time.strftime('%H:%M')}). Следующая проверка в 9:00")

                # Ожидание до следующей проверки
                print(f"\n⏳ Следующая проверка через {check_interval_minutes} минут...")
                time.sleep(check_interval_minutes * 60)

        except KeyboardInterrupt:
            print("\n\n🛑 Цикл остановлен пользователем")
        except Exception as e:
            print(f"\n❌ Критическая ошибка: {e}")
            import traceback
            traceback.print_exc()

    def generate_daily_report(self) -> str:
        """Генерация ежедневного отчёта"""
        report = f"""
╔════════════════════════════════════════════════════════════╗
║          ЕЖЕДНЕВНЫЙ ОТЧЁТ ПО ОТКЛИКАМ НА {self.platform_name.upper():<15} ║
╠════════════════════════════════════════════════════════════╣
║ Дата: {datetime.now().strftime('%d.%m.%Y %H:%M')}                    ║
║                                                              ║
║ Отправлено сегодня: {self.stats['sent_today']:>3} / {self.daily_limit:<3}                    ║
║ Всего отправлено:    {self.stats['sent_total']:>5}                          ║
║ Конверсия:           {self.stats['conversion_rate'] * 100:>5.1f}%                         ║
║ Средний бюджет:      {self.stats['avg_budget']:>7.0f} ₽                      ║
║                                                              ║
║ Очередь на отправку: {len(self.proposals_queue):>3} заказов                  ║
╚════════════════════════════════════════════════════════════╝
        """
        return report


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='Массовая отправка откликов для получения 5-10 заказов/день',
        epilog='Пример: python high_volume_proposal_sender.py --platform kwork --limit 15 --budget 800 --no-approval'
    )

    parser.add_argument('--platform', '-p', required=True,
                        help='Название платформы (kwork, freelance_ru, habr_freelance, profi_ru, avito_uslugi, youla_freelance)')
    parser.add_argument('--limit', '-l', type=int, default=15,
                        help='Лимит откликов в день (рекомендуется 15-20)')
    parser.add_argument('--budget', '-b', type=float, default=800.0,
                        help='Минимальный бюджет заказа в рублях')
    parser.add_argument('--scraper', '-s', action='store_true',
                        help='Использовать универсальный скрапер (для "серых" площадок)')
    parser.add_argument('--no-approval', action='store_true',
                        help='Отключить ручное подтверждение (ОПАСНО: риск бана!)')
    parser.add_argument('--interval', '-i', type=int, default=30,
                        help='Интервал проверки в минутах (по умолчанию: 30)')

    args = parser.parse_args()

    # Валидация параметров
    if args.limit > 25 and not args.no_approval:
        print("⚠️  Предупреждение: лимит >25 откликов/день без отключения подтверждения не рекомендуется")
        response = input("Продолжить? (y/n): ").strip().lower()
        if response != 'y':
            sys.exit(0)

    if args.no_approval:
        print("⚠️  ВНИМАНИЕ: Режим БЕЗ РУЧНОГО ПОДТВЕРЖДЕНИЯ АКТИВИРОВАН")
        print("⚠️  Это может привести к БАНУ аккаунта на платформе!")
        print("⚠️  Используйте ТОЛЬКО на платформах с разрешенной автоматизацией")
        response = input("\nВы уверены? (YES/no): ").strip().lower()
        if response != 'yes':
            print("Операция отменена")
            sys.exit(0)

    # Создание отправщика
    sender = HighVolumeProposalSender(
        platform_name=args.platform,
        daily_limit=args.limit,
        min_budget=args.budget,
        use_scraper=args.scraper,
        human_approval=not args.no_approval
    )

    # Запуск цикла
    print(sender.generate_daily_report())
    sender.run_continuous_cycle(check_interval_minutes=args.interval)


if __name__ == "__main__":
    main()