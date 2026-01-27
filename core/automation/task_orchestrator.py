"""
Task Orchestrator с распределенными блокировками для предотвращения гонок данных
"""
import asyncio
import logging
import json
import time
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
import uuid
from redis import asyncio as aioredis  # Для распределенных локов
from core.services.base_service import BaseService, ExecutionContext, ServiceResult
from core.ai_management.lazy_model_loader import LazyModelLoader
from services.ai_services.copywriting_service import CopywritingService
from services.ai_services.translation_service import TranslationService
from services.storage.database_service import DatabaseService

logger = logging.getLogger(__name__)


class DistributedLock:
    """
    Распределенная блокировка через Redis для предотвращения гонок данных
    при параллельной обработке одного заказа
    """

    def __init__(self, redis_client: aioredis.Redis, lock_key: str, timeout: int = 30):
        self.redis = redis_client
        self.lock_key = f"lock:task:{lock_key}"
        self.timeout = timeout
        self.lock_value = str(uuid.uuid4())
        self.acquired = False

    async def acquire(self) -> bool:
        """Попытка захвата блокировки с таймаутом"""
        # Используем SET с опциями NX (только если ключ не существует) и PX (таймаут в мс)
        result = await self.redis.set(
            self.lock_key,
            self.lock_value,
            nx=True,
            px=self.timeout * 1000
        )
        self.acquired = bool(result)
        return self.acquired

    async def release(self):
        """Освобождение блокировки (только если мы её захватили)"""
        if not self.acquired:
            return

        # Lua скрипт для атомарной проверки и удаления
        lua_script = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
            return redis.call("del", KEYS[1])
        else
            return 0
        end
        """

        try:
            await self.redis.eval(lua_script, 1, self.lock_key, self.lock_value)
        except Exception as e:
            logger.warning(f"Ошибка освобождения блокировки {self.lock_key}: {str(e)}")
        finally:
            self.acquired = False

    async def __aenter__(self):
        if not await self.acquire():
            raise TimeoutError(f"Не удалось захватить блокировку {self.lock_key} за {self.timeout}с")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.release()


class TaskOrchestrator(BaseService):
    """
    Оркестратор задач с защитой от гонок данных и поддержкой распределенной обработки
    """

    def __init__(self, db_service: DatabaseService, redis_client: aioredis.Redis):
        super().__init__(service_name="task_orchestrator")
        self.db_service = db_service
        self.redis_client = redis_client
        self.copywriting_service = CopywritingService()
        self.translation_service = TranslationService()
        self._task_locks: Dict[str, asyncio.Lock] = {}  # Локальные блокировки для задач

    async def _load_dependencies(self):
        """Инициализация зависимостей"""
        # Инициализация сервисов ИИ
        await self.copywriting_service.initialize()
        await self.translation_service.initialize()
        self._initialized = True

    async def execute_task(self, job_details: Dict[str, Any], bid_result: Dict[str, Any],
                          context: ExecutionContext) -> ServiceResult:
        """
        Выполнение задачи с распределенной блокировкой для предотвращения гонок данных
        """
        job_id = context.job_id or job_details.get('id')

        if not job_id:
            return ServiceResult.failure(
                error="Отсутствует идентификатор заказа (job_id)",
                error_type="ValidationError",
                stack_trace="",
                context=context,
                execution_time=0.0,
                rollback_required=True
            )

        # 1. Захват распределенной блокировки для этого заказа
        lock = DistributedLock(self.redis_client, job_id, timeout=300)  # 5 минут на выполнение

        try:
            async with lock:
                # 2. Проверка, не выполняется ли уже эта задача
                if not await self._can_start_task(job_id, context):
                    return ServiceResult.failure(
                        error=f"Задача для заказа {job_id} уже выполняется или завершена",
                        error_type="TaskAlreadyRunningError",
                        stack_trace="",
                        context=context,
                        execution_time=0.0
                    )

                # 3. Маркировка задачи как "в процессе"
                await self._mark_task_in_progress(job_id, context)

                # 4. Выполнение основной логики
                result = await self._execute_business_logic(context, job_id, job_details, bid_result)

                # 5. Маркировка завершения
                if result.success:
                    await self._mark_task_completed(job_id, context, result.data)
                else:
                    await self._mark_task_failed(job_id, context, result.error)

                return result

        except TimeoutError as e:
            return ServiceResult.failure(
                error=f"Таймаут блокировки для заказа {job_id}: {str(e)}",
                error_type="LockTimeoutError",
                stack_trace="",
                context=context,
                execution_time=0.0,
                rollback_required=True
            )
        except Exception as e:
            # Обеспечение освобождения блокировки даже при исключениях
            await lock.release()
            raise

    async def _can_start_task(self, job_id: str, context: ExecutionContext) -> bool:
        """Проверка возможности запуска задачи"""
        # Проверка в БД
        task_status = await self.db_service.get_task_status(job_id)

        if task_status and task_status.get('status') in ['in_progress', 'completed', 'failed']:
            logger.warning(f"Заказ {job_id} уже имеет статус: {task_status.get('status')}")
            return False

        return True

    async def _mark_task_in_progress(self, job_id: str, context: ExecutionContext):
        """Маркировка задачи как выполняемой"""
        await self.db_service.update_task_status(
            job_id=job_id,
            status='in_progress',
            started_at=datetime.now(timezone.utc),
            worker_id=context.correlation_id,
            metadata={
                "platform": context.platform,
                "user_id": context.user_id,
                "started_at_iso": datetime.now(timezone.utc).isoformat()
            }
        )

        # Также сохраняем в Redis для быстрой проверки
        await self.redis_client.setex(
            f"task:status:{job_id}",
            3600,  # TTL 1 час
            json.dumps({
                "status": "in_progress",
                "worker_id": context.correlation_id,
                "started_at": time.time()
            })
        )

    async def _mark_task_completed(self, job_id: str, context: ExecutionContext, result_data: Any):
        """Маркировка успешного завершения задачи"""
        await self.db_service.update_task_status(
            job_id=job_id,
            status='completed',
            completed_at=datetime.now(timezone.utc),
            result=result_data
        )

        # Удаление из Redis
        await self.redis_client.delete(f"task:status:{job_id}")

    async def _mark_task_failed(self, job_id: str, context: ExecutionContext, error: str):
        """Маркировка неудачного завершения задачи"""
        await self.db_service.update_task_status(
            job_id=job_id,
            status='failed',
            failed_at=datetime.now(timezone.utc),
            error=error,
            error_type="ExecutionError"
        )

    async def _execute_business_logic(self, context: ExecutionContext, job_id: str,
                                    job_details: Dict[str, Any], bid_result: Dict[str, Any]) -> Any:
        """
        Основная бизнес-логика выполнения задачи
        """
        # Анализ требований заказа
        requirements = job_details.get('requirements', {})
        deliverables_required = requirements.get('deliverables', [])

        # Выполнение каждого типа работ
        deliverables = {}

        for deliverable_type in deliverables_required:
            if deliverable_type == 'copywriting':
                content = await self.copywriting_service.generate_content(
                    prompt=job_details.get('description', ''),
                    tone=bid_result.get('proposed_tone', 'professional'),
                    length=job_details.get('word_count', 500),
                    context=context
                )
                deliverables['copywriting'] = content

            elif deliverable_type == 'translation':
                source_text = job_details.get('source_text', '')
                target_lang = job_details.get('target_language', 'ru')

                translation = await self.translation_service.translate_text(
                    text=source_text,
                    target_language=target_lang,
                    context=context
                )
                deliverables['translation'] = translation

            elif deliverable_type == 'editing':
                text_to_edit = job_details.get('text_to_edit', '')
                editing_style = job_details.get('editing_style', 'proofreading')

                edited = await self._perform_editing(text_to_edit, editing_style, context)
                deliverables['editing'] = edited

        # Валидация результатов
        validation = await self._validate_deliverables(deliverables, requirements)

        if not validation['valid']:
            return ServiceResult.failure(
                error=f"Валидация результатов не пройдена: {', '.join(validation['errors'])}",
                error_type="ValidationError",
                stack_trace="",
                context=context,
                execution_time=0.0,
                rollback_required=True
            )

        return deliverables

    async def _perform_editing(self, text: str, style: str, context: ExecutionContext) -> str:
        """Выполнение редактирования текста"""
        # Простая реализация — в продакшене использовать полноценный сервис
        if style == 'proofreading':
            # Исправление грамматики и орфографии
            return await self.copywriting_service.improve_text(text, context)
        elif style == 'rewriting':
            # Перефразирование с сохранением смысла
            return await self.copywriting_service.rewrite_text(text, context)
        else:
            return text

    async def _validate_deliverables(self, deliverables: Dict[str, Any], requirements: Dict[str, Any]) -> Dict[str, Any]:
        """Валидация результатов на соответствие требованиям"""
        errors = []
        warnings = []

        # Проверка наличия всех требуемых артефактов
        required = requirements.get('deliverables', [])
        for req_type in required:
            if req_type not in deliverables:
                errors.append(f"Отсутствует обязательный артефакт: {req_type}")

        # Проверка объема текста
        min_words = requirements.get('min_word_count')
        if min_words and 'copywriting' in deliverables:
            word_count = len(deliverables['copywriting'].split())
            if word_count < min_words:
                errors.append(f"Объем текста ({word_count} слов) меньше минимального ({min_words})")

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings
        }

    async def rollback(self, transaction_id: str) -> bool:
        """
        Откат задачи — пометка как отмененной и очистка ресурсов
        """
        # В реальной системе здесь будет откат платежей, удаление файлов и т.д.
        logger.info(f"Откат транзакции {transaction_id} для оркестратора задач")
        return True

    async def health_check(self) -> Dict[str, Any]:
        """Проверка здоровья сервиса"""
        base_health = await super().health_check()

        # Проверка подключения к Redis
        try:
            await self.redis_client.ping()
            redis_healthy = True
        except:
            redis_healthy = False

        return {
            **base_health,
            "redis_connected": redis_healthy,
            "active_tasks": len(self._task_locks)
        }