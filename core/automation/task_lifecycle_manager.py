"""
Унифицированный менеджер жизненного цикла задач с поддержкой:
- Автоматических переходов между фазами
- Отката при ошибках (Saga pattern)
- Сохранения состояния для восстановления
- Параллельной обработки нескольких задач
"""
import asyncio
import json
import logging
from enum import Enum
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timezone
import uuid
from dataclasses import dataclass, asdict

from core.automation.job_analyzer import JobAnalyzer
from core.automation.decision_engine import DecisionEngine
from core.automation.task_orchestrator import TaskOrchestrator
from core.automation.quality_controller import QualityController
from core.automation.reputation_manager import ReputationManager
from core.payment.enhanced_payment_processor import EnhancedPaymentProcessor
from core.communication.empathetic_communicator import EmpatheticCommunicator
from services.ai_services.copywriting_service import CopywritingService
from services.ai_services.translation_service import TranslationService
from services.ai_services.editing_service import EditingService
from services.storage.database_service import DatabaseService
from core.services.base_service import ExecutionContext, ServiceResult

logger = logging.getLogger(__name__)


class TaskPhase(Enum):
    DISCOVERY = "discovery"          # Анализ заказа
    QUALIFICATION = "qualification"  # Оценка возможности выполнения
    BIDDING = "bidding"              # Подача предложения
    NEGOTIATION = "negotiation"      # Переговоры
    EXECUTION = "execution"          # Выполнение работы
    QUALITY_CHECK = "quality_check"  # Проверка качества
    DELIVERY = "delivery"            # Доставка результата
    REVISION = "revision"            # Работа над правками
    PAYMENT = "payment"              # Получение оплаты
    FEEDBACK = "feedback"            # Получение отзыва
    COMPLETED = "completed"          # Завершено успешно
    FAILED = "failed"                # Провалено


@dataclass
class TaskState:
    """Полное состояние задачи для восстановления после сбоя"""
    task_id: str
    job_id: str
    current_phase: TaskPhase
    phase_start_time: datetime
    phase_attempts: int
    phase_data: Dict[str, Any]
    context: Dict[str, Any]
    error_history: List[Dict[str, Any]]
    created_at: datetime
    updated_at: datetime

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        # Конвертация datetime в ISO формат для сериализации
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

        return cls(**data)


