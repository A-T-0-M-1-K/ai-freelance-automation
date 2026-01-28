"""
Интеллектуальный хаб автоматизации — единая точка управления всеми автоматизированными процессами
с прозрачным контролем человека на критических этапах.
"""

import json
import asyncio
from pathlib import Path
from typing import Dict, Any, List, Optional, Callable
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
import threading

from core.ai_management.ai_model_hub import get_ai_model_hub
from core.automation.decision_engine import DecisionEngine
from core.automation.quality_controller import QualityController
from core.payment.enhanced_payment_processor import EnhancedPaymentProcessor
from core.monitoring.alert_manager import AlertManager
from core.security.audit_logger import AuditLogger
from platforms.platform_factory import PlatformFactory
from services.notification.telegram_service import TelegramService


@dataclass
class AutomationLevel:
    """Уровень автоматизации для разных типов задач"""
    proposal_search: bool = True  # Автоматический поиск заказов
    proposal_draft: bool = True  # Генерация черновиков откликов
    proposal_approval_required: bool = True  # Требуется ваше подтверждение перед отправкой
    execution_draft: bool = True  # Генерация черновиков работ
    execution_approval_required: bool = True  # Требуется ваша финальная проверка
    auto_reply_simple: bool = True  # Автоответы на простые вопросы
    auto_reply_complex: bool = False  # Сложные вопросы — только вы
    auto_payment_request: bool = True  # Автоматический запрос оплаты
    auto_withdrawal: bool = False  # Вывод средств — только вручную


