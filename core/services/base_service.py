"""
Единый интерфейс для всех сервисов системы с встроенной поддержкой:
- Мониторинга производительности
- Обработки ошибок с политиками повторных попыток
- Аудита действий
- Управления транзакциями
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass
from enum import Enum
import asyncio
import time
import logging
import traceback
from datetime import datetime, timezone
import uuid

logger = logging.getLogger(__name__)


class ServiceStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class RetryPolicy(Enum):
    NONE = "none"
    LINEAR = "linear"  # +2с между попытками
    EXPONENTIAL = "exponential"  # 2^попытка секунд
    EXPONENTIAL_JITTER = "exponential_jitter"  # с рандомизацией


@dataclass
class ExecutionContext:
    """Контекст выполнения задачи с полной трассировкой"""
    task_id: str
    user_id: Optional[str] = None
    platform: Optional[str] = None
    job_id: Optional[str] = None
    client_id: Optional[str] = None
    correlation_id: Optional[str] = None
    metadata: Dict[str, Any] = None
    started_at: datetime = None
    timeout: int = 300  # секунд

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}
        if self.started_at is None:
            self.started_at = datetime.now(timezone.utc)
        if self.correlation_id is None:
            self.correlation_id = str(uuid.uuid4())


@dataclass
class ServiceResult:
    """Стандартизированный результат выполнения сервиса"""
    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None
    error_type: Optional[str] = None
    stack_trace: Optional[str] = None
    execution_time: float = 0.0
    retries: int = 0
    context: Optional[ExecutionContext] = None
    transaction_id: Optional[str] = None
    rollback_required: bool = False

    @classmethod
    def success(cls, data: Any, context: ExecutionContext, execution_time: float, transaction_id: str = None):
        return cls(
            success=True,
            data=data,
            execution_time=execution_time,
            context=context,
            transaction_id=transaction_id or str(uuid.uuid4())
        )

    @classmethod
    def failure(cls, error: str, error_type: str, stack_trace: str, context: ExecutionContext,
                execution_time: float, retries: int = 0, rollback_required: bool = False):
        return cls(
            success=False,
            error=error,
            error_type=error_type,
            stack_trace=stack_trace,
            execution_time=execution_time,
            retries=retries,
            context=context,
            rollback_required=rollback_required
        )


@dataclass
class ValidationResult:
    """Результат валидации входных параметров"""
    valid: bool
    errors: List[str] = None
    warnings: List[str] = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []
        if self.warnings is None:
            self.warnings = []

    @property
    def has_errors(self) -> bool:
        return len(self.errors) > 0

    @property
    def has_warnings(self) -> bool:
        return len(self.warnings) > 0


class BaseService(ABC):
    """
    Базовый класс для всех сервисов с единой точкой расширения
    """

    def __init__(self, service_name: str):
        self.service_name = service_name
        self.logger = logging.getLogger(f"service.{service_name}")
        self.transaction_log = []
        self._initialized = False

    async def initialize(self) -> bool:
        """Асинхронная инициализация сервиса (загрузка моделей, подключение к БД и т.д.)"""
        if self._initialized:
            return True

        try:
            start_time = time.time()
            await self._load_dependencies()
            self._initialized = True
            self.logger.info(f"Сервис '{self.service_name}' инициализирован за {time.time() - start_time:.2f}с")
            return True
        except Exception as e:
            self.logger.error(f"Ошибка инициализации сервиса '{self.service_name}': {str(e)}")
            return False

    @abstractmethod
    async def _load_dependencies(self):
        """Загрузка зависимостей сервиса (модели, коннекты и т.д.)"""
        pass

    async def validate(self, params: Dict[str, Any]) -> ValidationResult:
        """
        Валидация входных параметров перед выполнением
        """
        # Базовая валидация — переопределяется в дочерних классах
        if not isinstance(params, dict):
            return ValidationResult(
                valid=False,
                errors=["Параметры должны быть словарем (dict)"]
            )
        return ValidationResult(valid=True)

    async def execute(self, context: ExecutionContext, **kwargs) -> ServiceResult:
        """
        Единая точка входа для выполнения бизнес-логики сервиса
        """
        # 1. Валидация контекста
        if not isinstance(context, ExecutionContext):
            return ServiceResult.failure(
                error="Неверный тип контекста выполнения",
                error_type="ValidationError",
                stack_trace="",
                context=context,
                execution_time=0.0
            )

        # 2. Валидация параметров
        validation_result = await self.validate(kwargs)
        if validation_result.has_errors:
            return ServiceResult.failure(
                error=f"Валидация параметров не пройдена: {', '.join(validation_result.errors)}",
                error_type="ValidationError",
                stack_trace="",
                context=context,
                execution_time=0.0
            )

        # 3. Инициализация сервиса (если не инициализирован)
        if not self._initialized:
            if not await self.initialize():
                return ServiceResult.failure(
                    error=f"Не удалось инициализировать сервис '{self.service_name}'",
                    error_type="InitializationError",
                    stack_trace="",
                    context=context,
                    execution_time=0.0,
                    rollback_required=True
                )

        # 4. Выполнение с обработкой ошибок и мониторингом
        start_time = time.time()
        transaction_id = str(uuid.uuid4())
        self.logger.info(f"[{transaction_id}] Запуск сервиса '{self.service_name}' для задачи {context.task_id}")

        try:
            # Регистрация транзакции
            await self._register_transaction(transaction_id, context, kwargs)

            # Выполнение бизнес-логики
            result = await self._execute_business_logic(context, transaction_id, **kwargs)

            execution_time = time.time() - start_time

            if isinstance(result, ServiceResult):
                result.execution_time = execution_time
                result.transaction_id = transaction_id
                result.context = context
                return result

            # Автоматическая обертка успешного результата
            return ServiceResult.success(
                data=result,
                context=context,
                execution_time=execution_time,
                transaction_id=transaction_id
            )

        except asyncio.TimeoutError:
            execution_time = time.time() - start_time
            error_msg = f"Таймаут выполнения сервиса '{self.service_name}' (> {context.timeout}с)"
            self.logger.error(f"[{transaction_id}] {error_msg}")
            return ServiceResult.failure(
                error=error_msg,
                error_type="TimeoutError",
                stack_trace=traceback.format_exc(),
                context=context,
                execution_time=execution_time,
                rollback_required=True
            )

        except Exception as e:
            execution_time = time.time() - start_time
            error_type = type(e).__name__
            error_msg = str(e)
            stack_trace = traceback.format_exc()

            self.logger.error(f"[{transaction_id}] Ошибка в сервисе '{self.service_name}': {error_msg}\n{stack_trace}")

            # Автоматический откат при критических ошибках
            rollback_required = self._should_rollback(error_type)

            if rollback_required:
                try:
                    await self.rollback(transaction_id)
                    self.logger.info(f"[{transaction_id}] Откат транзакции выполнен успешно")
                except Exception as rollback_error:
                    self.logger.error(f"[{transaction_id}] Ошибка при откате: {str(rollback_error)}")

            return ServiceResult.failure(
                error=error_msg,
                error_type=error_type,
                stack_trace=stack_trace,
                context=context,
                execution_time=execution_time,
                rollback_required=rollback_required
            )

    @abstractmethod
    async def _execute_business_logic(self, context: ExecutionContext, transaction_id: str, **kwargs) -> Any:
        """
        Бизнес-логика сервиса — реализуется в дочерних классах
        """
        pass

    async def rollback(self, transaction_id: str) -> bool:
        """
        Откат транзакции — реализуется в дочерних классах при необходимости
        """
        self.logger.info(f"[{transaction_id}] Откат транзакции для сервиса '{self.service_name}'")
        # По умолчанию просто логируем — дочерние классы переопределяют при необходимости
        return True

    async def _register_transaction(self, transaction_id: str, context: ExecutionContext, params: Dict):
        """
        Регистрация транзакции для аудита и отката
        """
        transaction_record = {
            "transaction_id": transaction_id,
            "service": self.service_name,
            "task_id": context.task_id,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "params": params,
            "context": {
                "user_id": context.user_id,
                "platform": context.platform,
                "job_id": context.job_id,
                "client_id": context.client_id,
                "correlation_id": context.correlation_id
            }
        }
        self.transaction_log.append(transaction_record)

        # Ограничение размера лога транзакций (последние 1000)
        if len(self.transaction_log) > 1000:
            self.transaction_log = self.transaction_log[-1000:]

    def _should_rollback(self, error_type: str) -> bool:
        """
        Определение необходимости отката по типу ошибки
        """
        critical_errors = [
            "DatabaseError", "IntegrityError", "PaymentError",
            "BlockchainError", "FilesystemError", "NetworkError"
        ]
        return any(critical in error_type for critical in critical_errors)

    async def health_check(self) -> Dict[str, Any]:
        """
        Проверка здоровья сервиса
        """
        return {
            "service": self.service_name,
            "status": "healthy" if self._initialized else "initializing",
            "initialized": self._initialized,
            "uptime_seconds": getattr(self, "_uptime_seconds", 0),
            "transaction_count": len(self.transaction_log),
            "last_transaction": self.transaction_log[-1] if self.transaction_log else None
        }

    def __str__(self):
        return f"BaseService(name={self.service_name}, initialized={self._initialized})"


# Декораторы для расширения функционала без изменения базового класса


def monitor_performance(service_name: Optional[str] = None):
    """
    Декоратор для мониторинга производительности методов
    """

    def decorator(func):
        async def wrapper(self, *args, **kwargs):
            start_time = time.time()
            func_name = func.__name__
            service = service_name or getattr(self, 'service_name', self.__class__.__name__)

            try:
                result = await func(self, *args, **kwargs)
                execution_time = time.time() - start_time

                # Логирование метрик
                logger.info(f"[PERF] {service}.{func_name} completed in {execution_time:.3f}s")

                # Сохранение метрик в систему мониторинга (если доступна)
                if hasattr(self, '_metrics_collector'):
                    await self._metrics_collector.record_metric(
                        metric_name=f"{service}.{func_name}.duration",
                        value=execution_time,
                        labels={"status": "success"}
                    )

                return result

            except Exception as e:
                execution_time = time.time() - start_time
                logger.error(f"[PERF] {service}.{func_name} failed after {execution_time:.3f}s: {str(e)}")

                if hasattr(self, '_metrics_collector'):
                    await self._metrics_collector.record_metric(
                        metric_name=f"{service}.{func_name}.duration",
                        value=execution_time,
                        labels={"status": "failed", "error_type": type(e).__name__}
                    )

                raise

        return wrapper

    return decorator


def handle_errors(retry_policy: RetryPolicy = RetryPolicy.EXPONENTIAL, max_retries: int = 3):
    """
    Декоратор для обработки ошибок с политикой повторных попыток
    """

    def decorator(func):
        async def wrapper(self, *args, **kwargs):
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    return await func(self, *args, **kwargs)

                except (asyncio.TimeoutError, ConnectionError, ConnectionResetError) as e:
                    last_exception = e
                    if attempt < max_retries:
                        # Расчет задержки в зависимости от политики
                        if retry_policy == RetryPolicy.LINEAR:
                            delay = 2 * (attempt + 1)
                        elif retry_policy == RetryPolicy.EXPONENTIAL:
                            delay = 2 ** attempt
                        elif retry_policy == RetryPolicy.EXPONENTIAL_JITTER:
                            import random
                            delay = (2 ** attempt) * (0.5 + random.random())
                        else:  # NONE
                            delay = 0

                        logger.warning(f"Попытка {attempt + 1}/{max_retries} не удалась для {func.__name__}: {str(e)}. "
                                       f"Повтор через {delay:.1f}с")

                        if delay > 0:
                            await asyncio.sleep(delay)
                    else:
                        logger.error(f"Все {max_retries} попыток не удалась для {func.__name__}: {str(e)}")
                        raise last_exception

                except Exception as e:
                    # Для не-сетевых ошибок не повторяем
                    logger.error(f"Критическая ошибка в {func.__name__}: {str(e)}")
                    raise

            raise last_exception if last_exception else Exception("Неизвестная ошибка выполнения")

        return wrapper

    return decorator


def audit_log(action: str, resource_type: Optional[str] = None):
    """
    Декоратор для аудита действий
    """

    def decorator(func):
        async def wrapper(self, *args, **kwargs):
            service_name = getattr(self, 'service_name', self.__class__.__name__)
            start_time = time.time()

            try:
                result = await func(self, *args, **kwargs)
                execution_time = time.time() - start_time

                # Извлечение контекста из аргументов
                context = None
                for arg in args:
                    if isinstance(arg, ExecutionContext):
                        context = arg
                        break
                if context is None and 'context' in kwargs:
                    context = kwargs['context']

                audit_record = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "action": action,
                    "service": service_name,
                    "resource_type": resource_type,
                    "user_id": context.user_id if context else None,
                    "job_id": context.job_id if context else None,
                    "client_id": context.client_id if context else None,
                    "correlation_id": context.correlation_id if context else str(uuid.uuid4()),
                    "execution_time_ms": int(execution_time * 1000),
                    "status": "success"
                }

                logger.info(f"[AUDIT] {audit_record}")

                # Сохранение в аудит-лог (реализуется отдельно)
                if hasattr(self, '_audit_logger'):
                    await self._audit_logger.log_action(audit_record)

                return result

            except Exception as e:
                execution_time = time.time() - start_time
                logger.error(f"[AUDIT] Действие '{action}' завершилось ошибкой: {str(e)}")
                raise

        return wrapper

    return decorator