class TaskLifecycleManager:
    """
    Оркестратор полного жизненного цикла задачи фрилансера
    """

    def __init__(self, db_service: DatabaseService):
        self.db_service = db_service
        self.phases = {
            TaskPhase.DISCOVERY: JobAnalyzer(),
            TaskPhase.QUALIFICATION: DecisionEngine(),
            TaskPhase.BIDDING: self._init_bidding_engine(),
            TaskPhase.EXECUTION: TaskOrchestrator(),
            TaskPhase.QUALITY_CHECK: QualityController(),
            TaskPhase.DELIVERY: self._init_delivery_manager(),
            TaskPhase.PAYMENT: EnhancedPaymentProcessor(),
            TaskPhase.FEEDBACK: ReputationManager()
        }
        self.active_tasks: Dict[str, TaskState] = {}
        self._lock = asyncio.Lock()

    def _init_bidding_engine(self):
        """Инициализация движка подачи предложений"""
        from services.ai_services.copywriting_service import CopywritingService
        return BiddingEngine(
            copywriting_service=CopywritingService(),
            translation_service=TranslationService(),
            editing_service=EditingService()
        )

    def _init_delivery_manager(self):
        """Инициализация менеджера доставки"""
        from core.communication.empathetic_communicator import EmpatheticCommunicator
        return DeliveryManager(
            communicator=EmpatheticCommunicator(),
            storage_service=self.db_service
        )

    async def start_new_task(self, job_data: Dict[str, Any], platform: str) -> TaskState:
        """
        Запуск нового жизненного цикла задачи
        """
        task_id = str(uuid.uuid4())
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
            phase_data={"job_data": job_data, "platform": platform},
            context=asdict(context),
            error_history=[],
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )

        # Сохранение начального состояния
        await self._save_task_state(task_state)
        self.active_tasks[task_id] = task_state

        logger.info(f"Запущен новый жизненный цикл задачи {task_id} для заказа {job_id}")

        # Запуск асинхронной обработки
        asyncio.create_task(self._process_task_lifecycle(task_state))

        return task_state

    async def _process_task_lifecycle(self, task_state: TaskState):
        """
        Основной цикл обработки задачи с автоматическими переходами между фазами
        """
        max_attempts_per_phase = 3

        while task_state.current_phase not in [TaskPhase.COMPLETED, TaskPhase.FAILED]:
            current_phase = task_state.current_phase
            phase_handler = self.phases.get(current_phase)

            if phase_handler is None:
                error_msg = f"Нет обработчика для фазы {current_phase}"
                logger.error(error_msg)
                await self._handle_phase_failure(task_state, error_msg, "NoHandlerError")
                continue

            try:
                # Выполнение фазы
                result = await self._execute_phase(phase_handler, task_state)

                if result.success:
                    # Успешное завершение фазы — переход к следующей
                    await self._handle_phase_success(task_state, result)
                else:
                    # Ошибка в фазе
                    task_state.phase_attempts += 1

                    if task_state.phase_attempts >= max_attempts_per_phase or result.rollback_required:
                        # Превышено количество попыток или требуется откат
                        await self._handle_phase_failure(task_state, result.error, result.error_type)
                    else:
                        # Повторная попытка фазы
                        logger.warning(f"Повторная попытка фазы {current_phase} для задачи {task_state.task_id} "
                                     f"(попытка {task_state.phase_attempts}/{max_attempts_per_phase})")
                        await asyncio.sleep(2 ** (task_state.phase_attempts - 1))  # Экспоненциальная задержка

                # Сохранение состояния после каждой фазы
                await self._save_task_state(task_state)

            except Exception as e:
                logger.exception(f"Необработанное исключение в фазе {current_phase} для задачи {task_state.task_id}")
                await self._handle_phase_failure(task_state, str(e), type(e).__name__)
                await self._save_task_state(task_state)

        # Финальные действия по завершению задачи
        await self._finalize_task(task_state)

    async def _execute_phase(self, phase_handler, task_state: TaskState) -> ServiceResult:
        """
        Выполнение конкретной фазы жизненного цикла
        """
        context = ExecutionContext(
            task_id=task_state.task_id,
            job_id=task_state.job_id,
            platform=task_state.phase_data.get('platform', 'unknown'),
            metadata=task_state.context.get('metadata', {})
        )

        # Вызов соответствующего метода фазы
        if task_state.current_phase == TaskPhase.DISCOVERY:
            return await phase_handler.analyze_job(task_state.phase_data['job_data'], context)

        elif task_state.current_phase == TaskPhase.QUALIFICATION:
            return await phase_handler.evaluate_job_suitability(task_state.phase_data['job_analysis'], context)

        elif task_state.current_phase == TaskPhase.BIDDING:
            return await phase_handler.prepare_bid(
                job_analysis=task_state.phase_data.get('job_analysis'),
                qualification_result=task_state.phase_data.get('qualification_result'),
                context=context
            )

        elif task_state.current_phase == TaskPhase.EXECUTION:
            return await phase_handler.execute_task(
                job_details=task_state.phase_data.get('job_details'),
                bid_result=task_state.phase_data.get('bid_result'),
                context=context
            )

        elif task_state.current_phase == TaskPhase.QUALITY_CHECK:
            return await phase_handler.check_quality(
                deliverables=task_state.phase_data.get('deliverables'),
                job_requirements=task_state.phase_data.get('job_requirements'),
                context=context
            )

        elif task_state.current_phase == TaskPhase.DELIVERY:
            return await phase_handler.deliver_result(
                deliverables=task_state.phase_data.get('deliverables'),
                client_id=task_state.phase_data.get('client_id'),
                context=context
            )

        elif task_state.current_phase == TaskPhase.PAYMENT:
            return await phase_handler.process_payment(
                job_id=task_state.job_id,
                amount=task_state.phase_data.get('amount'),
                context=context
            )

        elif task_state.current_phase == TaskPhase.FEEDBACK:
            return await phase_handler.process_feedback(
                job_id=task_state.job_id,
                client_id=task_state.phase_data.get('client_id'),
                context=context
            )

        else:
            return ServiceResult.failure(
                error=f"Неизвестная фаза: {task_state.current_phase}",
                error_type="UnknownPhaseError",
                stack_trace="",
                context=context,
                execution_time=0.0
            )

    async def _handle_phase_success(self, task_state: TaskState, result: ServiceResult):
        """
        Обработка успешного завершения фазы и переход к следующей
        """
        # Сохранение результатов фазы
        task_state.phase_data[f"{task_state.current_phase.value}_result"] = result.data

        # Определение следующей фазы
        next_phase = self._get_next_phase(task_state.current_phase, result.data)

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
        """
        Логика переходов между фазами с учетом результатов текущей фазы
        """
        transitions = {
            TaskPhase.DISCOVERY: TaskPhase.QUALIFICATION,
            TaskPhase.QUALIFICATION: TaskPhase.BIDDING if phase_result.get('suitable', False) else None,
            TaskPhase.BIDDING: TaskPhase.NEGOTIATION if phase_result.get('negotiation_required', False) else TaskPhase.EXECUTION,
            TaskPhase.NEGOTIATION: TaskPhase.EXECUTION if phase_result.get('accepted', False) else None,
            TaskPhase.EXECUTION: TaskPhase.QUALITY_CHECK,
            TaskPhase.QUALITY_CHECK: TaskPhase.DELIVERY if phase_result.get('quality_passed', True) else TaskPhase.REVISION,
            TaskPhase.REVISION: TaskPhase.QUALITY_CHECK,  # Возврат на проверку после правок
            TaskPhase.DELIVERY: TaskPhase.PAYMENT,
            TaskPhase.PAYMENT: TaskPhase.FEEDBACK,
            TaskPhase.FEEDBACK: TaskPhase.COMPLETED
        }

        # Специальная логика для отказа в квалификации
        if current_phase == TaskPhase.QUALIFICATION and not phase_result.get('suitable', False):
            logger.info(f"Заказ не подходит по критериям — завершение жизненного цикла")
            return None  # Завершение без перехода

        return transitions.get(current_phase)

    async def _handle_phase_failure(self, task_state: TaskState, error: str, error_type: str):
        """
        Обработка ошибки в фазе с возможным откатом (Saga pattern)
        """
        error_record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "phase": task_state.current_phase.value,
            "error": error,
            "error_type": error_type,
            "attempt": task_state.phase_attempts
        }
        task_state.error_history.append(error_record)

        logger.error(f"Ошибка в фазе {task_state.current_phase.value} задачи {task_state.task_id}: {error}")

        # Логика отката для критических фаз
        if task_state.current_phase in [TaskPhase.PAYMENT, TaskPhase.DELIVERY]:
            await self._perform_saga_rollback(task_state)

        # Решение о завершении задачи с ошибкой
        if task_state.phase_attempts >= 3 or error_type in ["PaymentError", "BlockchainError", "ContractViolation"]:
            task_state.current_phase = TaskPhase.FAILED
            logger.error(f"Задача {task_state.task_id} помечена как неудачная после {task_state.phase_attempts} попыток")

    async def _perform_saga_rollback(self, task_state: TaskState):
        """
        Выполнение отката по паттерну Saga для распределенных транзакций
        """
        # Откат в обратном порядке выполненных фаз
        rollback_phases = [
            TaskPhase.DELIVERY,
            TaskPhase.QUALITY_CHECK,
            TaskPhase.EXECUTION,
            TaskPhase.BIDDING
        ]

        for phase in rollback_phases:
            if phase.value in task_state.phase_data:
                try:
                    phase_handler = self.phases.get(phase)
                    if phase_handler and hasattr(phase_handler, 'rollback'):
                        await phase_handler.rollback(task_state.phase_data[f"{phase.value}_result"])
                        logger.info(f"Откат фазы {phase.value} выполнен успешно")
                except Exception as e:
                    logger.warning(f"Ошибка при откате фазы {phase.value}: {str(e)}")
                    # Продолжаем откат даже при ошибках в отдельных фазах

    async def _save_task_state(self, task_state: TaskState):
        """
        Сохранение состояния задачи для восстановления после сбоя
        """
        task_state.updated_at = datetime.now(timezone.utc)

        # Сохранение в основную БД
        await self.db_service.save_task_state(task_state.to_dict())

        # Дублирование в файловый кэш для быстрого восстановления
        cache_path = f"data/cache/task_states/{task_state.task_id}.json"
        import os
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)

        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump(task_state.to_dict(), f, ensure_ascii=False, indent=2)

    async def _finalize_task(self, task_state: TaskState):
        """
        Финальные действия по завершению задачи
        """
        # Удаление из активных задач
        self.active_tasks.pop(task_state.task_id, None)

        # Генерация отчета
        report = await self._generate_completion_report(task_state)

        # Сохранение отчета
        report_path = f"data/reports/completed/{task_state.task_id}_{int(datetime.now().timestamp())}.json"
        import os
        os.makedirs(os.path.dirname(report_path), exist_ok=True)

        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        logger.info(f"Завершена задача {task_state.task_id}, отчет сохранен в {report_path}")

    async def _generate_completion_report(self, task_state: TaskState) -> Dict[str, Any]:
        """
        Генерация детального отчета о выполнении задачи
        """
        total_duration = (task_state.updated_at - task_state.created_at).total_seconds()

        # Анализ успешных и неудачных фаз
        successful_phases = []
        failed_phases = []

        for error in task_state.error_history:
            failed_phases.append(error['phase'])

        all_phases = [p.value for p in TaskPhase if p not in [TaskPhase.COMPLETED, TaskPhase.FAILED]]
        successful_phases = [p for p in all_phases if p not in failed_phases]

        return {
            "task_id": task_state.task_id,
            "job_id": task_state.job_id,
            "status": task_state.current_phase.value,
            "total_duration_seconds": total_duration,
            "phases_completed": successful_phases,
            "phases_failed": failed_phases,
            "error_count": len(task_state.error_history),
            "errors": task_state.error_history,
            "final_result": task_state.phase_data.get(f"{task_state.current_phase.value}_result"),
            "generated_at": datetime.now(timezone.utc).isoformat()
        }

    async def recover_task(self, task_id: str) -> Optional[TaskState]:
        """
        Восстановление задачи после сбоя системы
        """
        # Попытка загрузки из файлового кэша
        cache_path = f"data/cache/task_states/{task_id}.json"
        import os

        if os.path.exists(cache_path):
            try:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    state_dict = json.load(f)
                    task_state = TaskState.from_dict(state_dict)
                    self.active_tasks[task_id] = task_state
                    logger.info(f"Задача {task_id} восстановлена из кэша")

                    # Возобновление обработки
                    asyncio.create_task(self._process_task_lifecycle(task_state))
                    return task_state
            except Exception as e:
                logger.error(f"Ошибка восстановления задачи из кэша: {str(e)}")

        # Попытка загрузки из основной БД
        try:
            state_dict = await self.db_service.load_task_state(task_id)
            if state_dict:
                task_state = TaskState.from_dict(state_dict)
                self.active_tasks[task_id] = task_state
                logger.info(f"Задача {task_id} восстановлена из БД")
                asyncio.create_task(self._process_task_lifecycle(task_state))
                return task_state
        except Exception as e:
            logger.error(f"Ошибка восстановления задачи из БД: {str(e)}")

        return None

    async def get_task_status(self, task_id: str) -> Dict[str, Any]:
        """
        Получение текущего статуса задачи
        """
        task_state = self.active_tasks.get(task_id)

        if not task_state:
            # Попытка загрузки из хранилища
            task_state = await self.recover_task(task_id)
            if not task_state:
                return {"status": "not_found", "task_id": task_id}

        duration = (datetime.now(timezone.utc) - task_state.phase_start_time).total_seconds()

        return {
            "task_id": task_state.task_id,
            "job_id": task_state.job_id,
            "current_phase": task_state.current_phase.value,
            "phase_duration_seconds": duration,
            "phase_attempts": task_state.phase_attempts,
            "error_count": len(task_state.error_history),
            "last_error": task_state.error_history[-1] if task_state.error_history else None,
            "status": "active" if task_state.current_phase not in [TaskPhase.COMPLETED, TaskPhase.FAILED] else task_state.current_phase.value
        }