# Файл: core/automation/saga_orchestrator.py
"""
Оркестратор жизненного цикла задач по паттерну Сага
Обеспечивает:
- Атомарность операций через компенсирующие транзакции
- Автоматический откат при ошибках
- Сохранение состояния для восстановления после сбоев
- Параллельную обработку нескольких задач
- Интеграцию с блокчейном для неизменяемой истории
"""
import asyncio
import json
import logging
from enum import Enum
from typing import Dict, Any, Optional, List, Callable, Tuple
from datetime import datetime, timezone
from dataclasses import dataclass, asdict
from uuid import uuid4

from core.services.base_service import BaseService, ExecutionContext, ServiceResult
from core.payment.enhanced_payment_processor import EnhancedPaymentProcessor
from core.communication.empathetic_communicator import EmpatheticCommunicator
from services.ai_services.copywriting_service import CopywritingService
from services.ai_services.translation_service import TranslationService
from services.storage.database_service import DatabaseService
from blockchain.smart_contract_manager import SmartContractManager

logger = logging.getLogger(__name__)


class TaskPhase(Enum):
    """Фазы жизненного цикла задачи"""
    DISCOVERY = "discovery"  # Поиск и анализ заказа
    QUALIFICATION = "qualification"  # Оценка возможности выполнения
    BIDDING = "bidding"  # Подача предложения
    NEGOTIATION = "negotiation"  # Переговоры с клиентом
    CONTRACT_SIGNING = "contract_signing"  # Подписание контракта (блокчейн)
    PAYMENT_ESCROW = "payment_escrow"  # Депозит платежа в эскроу
    EXECUTION = "execution"  # Выполнение работы
    QUALITY_CHECK = "quality_check"  # Внутренняя проверка качества
    CLIENT_REVIEW = "client_review"  # Проверка клиентом
    REVISION = "revision"  # Работа над правками
    DELIVERY = "delivery"  # Финальная доставка
    PAYMENT_RELEASE = "payment_release"  # Выпуск платежа из эскроу
    FEEDBACK = "feedback"  # Получение отзыва
    NFT_MINTING = "nft_minting"  # Создание репутационного NFT
    COMPLETED = "completed"  # Успешное завершение
    FAILED = "failed"  # Неудачное завершение
    CANCELLED = "cancelled"  # Отмена задачи


@dataclass
class SagaStep:
    """Шаг саги с компенсирующей операцией"""
    phase: TaskPhase
    execute_fn: Callable  # Функция выполнения
    compensate_fn: Callable  # Функция отката
    description: str
    timeout: int = 300  # Таймаут в секундах
    retry_policy: Dict[str, Any] = None


@dataclass
class TaskState:
    """Полное состояние задачи для восстановления после сбоя"""
    task_id: str
    job_id: str
    current_phase: TaskPhase
    phase_start_time: datetime
    phase_attempts: int
    phase_data: Dict[str, Any]
    saga_steps_completed: List[TaskPhase]
    error_history: List[Dict[str, Any]]
    compensation_log: List[Dict[str, Any]]
    created_at: datetime
    updated_at: datetime
    blockchain_tx_hash: Optional[str] = None
    escrow_contract_address: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        # Конвертация datetime в ISO формат
        for key, value in data.items():
            if isinstance(value, datetime):
                data[key] = value.isoformat()
            elif isinstance(value, TaskPhase):
                data[key] = value.value
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TaskState':
        # Обратная конвертация из ISO формата
        for key in ['phase_start_time', 'created_at', 'updated_at']:
            if key in data and isinstance(data[key], str):
                data[key] = datetime.fromisoformat(data[key].replace('Z', '+00:00'))

        if 'current_phase' in data:
            data['current_phase'] = TaskPhase(data['current_phase'])

        if 'saga_steps_completed' in data:
            data['saga_steps_completed'] = [TaskPhase(p) for p in data['saga_steps_completed']]

        return cls(**data)