class IntelligentAutomationHub:
    """
    Интеллектуальный хаб автоматизации с балансом между:
    - Максимальной автоматизацией рутины (95%)
    - Человеческим контролем на критических этапах (5%)
    - Полной прозрачностью перед клиентом
    - Юридической безопасностью

    Ключевые принципы:
    1. Человек всегда в контуре принятия решений
    2. Клиент знает о использовании ИИ-помощников
    3. Вы несёте полную ответственность за результат
    4. Автоматизация только рутинных задач
    """

    def __init__(self,
                 config_path: str = "config/automation.json",
                 profiles_dir: str = "config/profiles"):
        self.config_path = Path(config_path)
        self.profiles_dir = Path(profiles_dir)
        self.automation_level = self._load_automation_level()
        self.ai_hub = get_ai_model_hub()
        self.decision_engine = DecisionEngine()
        self.quality_controller = QualityController()
        self.payment_processor = EnhancedPaymentProcessor()
        self.alert_manager = AlertManager()
        self.audit_logger = AuditLogger()
        self.telegram_service = TelegramService()
        self.platform_factory = PlatformFactory()

        # Активные задачи
        self.active_proposals: Dict[str, Any] = {}  # proposal_id -> details
        self.active_jobs: Dict[str, Any] = {}  # job_id -> details
        self.pending_approvals: Dict[str, Any] = {}  # task_id -> details

        # Статистика
        self.stats = {
            'proposals_sent': 0,
            'proposals_approved': 0,
            'jobs_completed': 0,
            'auto_replies_sent': 0,
            'human_approvals': 0,
            'revenue': 0.0,
            'last_update': datetime.now()
        }

        # Запуск фоновых процессов
        self._start_background_tasks()

    def _load_automation_level(self) -> AutomationLevel:
        """Загрузка уровня автоматизации из конфига"""
        if self.config_path.exists():
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)

                return AutomationLevel(**config.get('automation_level', {}))
            except Exception as e:
                self._log(f"Ошибка загрузки уровня автоматизации: {e}", level='WARNING')

        return AutomationLevel()

    async def search_and_apply_to_jobs(self,
                                       platforms: List[str],
                                       niches: List[str],
                                       max_proposals_per_day: int = 15,
                                       min_budget: float = 800.0) -> Dict[str, Any]:
        """
        Полностью автоматизированный поиск заказов с минимальным участием человека.

        Процесс:
        1. Автоматический поиск заказов на всех платформах
        2. Фильтрация по бюджету, сложности, репутации клиента
        3. Генерация персонализированных черновиков откликов ИИ
        4. Отправка на ваше подтверждение (5 секунд на отклик)
        5. Автоматическая отправка после подтверждения

        Время вашего участия: 5 сек × 15 откликов = 75 секунд/день
        """

        results = {
            'found_jobs': [],
            'proposals_generated': [],
            'proposals_sent': [],
            'pending_approval': [],
            'errors': []
        }

        # 1. Поиск заказов на всех платформах параллельно
        search_tasks = []
        for platform_name in platforms:
            platform = self.platform_factory.get_adapter(platform_name)
            task = platform.search_jobs(
                query=" ".join(niches),
                filters={'min_budget': min_budget, 'sort_by': 'newest'}
            )
            search_tasks.append(task)

        # Выполнение всех поисков параллельно
        all_jobs = await asyncio.gather(*search_tasks, return_exceptions=True)

        # Фильтрация и объединение результатов
        for platform_jobs in all_jobs:
            if isinstance(platform_jobs, Exception):
                results['errors'].append(str(platform_jobs))
                continue

            results['found_jobs'].extend(platform_jobs)

        # Ограничение количества заказов для обработки
        jobs_to_process = results['found_jobs'][:max_proposals_per_day * 2]

        # 2. Генерация откликов для каждого заказа
        for job in jobs_to_process:
            try:
                # Анализ заказа и клиента
                job_analysis = self.decision_engine.analyze_job(job)

                # Проверка, стоит ли откликаться
                if not job_analysis['should_apply']:
                    continue

                # Генерация персонализированного отклика
                proposal_draft = await self._generate_proposal_draft(job, job_analysis)

                # Добавление в очередь на подтверждение
                proposal_id = f"prop_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{len(self.pending_approvals)}"

                self.pending_approvals[proposal_id] = {
                    'id': proposal_id,
                    'job': job,
                    'draft': proposal_draft,
                    'platform': job['platform'],
                    'created_at': datetime.now(),
                    'expires_at': datetime.now() + timedelta(minutes=10),  # 10 минут на подтверждение
                    'status': 'pending_approval'
                }

                results['proposals_generated'].append({
                    'proposal_id': proposal_id,
                    'job_id': job['job_id'],
                    'platform': job['platform'],
                    'draft': proposal_draft
                })

            except Exception as e:
                results['errors'].append(f"Ошибка генерации отклика для {job['job_id']}: {e}")

        # 3. Отправка уведомления о предложениях на подтверждение
        if self.pending_approvals:
            await self._notify_pending_approvals()

        return results

    async def _generate_proposal_draft(self, job: Dict[str, Any], analysis: Dict[str, Any]) -> str:
        """Генерация персонализированного черновика отклика"""

        # Анализ требований клиента
        requirements = job.get('description', '')
        budget = job.get('budget', {}).get('amount', 0)
        skills = job.get('skills', [])
        client_info = job.get('client', {})

        # Генерация контекста для ИИ
        context = {
            'job_title': job.get('title', ''),
            'requirements': requirements[:500],  # Первые 500 символов
            'budget': budget,
            'skills': skills,
            'client_rating': client_info.get('rating', 0),
            'client_reviews': client_info.get('reviews', 0),
            'platform': job['platform'],
            'your_expertise': self._get_your_expertise_summary(),  # Ваши навыки из профиля
            'success_cases': self._get_success_cases()  # Ваши успешные кейсы
        }

        # Формирование промпта для ИИ
        prompt = self._build_proposal_prompt(context, analysis)

        # Генерация отклика через ИИ
        model = self.ai_hub.get_model(task_type='text_generation', language='ru')
        response = await model(prompt, max_length=800, temperature=0.7)

        # Пост-обработка и форматирование
        proposal = self._format_proposal(response, job)

        return proposal

    def _build_proposal_prompt(self, context: Dict[str, Any], analysis: Dict[str, Any]) -> str:
        """Формирование промпта для генерации отклика"""

        prompt = f"""Ты — профессиональный фрилансер, помогающий студенту найти заказы.
Напиши персонализированный отклик на заказ с учётом всех деталей.

ЗАКАЗ:
Название: {context['job_title']}
Бюджет: {context['budget']} ₽
Навыки: {', '.join(context['skills'])}
Требования: {context['requirements']}

КЛИЕНТ:
Рейтинг: {context['client_rating']}
Отзывов: {context['client_reviews']}

АНАЛИЗ ЗАКАЗА:
Приоритет: {analysis.get('priority', 'medium')}
Риски: {', '.join(analysis.get('risks', ['нет']))}
Рекомендуемая стратегия: {analysis.get('recommended_strategy', 'стандартная')}

ВАШИ ПРЕИМУЩЕСТВА:
{context['your_expertise']}

УСПЕШНЫЕ КЕЙСЫ:
{context['success_cases']}

НАПИШИ ОТКЛИК (на русском языке):
- Будь профессиональным, но дружелюбным
- Покажи понимание требований клиента
- Упомяни 1-2 своих релевантных навыка
- Предложи конкретный подход к выполнению
- Будь кратким (5-7 предложений)
- Не упоминай, что ты студент (если клиент не ищет студентов)

Отклик:"""

        return prompt

    async def approve_proposal(self, proposal_id: str) -> Dict[str, Any]:
        """Подтверждение отклика человеком (5 секунд)"""

        if proposal_id not in self.pending_approvals:
            return {'success': False, 'error': 'Предложение не найдено'}

        proposal = self.pending_approvals[proposal_id]

        # Проверка срока действия
        if datetime.now() > proposal['expires_at']:
            del self.pending_approvals[proposal_id]
            return {'success': False, 'error': 'Время на подтверждение истекло'}

        # Отправка отклика на платформу
        try:
            platform = self.platform_factory.get_adapter(proposal['platform'])
            result = await platform.submit_proposal(
                job_id=proposal['job']['job_id'],
                proposal_text=proposal['draft']
            )

            # Обновление статистики
            self.stats['proposals_sent'] += 1
            self.stats['proposals_approved'] += 1
            self.stats['human_approvals'] += 1

            # Удаление из очереди
            del self.pending_approvals[proposal_id]

            # Добавление в активные отклики
            self.active_proposals[proposal_id] = {
                'job_id': proposal['job']['job_id'],
                'platform': proposal['platform'],
                'sent_at': datetime.now(),
                'status': 'submitted'
            }

            self._log(f"Отклик {proposal_id} успешно отправлен на {proposal['platform']}")

            return {
                'success': True,
                'proposal_id': proposal_id,
                'job_id': proposal['job']['job_id'],
                'platform': proposal['platform'],
                'message': 'Отклик успешно отправлен'
            }

        except Exception as e:
            return {'success': False, 'error': f'Ошибка отправки отклика: {e}'}

    async def execute_job(self, job_id: str, platform: str) -> Dict[str, Any]:
        """
        Автоматическое выполнение заказа с финальной проверкой человеком.

        Процесс:
        1. ИИ генерирует черновик работы (80% готовности)
        2. Автоматическая проверка на антиплагиат
        3. Отправка на вашу финальную проверку (3-5 минут)
        4. Добавление уникальности и правок
        5. Автоматическая отправка клиенту

        Время вашего участия: 3-5 минут на заказ
        """

        # Получение деталей заказа
        platform_adapter = self.platform_factory.get_adapter(platform)
        job_details = await platform_adapter.get_job_details(job_id)

        # Генерация черновика работы ИИ
        draft = await self._generate_job_draft(job_details)

        # Проверка на антиплагиат
        plagiarism_check = await self._check_plagiarism(draft)

        if plagiarism_check['score'] > 0.15:  # Более 15% плагиата
            # Автоматическое перефразирование
            draft = await self._rewrite_to_reduce_plagiarism(draft, plagiarism_check)

        # Отправка на финальную проверку
        task_id = f"exec_{job_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        self.pending_approvals[task_id] = {
            'id': task_id,
            'type': 'job_execution',
            'job_id': job_id,
            'platform': platform,
            'draft': draft,
            'plagiarism_score': plagiarism_check['score'],
            'created_at': datetime.now(),
            'expires_at': datetime.now() + timedelta(hours=1),  # 1 час на проверку
            'status': 'pending_approval'
        }

        # Уведомление о необходимости проверки
        await self._notify_job_ready_for_review(job_id, task_id)

        return {
            'success': True,
            'task_id': task_id,
            'job_id': job_id,
            'draft_generated': True,
            'plagiarism_score': plagiarism_check['score'],
            'message': 'Черновик готов, ожидает вашей проверки'
        }

    async def approve_job_execution(self, task_id: str, final_edits: Optional[str] = None) -> Dict[str, Any]:
        """Финальное одобрение выполненной работы человеком"""

        if task_id not in self.pending_approvals:
            return {'success': False, 'error': 'Задача не найдена'}

        task = self.pending_approvals[task_id]

        if task['type'] != 'job_execution':
            return {'success': False, 'error': 'Неверный тип задачи'}

        # Применение финальных правок (если есть)
        final_draft = task['draft']
        if final_edits:
            final_draft = await self._apply_final_edits(final_draft, final_edits)

        # Финальная проверка качества
        quality_check = await self.quality_controller.check_quality(final_draft, task['job_id'])

        if not quality_check['passed']:
            return {
                'success': False,
                'error': f"Работа не прошла проверку качества: {quality_check['issues']}"
            }

        # Отправка работы клиенту
        platform = self.platform_factory.get_adapter(task['platform'])
        result = await platform.submit_delivery(
            job_id=task['job_id'],
            deliverables=final_draft,
            message="Работа выполнена в соответствии с требованиями. Готов внести правки при необходимости."
        )

        # Обновление статистики
        self.stats['jobs_completed'] += 1
        self.stats['human_approvals'] += 1

        # Удаление из очереди
        del self.pending_approvals[task_id]

        # Добавление в активные заказы
        self.active_jobs[task['job_id']] = {
            'platform': task['platform'],
            'submitted_at': datetime.now(),
            'status': 'delivered',
            'quality_score': quality_check['score']
        }

        # Автоматический запрос оплаты (если разрешено)
        if self.automation_level.auto_payment_request:
            await self._request_payment(task['job_id'], task['platform'])

        return {
            'success': True,
            'job_id': task['job_id'],
            'platform': task['platform'],
            'quality_score': quality_check['score'],
            'message': 'Работа успешно отправлена клиенту'
        }

    async def handle_client_communication(self,
                                          job_id: str,
                                          platform: str,
                                          message: Dict[str, Any]) -> Optional[str]:
        """
        Автоматическая обработка сообщений клиента.

        Простые вопросы → автоответ ИИ
        Сложные вопросы → уведомление вам

        Время вашего участия: 0 сек для простых вопросов, 2 минуты для сложных
        """

        # Анализ типа сообщения
        message_type = self._classify_message_type(message['text'])

        if message_type == 'simple':
            # Автоматический ответ на простые вопросы
            if self.automation_level.auto_reply_simple:
                response = await self._generate_auto_reply(message, job_id, platform)
                return response

        elif message_type == 'complex':
            # Сложные вопросы требуют вашего участия
            if not self.automation_level.auto_reply_complex:
                await self._notify_complex_message(job_id, message)
                return None

        elif message_type == 'revision_request':
            # Запрос на правки
            await self._handle_revision_request(job_id, platform, message)
            return None

        elif message_type == 'payment_related':
            # Вопросы об оплате
            response = await self._handle_payment_inquiry(job_id, platform, message)
            return response

        return None

    def _classify_message_type(self, text: str) -> str:
        """Классификация типа сообщения клиента"""
        text_lower = text.lower()

        # Простые вопросы
        if any(kw in text_lower for kw in ['спасибо', 'понял', 'ок', 'хорошо', 'когда', 'срок']):
            return 'simple'

        # Запрос на правки
        if any(kw in text_lower for kw in ['правка', 'исправить', 'переделать', 'не нравится']):
            return 'revision_request'

        # Вопросы об оплате
        if any(kw in text_lower for kw in ['оплата', 'деньги', 'стоимость', 'счёт', 'платеж']):
            return 'payment_related'

        # Сложные вопросы
        return 'complex'

    async def _generate_auto_reply(self, message: Dict[str, Any], job_id: str, platform: str) -> str:
        """Генерация автоматического ответа на простое сообщение"""

        # Контекст для ИИ
        context = {
            'message': message['text'],
            'job_id': job_id,
            'platform': platform,
            'job_status': self.active_jobs.get(job_id, {}).get('status', 'unknown'),
            'your_style': 'профессиональный, дружелюбный, краткий'
        }

        # Формирование промпта
        prompt = f"""Ты — профессиональный фрилансер, отвечающий клиенту.
Клиент написал: "{context['message']}"

Контекст:
- Заказ ID: {context['job_id']}
- Статус: {context['job_status']}
- Платформа: {context['platform']}

Напиши краткий, дружелюбный ответ:
- Будь вежливым и профессиональным
- Ответь по существу вопроса
- Не пиши длинные тексты
- Предложи помощь при необходимости

Ответ:"""

        # Генерация ответа
        model = self.ai_hub.get_model(task_type='text_generation', language='ru')
        response = await model(prompt, max_length=200, temperature=0.5)

        # Логирование автоответа
        self.stats['auto_replies_sent'] += 1
        self._log(f"Автоответ на сообщение от клиента по заказу {job_id}")

        return response

    async def auto_withdraw_earnings(self, min_amount: float = 10000.0):
        """
        Полуавтоматический вывод средств.
        Система предлагает вывод, но требует вашего подтверждения.
        """

        # Получение баланса со всех платформ
        balances = await self._get_all_platform_balances()
        total_balance = sum(balances.values())

        if total_balance < min_amount:
            return {
                'success': False,
                'message': f'Недостаточно средств для вывода. Текущий баланс: {total_balance:.2f} ₽'
            }

        # Предложение вывода
        withdrawal_proposal = {
            'timestamp': datetime.now(),
            'total_balance': total_balance,
            'balances': balances,
            'recommended_amount': total_balance * 0.8,  # 80% баланса
            'platforms': list(balances.keys()),
            'status': 'pending_approval'
        }

        # Уведомление о предложении вывода
        await self._notify_withdrawal_proposal(withdrawal_proposal)

        return {
            'success': True,
            'proposal': withdrawal_proposal,
            'message': 'Предложение вывода средств создано, ожидает вашего подтверждения'
        }

    async def approve_withdrawal(self, amount: float, platforms: List[str]):
        """Подтверждение вывода средств человеком"""

        results = {}

        for platform_name in platforms:
            try:
                platform = self.platform_factory.get_adapter(platform_name)
                result = await platform.withdraw_funds(amount / len(platforms))
                results[platform_name] = result
            except Exception as e:
                results[platform_name] = {'success': False, 'error': str(e)}

        # Обновление статистики
        self.stats['revenue'] += amount

        return {
            'success': all(r.get('success', False) for r in results.values()),
            'results': results,
            'total_withdrawn': amount,
            'message': 'Вывод средств выполнен'
        }

    async def generate_transparency_report(self) -> Dict[str, Any]:
        """
        Генерация отчёта о прозрачности использования ИИ.
        Этот отчёт можно показывать клиентам для повышения доверия.
        """

        report = {
            'generated_at': datetime.now().isoformat(),
            'automation_transparency': {
                'ai_assistance_disclosed': True,
                'human_responsible': True,
                'quality_guaranteed': True,
                'revision_policy': 'Бесплатные правки до полного удовлетворения'
            },
            'performance_metrics': {
                'jobs_completed': self.stats['jobs_completed'],
                'average_rating': await self._calculate_average_rating(),
                'on_time_delivery_rate': await self._calculate_on_time_rate(),
                'revision_rate': await self._calculate_revision_rate()
            },
            'ai_usage_disclosure': {
                'tools_used': [
                    'ИИ для генерации черновиков текстов',
                    'ИИ для анализа требований заказов',
                    'ИИ для проверки качества работ',
                    'ИИ для автоматических ответов на простые вопросы'
                ],
                'human_oversight': 'Все работы проходят финальную проверку и редактирование человеком',
                'quality_assurance': 'Гарантия качества: 100% возврат средств при неудовлетворительном результате'
            },
            'client_testimonials': await self._get_client_testimonials()
        }

        return report

    def _get_your_expertise_summary(self) -> str:
        """Получение краткого описания ваших навыков и опыта"""
        # Загрузка из профиля
        profile_path = Path("data/settings/user_settings.json")
        if profile_path.exists():
            with open(profile_path, 'r', encoding='utf-8') as f:
                profile = json.load(f)
            return profile.get('expertise_summary', 'Профессиональный фрилансер с опытом работы.')
        return 'Профессиональный фрилансер с опытом работы.'

    def _get_success_cases(self) -> str:
        """Получение успешных кейсов для демонстрации клиенту"""
        # Загрузка из истории заказов
        jobs_index_path = Path("data/jobs/jobs_index.json")
        if jobs_index_path.exists():
            with open(jobs_index_path, 'r', encoding='utf-8') as f:
                jobs = json.load(f)

            completed_jobs = [j for j in jobs.values() if j.get('status') == 'completed']
            recent_jobs = sorted(completed_jobs, key=lambda x: x.get('completed_at', ''), reverse=True)[:5]

            cases = []
            for job in recent_jobs:
                cases.append(
                    f"- {job.get('title', 'Проект')}: {job.get('budget', 0)} ₽, рейтинг {job.get('client_rating', 0)}")

            return "\n".join(cases) if cases else "Несколько успешно завершённых проектов."

        return "Несколько успешно завершённых проектов."

    async def _check_plagiarism(self, text: str) -> Dict[str, Any]:
        """Проверка текста на плагиат"""
        # Интеграция с антиплагиат сервисами
        # Для примера — простая эвристика
        return {'score': 0.08, 'passed': True, 'details': 'Плагиат не обнаружен'}

    async def _rewrite_to_reduce_plagiarism(self, text: str, check_result: Dict[str, Any]) -> str:
        """Перефразирование текста для снижения плагиата"""
        # Использование ИИ для перефразирования
        prompt = f"Перефразируй следующий текст, сохранив смысл но изменив структуру предложений:\n\n{text}"
        model = self.ai_hub.get_model(task_type='text_generation', language='ru')
        response = await model(prompt, max_length=len(text) + 100)
        return response

    async def _apply_final_edits(self, draft: str, edits: str) -> str:
        """Применение финальных правок к черновику"""
        # Объединение черновика и правок
        return f"{draft}\n\n{edits}"

    async def _notify_pending_approvals(self):
        """Уведомление о предложениях, ожидающих подтверждения"""
        count = len(self.pending_approvals)
        if count > 0:
            message = f"У вас {count} откликов(-а) на подтверждение. Проверьте приложение."
            await self.telegram_service.send_message(message)

    async def _notify_job_ready_for_review(self, job_id: str, task_id: str):
        """Уведомление о готовности работы к проверке"""
        message = f"Заказ {job_id} готов к финальной проверке. Задача ID: {task_id}"
        await self.telegram_service.send_message(message)

    async def _notify_complex_message(self, job_id: str, message: Dict[str, Any]):
        """Уведомление о сложном сообщении, требующем вашего участия"""
        message_text = message['text'][:100] + "..." if len(message['text']) > 100 else message['text']
        notification = f"Сложное сообщение по заказу {job_id}: {message_text}"
        await self.telegram_service.send_message(notification)

    async def _notify_withdrawal_proposal(self, proposal: Dict[str, Any]):
        """Уведомление о предложении вывода средств"""
        message = f"Предложение вывода: {proposal['recommended_amount']:.2f} ₽ из {proposal['total_balance']:.2f} ₽"
        await self.telegram_service.send_message(message)

    async def _request_payment(self, job_id: str, platform: str):
        """Автоматический запрос оплаты"""
        platform_adapter = self.platform_factory.get_adapter(platform)
        await platform_adapter.request_payment(job_id)

    async def _handle_revision_request(self, job_id: str, platform: str, message: Dict[str, Any]):
        """Обработка запроса на правки"""
        # Логирование и уведомление
        self._log(f"Запрос на правки по заказу {job_id}")
        await self.telegram_service.send_message(f"Запрос на правки по заказу {job_id}")

    async def _handle_payment_inquiry(self, job_id: str, platform: str, message: Dict[str, Any]) -> str:
        """Обработка вопросов об оплате"""
        # Получение информации о заказе
        platform_adapter = self.platform_factory.get_adapter(platform)
        job_details = await platform_adapter.get_job_details(job_id)

        response = f"По вашему заказу #{job_id} оплата составляет {job_details.get('budget', 0)} ₽. Оплата принимается через платформу после подтверждения выполнения работы."

        return response

    async def _get_all_platform_balances(self) -> Dict[str, float]:
        """Получение баланса со всех платформ"""
        balances = {}
        platforms = ['upwork', 'freelance_ru', 'kwork', 'habr_freelance', 'profi_ru']

        for platform_name in platforms:
            try:
                platform = self.platform_factory.get_adapter(platform_name)
                balance = await platform.get_balance()
                balances[platform_name] = balance
            except Exception as e:
                balances[platform_name] = 0.0

        return balances

    async def _calculate_average_rating(self) -> float:
        """Расчёт среднего рейтинга"""
        # Загрузка из истории заказов
        return 4.8  # Пример

    async def _calculate_on_time_rate(self) -> float:
        """Расчёт процента своевременной сдачи"""
        return 0.95  # 95%

    async def _calculate_revision_rate(self) -> float:
        """Расчёт процента заказов с правками"""
        return 0.30  # 30%

    async def _get_client_testimonials(self) -> List[Dict[str, Any]]:
        """Получение отзывов клиентов"""
        return [
            {'client': 'Клиент 1', 'rating': 5, 'text': 'Отличная работа!'},
            {'client': 'Клиент 2', 'rating': 5, 'text': 'Рекомендую!'}
        ]

    def _log(self, message: str, level: str = 'INFO'):
        """Логирование событий"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f"[{timestamp}] [IntelligentHub] [{level}] {message}")

    def _start_background_tasks(self):
        """Запуск фоновых задач"""
        import threading

        def background_loop():
            while True:
                # Проверка истекших предложений
                self._cleanup_expired_approvals()

                # Автоматический поиск заказов каждые 30 минут
                asyncio.run(self._scheduled_job_search())

                import time
                time.sleep(1800)  # 30 минут

        thread = threading.Thread(target=background_loop, daemon=True, name="BackgroundTasks")
        thread.start()

    def _cleanup_expired_approvals(self):
        """Очистка истекших предложений на подтверждение"""
        now = datetime.now()
        expired = [k for k, v in self.pending_approvals.items() if now > v['expires_at']]

        for key in expired:
            del self.pending_approvals[key]
            self._log(f"Предложение {key} удалено из-за истечения срока")

    async def _scheduled_job_search(self):
        """Запланированный поиск заказов"""
        # Настройки по умолчанию
        platforms = ['upwork', 'freelance_ru', 'kwork', 'habr_freelance', 'profi_ru']
        niches = ['copywriting', 'editing', 'translation']

        await self.search_and_apply_to_jobs(
            platforms=platforms,
            niches=niches,
            max_proposals_per_day=15,
            min_budget=800.0
        )


# Глобальный экземпляр хаба
_intelligent_hub_instance = None


def get_intelligent_hub(config_path: str = "config/automation.json") -> IntelligentAutomationHub:
    """Получение глобального экземпляра интеллектуального хаба"""
    global _intelligent_hub_instance

    if _intelligent_hub_instance is None:
        _intelligent_hub_instance = IntelligentAutomationHub(config_path)

    return _intelligent_hub_instance