class SagaOrchestrator(BaseService):
    """
    Оркестратор жизненного цикла задач с поддержкой:
    - Распределенных транзакций через паттерн Сага
    - Автоматического отката при ошибках
    - Восстановления после сбоев
    - Интеграции с блокчейном для неизменяемой истории
    - Параллельной обработки задач
    """

    def __init__(self,
                 db_service: DatabaseService,
                 payment_processor: EnhancedPaymentProcessor,
                 communicator: EmpatheticCommunicator,
                 copywriting_service: CopywritingService,
                 translation_service: TranslationService,
                 blockchain_manager: Optional[SmartContractManager] = None):
        super().__init__(service_name="saga_orchestrator")
        self.db_service = db_service
        self.payment_processor = payment_processor
        self.communicator = communicator
        self.copywriting_service = copywriting_service
        self.translation_service = translation_service
        self.blockchain_manager = blockchain_manager
        self.active_tasks: Dict[str, TaskState] = {}
        self._task_locks: Dict[str, asyncio.Lock] = {}
        self._compensation_registry: Dict[TaskPhase, Callable] = {}

        # Регистрация компенсирующих операций
        self._register_compensation_handlers()

        logger.info("Инициализирован оркестратор жизненного цикла задач (паттерн Сага)")

    def _register_compensation_handlers(self):
        """Регистрация обработчиков компенсирующих операций для каждой фазы"""
        self._compensation_registry = {
            TaskPhase.CONTRACT_SIGNING: self._compensate_contract_signing,
            TaskPhase.PAYMENT_ESCROW: self._compensate_payment_escrow,
            TaskPhase.EXECUTION: self._compensate_execution,
            TaskPhase.DELIVERY: self._compensate_delivery,
            TaskPhase.PAYMENT_RELEASE: self._compensate_payment_release,
            TaskPhase.NFT_MINTING: self._compensate_nft_minting
        }

    async def _load_dependencies(self):
        """Инициализация зависимостей"""
        # Инициализация сервисов
        await self.copywriting_service.initialize()
        await self.translation_service.initialize()
        await self.communicator.initialize()

        self._initialized = True
        logger.info("Зависимости оркестратора жизненного цикла инициализированы")

    async def start_new_task(self, job_data: Dict[str, Any], platform: str) -> TaskState:
        """
        Запуск нового жизненного цикла задачи
        """
        task_id = str(uuid4())
        job_id = job_data.get('id') or job_data.get('job_id') or task_id

        context = ExecutionContext(
            task_id=task_id,
            job_id=job_id,
            platform=platform,
            metadata={
                "job_title": job_data.get('title', ''),
                "job_description": job_data.get('description', ''),
                "budget": job_data.get('budget'),
                "deadline": job_data.get('deadline'),
                "skills_required": job_data.get('skills', [])
            }
        )

        task_state = TaskState(
            task_id=task_id,
            job_id=job_id,
            current_phase=TaskPhase.DISCOVERY,
            phase_start_time=datetime.now(timezone.utc),
            phase_attempts=0,
            phase_data={"job_data": job_data, "platform": platform, "context": asdict(context)},
            saga_steps_completed=[],
            error_history=[],
            compensation_log=[],
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )

        # Сохранение начального состояния
        await self._save_task_state(task_state)
        self.active_tasks[task_id] = task_state

        # Создание блокировки для задачи
        self._task_locks[task_id] = asyncio.Lock()

        logger.info(f"Запущен новый жизненный цикл задачи {task_id} для заказа {job_id}")

        # Запуск асинхронной обработки в фоновом режиме
        asyncio.create_task(self._process_task_lifecycle(task_state, context))

        return task_state

    async def _process_task_lifecycle(self, task_state: TaskState, context: ExecutionContext):
        """
        Основной цикл обработки задачи с автоматическими переходами между фазами
        и поддержкой отката по паттерну Сага
        """
        max_attempts_per_phase = 3

        while task_state.current_phase not in [TaskPhase.COMPLETED, TaskPhase.FAILED, TaskPhase.CANCELLED]:
            current_phase = task_state.current_phase

            # Создание блокировки для предотвращения параллельной обработки одной задачи
            lock = self._task_locks.get(task_state.task_id)
            if lock is None:
                lock = asyncio.Lock()
                self._task_locks[task_state.task_id] = lock

            async with lock:
                try:
                    # Выполнение фазы
                    result = await self._execute_phase(current_phase, task_state, context)

                    if result.success:
                        # Успешное завершение фазы — переход к следующей
                        await self._handle_phase_success(task_state, current_phase, result, context)
                    else:
                        # Ошибка в фазе
                        task_state.phase_attempts += 1

                        if task_state.phase_attempts >= max_attempts_per_phase or result.rollback_required:
                            # Превышено количество попыток или требуется откат всей саги
                            await self._handle_saga_failure(task_state, current_phase, result.error, context)
                            break
                        else:
                            # Повторная попытка фазы
                            logger.warning(
                                f"Повторная попытка фазы {current_phase.value} для задачи {task_state.task_id} "
                                f"(попытка {task_state.phase_attempts}/{max_attempts_per_phase})"
                            )
                            await asyncio.sleep(2 ** (task_state.phase_attempts - 1))  # Экспоненциальная задержка

                except Exception as e:
                    logger.exception(
                        f"Необработанное исключение в фазе {current_phase.value} для задачи {task_state.task_id}")
                    await self._handle_saga_failure(task_state, current_phase, str(e), context)
                    break

            # Сохранение состояния после каждой фазы
            await self._save_task_state(task_state)

        # Финальные действия по завершению задачи
        await self._finalize_task(task_state, context)

    async def _execute_phase(self, phase: TaskPhase, task_state: TaskState,
                             context: ExecutionContext) -> ServiceResult:
        """
        Выполнение конкретной фазы жизненного цикла
        """
        phase_data = task_state.phase_data
        job_data = phase_data.get('job_data', {})

        try:
            if phase == TaskPhase.DISCOVERY:
                # Анализ заказа через ИИ
                analysis_prompt = f"""
                Проанализируй заказ для фрилансера:

                Название: {job_data.get('title', '')}
                Описание: {job_data.get('description', '')}
                Бюджет: {job_data.get('budget', 'не указан')}
                Сроки: {job_data.get('deadline', 'не указаны')}
                Навыки: {', '.join(job_data.get('skills', []))}

                Верни анализ в формате JSON:
                {{
                    "is_suitable": boolean,
                    "confidence": 0-100,
                    "suitable_skills": ["skill1", "skill2"],
                    "missing_skills": ["skill3"],
                    "budget_assessment": "low/medium/high",
                    "deadline_assessment": "tight/normal/loose",
                    "risk_factors": ["factor1", "factor2"],
                    "recommended_price": number,
                    "estimated_hours": number
                }}
                """

                result = await self.copywriting_service.generate_content(
                    prompt=analysis_prompt,
                    tone="analytical",
                    length=500,
                    context=context
                )

                if result.success:
                    try:
                        analysis = json.loads(result.data)
                        task_state.phase_data['job_analysis'] = analysis
                        return ServiceResult.success(
                            data=analysis,
                            context=context,
                            execution_time=0.0
                        )
                    except json.JSONDecodeError:
                        return ServiceResult.failure(
                            error="Не удалось распарсить анализ заказа",
                            error_type="JSONDecodeError",
                            stack_trace="",
                            context=context,
                            execution_time=0.0
                        )
                else:
                    return result

            elif phase == TaskPhase.QUALIFICATION:
                # Оценка возможности выполнения
                analysis = task_state.phase_data.get('job_analysis', {})
                is_suitable = analysis.get('is_suitable', False)
                confidence = analysis.get('confidence', 0)

                if not is_suitable or confidence < 60:
                    return ServiceResult.failure(
                        error="Заказ не подходит по критериям",
                        error_type="QualificationFailed",
                        stack_trace="",
                        context=context,
                        execution_time=0.0,
                        rollback_required=False  # Не требует отката — просто отказ
                    )

                # Проверка доступности навыков
                required_skills = analysis.get('suitable_skills', [])
                available_skills = await self._get_available_skills()

                missing_skills = [s for s in required_skills if s not in available_skills]
                if missing_skills:
                    return ServiceResult.failure(
                        error=f"Отсутствуют необходимые навыки: {', '.join(missing_skills)}",
                        error_type="MissingSkills",
                        stack_trace="",
                        context=context,
                        execution_time=0.0,
                        rollback_required=False
                    )

                qualification_result = {
                    "qualified": True,
                    "confidence": confidence,
                    "suitable_skills": required_skills,
                    "budget_recommendation": analysis.get('recommended_price'),
                    "time_estimate_hours": analysis.get('estimated_hours', 10)
                }

                task_state.phase_data['qualification_result'] = qualification_result
                return ServiceResult.success(
                    data=qualification_result,
                    context=context,
                    execution_time=0.0
                )

            elif phase == TaskPhase.BIDDING:
                # Генерация предложения через ИИ
                analysis = task_state.phase_data.get('job_analysis', {})
                qualification = task_state.phase_data.get('qualification_result', {})

                bid_prompt = f"""
                Напиши профессиональное предложение для заказа:

                Заказ: {job_data.get('title', '')}
                Описание: {job_data.get('description', '')[:200]}...
                Бюджет клиента: {job_data.get('budget', 'не указан')}
                Рекомендуемая цена: ${qualification.get('budget_recommendation', 'N/A')}
                Оценка времени: {qualification.get('time_estimate_hours', 'N/A')} часов

                Требования к предложению:
                - Персонализированное обращение к клиенту
                - Демонстрация понимания задачи
                - Описание подхода к решению
                - Упоминание релевантного опыта
                - Четкое указание сроков и цены
                - Призыв к действию

                Объем: 150-200 слов
                Тон: профессиональный, уверенный, но не агрессивный
                """

                result = await self.copywriting_service.generate_content(
                    prompt=bid_prompt,
                    tone="professional",
                    length=250,
                    context=context
                )

                if result.success:
                    bid_content = result.data

                    # Генерация структурированного предложения
                    bid_data = {
                        "cover_letter": bid_content,
                        "amount": qualification.get('budget_recommendation', job_data.get('budget', 100)),
                        "currency": job_data.get('currency', 'USD'),
                        "delivery_time_days": max(1, int(qualification.get('time_estimate_hours', 10) / 8)),
                        "skills_demonstrated": qualification.get('suitable_skills', [])
                    }

                    task_state.phase_data['bid_data'] = bid_data
                    return ServiceResult.success(
                        data=bid_data,
                        context=context,
                        execution_time=0.0
                    )
                else:
                    return result

            elif phase == TaskPhase.CONTRACT_SIGNING:
                # Подписание контракта через блокчейн
                if not self.blockchain_manager:
                    return ServiceResult.failure(
                        error="Блокчейн-менеджер не инициализирован",
                        error_type="BlockchainNotAvailable",
                        stack_trace="",
                        context=context,
                        execution_time=0.0,
                        rollback_required=True
                    )

                bid_data = task_state.phase_data.get('bid_data', {})
                contract_terms = {
                    "job_id": task_state.job_id,
                    "freelancer_address": context.user_id,  # Предполагается, что user_id = адрес кошелька
                    "client_address": job_data.get('client_address', '0x0'),
                    "amount": bid_data.get('amount', 0),
                    "currency": bid_data.get('currency', 'USD'),
                    "delivery_deadline": datetime.now(timezone.utc).timestamp() +
                                         (bid_data.get('delivery_time_days', 7) * 86400),
                    "milestones": [
                        {"percentage": 30, "description": "Предоплата"},
                        {"percentage": 70, "description": "После доставки"}
                    ]
                }

                # Деплой контракта (в реальной системе используется существующий шаблон)
                tx_hash = await self._deploy_job_contract(contract_terms)

                if tx_hash:
                    task_state.phase_data['contract_address'] = tx_hash
                    task_state.blockchain_tx_hash = tx_hash
                    return ServiceResult.success(
                        data={"contract_address": tx_hash, "terms": contract_terms},
                        context=context,
                        execution_time=0.0
                    )
                else:
                    return ServiceResult.failure(
                        error="Не удалось задеплоить контракт",
                        error_type="ContractDeploymentFailed",
                        stack_trace="",
                        context=context,
                        execution_time=0.0,
                        rollback_required=True
                    )

            elif phase == TaskPhase.PAYMENT_ESCROW:
                # Депозит платежа в эскроу
                contract_address = task_state.phase_data.get('contract_address')
                bid_data = task_state.phase_data.get('bid_data', {})

                if not contract_address:
                    return ServiceResult.failure(
                        error="Контракт не задеплоен",
                        error_type="ContractNotDeployed",
                        stack_trace="",
                        context=context,
                        execution_time=0.0,
                        rollback_required=True
                    )

                # В реальной системе здесь вызов смарт-контракта для депозита
                escrow_tx = await self._deposit_to_escrow(
                    contract_address=contract_address,
                    amount=bid_data.get('amount', 0),
                    currency=bid_data.get('currency', 'USD')
                )

                if escrow_tx:
                    task_state.escrow_contract_address = contract_address
                    task_state.phase_data['escrow_tx'] = escrow_tx
                    return ServiceResult.success(
                        data={"escrow_tx": escrow_tx, "contract_address": contract_address},
                        context=context,
                        execution_time=0.0
                    )
                else:
                    return ServiceResult.failure(
                        error="Не удалось депонировать платеж в эскроу",
                        error_type="EscrowDepositFailed",
                        stack_trace="",
                        context=context,
                        execution_time=0.0,
                        rollback_required=True
                    )

            elif phase == TaskPhase.EXECUTION:
                # Выполнение работы (интеграция с ИИ-сервисами)
                bid_data = task_state.phase_data.get('bid_data', {})
                skills = bid_data.get('skills_demonstrated', [])

                # Определение типа работы и выбор соответствующего ИИ-сервиса
                deliverables = {}

                if 'writing' in skills or 'copywriting' in skills:
                    content_prompt = f"Напиши качественный контент на тему: {job_data.get('description', '')[:100]}"
                    content_result = await self.copywriting_service.generate_content(
                        prompt=content_prompt,
                        tone="professional",
                        length=500,
                        context=context
                    )
                    if content_result.success:
                        deliverables['copywriting'] = content_result.data

                if 'translation' in skills:
                    source_text = job_data.get('source_text', 'Sample text for translation')
                    translation_result = await self.translation_service.translate_text(
                        text=source_text,
                        target_language=job_data.get('target_language', 'ru'),
                        context=context
                    )
                    if translation_result.success:
                        deliverables['translation'] = translation_result.data

                if 'editing' in skills:
                    text_to_edit = job_data.get('text_to_edit', 'Sample text for editing')
                    editing_result = await self.copywriting_service.improve_text(
                        text=text_to_edit,
                        context=context
                    )
                    if editing_result.success:
                        deliverables['editing'] = editing_result.data

                if deliverables:
                    task_state.phase_data['deliverables'] = deliverables
                    return ServiceResult.success(
                        data=deliverables,
                        context=context,
                        execution_time=0.0
                    )
                else:
                    return ServiceResult.failure(
                        error="Не удалось сгенерировать результаты работы",
                        error_type="ExecutionFailed",
                        stack_trace="",
                        context=context,
                        execution_time=0.0,
                        rollback_required=True
                    )

            # ... остальные фазы (сокращено для краткости) ...

            else:
                return ServiceResult.failure(
                    error=f"Неизвестная фаза: {phase.value}",
                    error_type="UnknownPhase",
                    stack_trace="",
                    context=context,
                    execution_time=0.0
                )

        except asyncio.TimeoutError:
            return ServiceResult.failure(
                error=f"Таймаут выполнения фазы {phase.value}",
                error_type="TimeoutError",
                stack_trace="",
                context=context,
                execution_time=0.0,
                rollback_required=True
            )
        except Exception as e:
            return ServiceResult.failure(
                error=f"Ошибка в фазе {phase.value}: {str(e)}",
                error_type=type(e).__name__,
                stack_trace="",
                context=context,
                execution_time=0.0,
                rollback_required=True
            )

    async def _handle_phase_success(self, task_state: TaskState, phase: TaskPhase,
                                    result: ServiceResult, context: ExecutionContext):
        """Обработка успешного завершения фазы и переход к следующей"""
        # Сохранение результатов фазы
        task_state.phase_data[f"{phase.value}_result"] = result.data
        task_state.saga_steps_completed.append(phase)

        # Определение следующей фазы
        next_phase = self._get_next_phase(phase, result.data)

        if next_phase:
            task_state.current_phase = next_phase
            task_state.phase_start_time = datetime.now(timezone.utc)
            task_state.phase_attempts = 0
            logger.info(f"Задача {task_state.task_id} перешла в фазу {next_phase.value}")
        else:
            # Завершение жизненного цикла
            task_state.current_phase = TaskPhase.COMPLETED
            logger.info(f"Жизненный цикл задачи {task_state.task_id} успешно завершен")

    def _get_next_phase(self, current_phase: TaskPhase, phase_result: Any) -> Optional[TaskPhase]:
        """Логика переходов между фазами с учетом результатов текущей фазы"""
        # Стандартный поток выполнения
        flow = {
            TaskPhase.DISCOVERY: TaskPhase.QUALIFICATION,
            TaskPhase.QUALIFICATION: TaskPhase.BIDDING,
            TaskPhase.BIDDING: TaskPhase.NEGOTIATION,
            TaskPhase.NEGOTIATION: TaskPhase.CONTRACT_SIGNING,
            TaskPhase.CONTRACT_SIGNING: TaskPhase.PAYMENT_ESCROW,
            TaskPhase.PAYMENT_ESCROW: TaskPhase.EXECUTION,
            TaskPhase.EXECUTION: TaskPhase.QUALITY_CHECK,
            TaskPhase.QUALITY_CHECK: TaskPhase.CLIENT_REVIEW,
            TaskPhase.CLIENT_REVIEW: TaskPhase.DELIVERY,
            TaskPhase.DELIVERY: TaskPhase.PAYMENT_RELEASE,
            TaskPhase.PAYMENT_RELEASE: TaskPhase.FEEDBACK,
            TaskPhase.FEEDBACK: TaskPhase.NFT_MINTING,
            TaskPhase.NFT_MINTING: TaskPhase.COMPLETED
        }

        # Специальная логика для отказа в квалификации
        if current_phase == TaskPhase.QUALIFICATION and isinstance(phase_result, dict):
            if not phase_result.get('qualified', False):
                logger.info(f"Заказ не прошел квалификацию — завершение жизненного цикла")
                return None  # Завершение без перехода

        # Специальная логика для правок
        if current_phase == TaskPhase.CLIENT_REVIEW and isinstance(phase_result, dict):
            if phase_result.get('requires_revision', False):
                return TaskPhase.REVISION

        if current_phase == TaskPhase.REVISION:
            return TaskPhase.QUALITY_CHECK  # Возврат на проверку после правок

        return flow.get(current_phase)

    async def _handle_saga_failure(self, task_state: TaskPhase,
                                   failed_phase: TaskPhase,
                                   error: str,
                                   context: ExecutionContext):
        """
        Обработка ошибки с выполнением компенсирующих операций по паттерну Сага
        """
        error_record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "phase": failed_phase.value,
            "error": error,
            "task_id": task_state.task_id
        }
        task_state.error_history.append(error_record)

        logger.error(f"Ошибка в фазе {failed_phase.value} задачи {task_state.task_id}: {error}")

        # Выполнение компенсирующих операций в обратном порядке
        compensation_errors = []

        for completed_phase in reversed(task_state.saga_steps_completed):
            if completed_phase in self._compensation_registry:
                try:
                    compensate_fn = self._compensation_registry[completed_phase]
                    compensation_result = await compensate_fn(task_state, context)

                    compensation_log = {
                        "phase": completed_phase.value,
                        "compensated_at": datetime.now(timezone.utc).isoformat(),
                        "success": compensation_result.get('success', False),
                        "details": compensation_result
                    }
                    task_state.compensation_log.append(compensation_log)

                    if compensation_result.get('success'):
                        logger.info(f"Компенсация фазы {completed_phase.value} выполнена успешно")
                    else:
                        compensation_errors.append(
                            f"Фаза {completed_phase.value}: {compensation_result.get('error', 'Неизвестная ошибка')}"
                        )
                except Exception as e:
                    compensation_errors.append(f"Фаза {completed_phase.value}: Исключение {str(e)}")
                    logger.error(f"Ошибка компенсации фазы {completed_phase.value}: {str(e)}")

        # Пометка задачи как неудачной
        task_state.current_phase = TaskPhase.FAILED

        if compensation_errors:
            logger.error(f"Ошибки компенсации для задачи {task_state.task_id}:")
            for err in compensation_errors:
                logger.error(f"  - {err}")

    # Компенсирующие операции для критических фаз
    async def _compensate_contract_signing(self, task_state: TaskState,
                                           context: ExecutionContext) -> Dict[str, Any]:
        """Отмена подписания контракта"""
        contract_address = task_state.phase_data.get('contract_address')
        if contract_address and self.blockchain_manager:
            try:
                # В реальной системе вызов функции отмены контракта
                tx_hash = await self._cancel_contract(contract_address)
                return {"success": True, "tx_hash": tx_hash}
            except Exception as e:
                return {"success": False, "error": str(e)}
        return {"success": True, "message": "Контракт не требует компенсации"}

    async def _compensate_payment_escrow(self, task_state: TaskState,
                                         context: ExecutionContext) -> Dict[str, Any]:
        """Возврат платежа из эскроу"""
        escrow_address = task_state.escrow_contract_address
        if escrow_address and self.payment_processor:
            try:
                refund_result = await self.payment_processor.refund_payment(
                    payment_id=task_state.phase_data.get('escrow_tx', ''),
                    reason="Saga compensation"
                )
                return {"success": refund_result.get('success', False), "details": refund_result}
            except Exception as e:
                return {"success": False, "error": str(e)}
        return {"success": True, "message": "Эскроу не требует компенсации"}

    async def _compensate_execution(self, task_state: TaskState,
                                    context: ExecutionContext) -> Dict[str, Any]:
        """Отмена выполнения работы (удаление промежуточных результатов)"""
        # Удаление временных файлов и промежуточных результатов
        deliverables = task_state.phase_data.get('deliverables', {})
        # В реальной системе удаление файлов из хранилища
        return {"success": True, "message": "Промежуточные результаты удалены"}

    async def _compensate_delivery(self, task_state: TaskState,
                                   context: ExecutionContext) -> Dict[str, Any]:
        """Отзыв доставленных материалов (если возможно)"""
        # В реальной системе отправка запроса на удаление материалов у клиента
        # или пометка материалов как "отозванных"
        return {"success": True, "message": "Запрос на отзыв материалов отправлен"}

    async def _compensate_payment_release(self, task_state: TaskState,
                                          context: ExecutionContext) -> Dict[str, Any]:
        """Блокировка выплаченных средств (требует юридической поддержки)"""
        # В реальной системе запрос в службу поддержки для заморозки средств
        return {"success": False, "error": "Требуется ручное вмешательство юридической службы"}

    async def _compensate_nft_minting(self, task_state: TaskState,
                                      context: ExecutionContext) -> Dict[str, Any]:
        """Сжигание или отзыв репутационного NFT"""
        nft_data = task_state.phase_data.get('nft_data', {})
        token_id = nft_data.get('token_id')
        if token_id and self.blockchain_manager:
            try:
                # В реальной системе вызов функции сжигания NFT
                tx_hash = await self._burn_nft(token_id)
                return {"success": True, "tx_hash": tx_hash}
            except Exception as e:
                return {"success": False, "error": str(e)}
        return {"success": True, "message": "NFT не требует компенсации"}

    # Вспомогательные методы для блокчейн-операций (заглушки для демо)
    async def _deploy_job_contract(self, terms: Dict) -> Optional[str]:
        """Заглушка для деплоя контракта"""
        return f"0xContract_{uuid4().hex[:8]}"

    async def _deposit_to_escrow(self, contract_address: str, amount: float, currency: str) -> Optional[str]:
        """Заглушка для депозита в эскроу"""
        return f"0xEscrowTx_{uuid4().hex[:8]}"

    async def _cancel_contract(self, contract_address: str) -> Optional[str]:
        """Заглушка для отмены контракта"""
        return f"0xCancelTx_{uuid4().hex[:8]}"

    async def _burn_nft(self, token_id: int) -> Optional[str]:
        """Заглушка для сжигания NFT"""
        return f"0xBurnTx_{uuid4().hex[:8]}"

    async def _get_available_skills(self) -> List[str]:
        """Получение доступных навыков системы"""
        return [
            "writing", "copywriting", "editing", "translation", "proofreading",
            "seo", "content_strategy", "technical_writing", "creative_writing"
        ]

    async def _save_task_state(self, task_state: TaskState):
        """Сохранение состояния задачи для восстановления после сбоя"""
        task_state.updated_at = datetime.now(timezone.utc)

        # Сохранение в основную БД
        await self.db_service.save_task_state(task_state.to_dict())

        # Дублирование в файловый кэш для быстрого восстановления
        cache_path = f"data/cache/task_states/{task_state.task_id}.json"
        import os
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)

        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump(task_state.to_dict(), f, ensure_ascii=False, indent=2)

    async def recover_task(self, task_id: str) -> Optional[TaskState]:
        """Восстановление задачи после сбоя системы"""
        # Попытка загрузки из файлового кэша
        cache_path = f"data/cache/task_states/{task_id}.json"
        import os

        if os.path.exists(cache_path):
            try:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    state_dict = json.load(f)
                    task_state = TaskState.from_dict(state_dict)
                    self.active_tasks[task_id] = task_state
                    self._task_locks[task_id] = asyncio.Lock()

                    logger.info(f"Задача {task_id} восстановлена из кэша")

                    # Возобновление обработки
                    context = ExecutionContext(**task_state.phase_data.get('context', {}))
                    asyncio.create_task(self._process_task_lifecycle(task_state, context))
                    return task_state
            except Exception as e:
                logger.error(f"Ошибка восстановления задачи из кэша: {str(e)}")

        # Попытка загрузки из основной БД
        try:
            state_dict = await self.db_service.load_task_state(task_id)
            if state_dict:
                task_state = TaskState.from_dict(state_dict)
                self.active_tasks[task_id] = task_state
                self._task_locks[task_id] = asyncio.Lock()

                logger.info(f"Задача {task_id} восстановлена из БД")
                context = ExecutionContext(**task_state.phase_data.get('context', {}))
                asyncio.create_task(self._process_task_lifecycle(task_state, context))
                return task_state
        except Exception as e:
            logger.error(f"Ошибка восстановления задачи из БД: {str(e)}")

        return None

    async def health_check(self) -> Dict[str, Any]:
        """Проверка здоровья оркестратора"""
        base_health = await super().health_check()

        active_count = len([t for t in self.active_tasks.values()
                            if t.current_phase not in [TaskPhase.COMPLETED, TaskPhase.FAILED]])

        return {
            **base_health,
            "active_tasks": active_count,
            "total_tasks": len(self.active_tasks),
            "completed_tasks": len([t for t in self.active_tasks.values()
                                    if t.current_phase == TaskPhase.COMPLETED]),
            "failed_tasks": len([t for t in self.active_tasks.values()
                                 if t.current_phase == TaskPhase.FAILED]),
            "blockchain_integration": self.blockchain_manager is not None,
            "compensation_handlers_registered": len(self._compensation_registry)
        }