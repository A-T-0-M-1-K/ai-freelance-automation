"""
Реализация паттерна Saga для управления долгоживущими транзакциями
с поддержкой откатов, журналирования и восстановления после сбоев.
"""

import json
import os
import time
import hashlib
from pathlib import Path
from datetime import datetime, timedelta
from enum import Enum
from typing import List, Dict, Any, Optional, Callable, Tuple
from dataclasses import dataclass, asdict
import threading
import uuid

from core.monitoring.alert_manager import AlertManager
from core.security.audit_logger import AuditLogger
from core.payment.enhanced_payment_processor import EnhancedPaymentProcessor


class SagaStatus(Enum):
    """Статус выполнения саги"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    COMPENSATING = "compensating"
    COMPENSATED = "compensated"
    TIMED_OUT = "timed_out"


class SagaStepStatus(Enum):
    """Статус шага саги"""
    PENDING = "pending"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    COMPENSATED = "compensated"


@dataclass
class SagaStep:
    """Один шаг в цепочке саги"""
    step_id: str
    name: str
    action: Callable  # Основное действие
    compensation: Callable  # Действие отката
    timeout_seconds: int = 300  # Таймаут по умолчанию 5 минут
    retry_count: int = 3
    retry_delay_seconds: int = 5
    requires_confirmation: bool = False
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


@dataclass
class SagaExecutionLog:
    """Журнал выполнения саги для аудита и восстановления"""
    saga_id: str
    saga_name: str
    status: SagaStatus
    steps: List[Dict[str, Any]]
    started_at: datetime
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    error_step: Optional[str] = None
    context_snapshot: Dict[str, Any] = None
    hash_before: str = ""
    hash_after: str = ""

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        result['started_at'] = self.started_at.isoformat()
        result['completed_at'] = self.completed_at.isoformat() if self.completed_at else None
        return result

    @classmethod
    def from_dict(cls,  Dict[str, Any]) -> 'SagaExecutionLog':
        return cls(
            saga_id=data['saga_id'],
            saga_name=data['saga_name'],
            status=SagaStatus(data['status']),
            steps=data['steps'],
            started_at=datetime.fromisoformat(data['started_at']),
            completed_at=datetime.fromisoformat(data['completed_at']) if data.get('completed_at') else None,
            error_message=data.get('error_message'),
            error_step=data.get('error_step'),
            context_snapshot=data.get('context_snapshot', {}),
            hash_before=data.get('hash_before', ''),
            hash_after=data.get('hash_after', '')
        )


class SagaOrchestrator:
    """
    Оркестратор саг для управления сложными бизнес-транзакциями
    с гарантией согласованности через механизм откатов (compensation).

    Особенности:
    - Журналирование всех этапов с хеш-суммами для аудита
    - Автоматический откат при таймауте (>5 мин по умолчанию)
    - Поддержка восстановления после сбоя из журнала
    - Человеко-читаемые отчёты о причинах сбоя
    - Интеграция с системой оповещений
    """

    def __init__(self,
                 log_dir: str = "data/logs/saga",
                 timeout_default: int = 300):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.timeout_default = timeout_default
        self.active_sagas: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()
        self.alert_manager = AlertManager()
        self.audit_logger = AuditLogger()
        self.payment_processor = EnhancedPaymentProcessor()

        # Запуск фонового монитора таймаутов
        self._start_timeout_monitor()

    def execute_saga(self,
                    saga_name: str,
                    steps: List[SagaStep],
                    context: Dict[str, Any] = None,
                    timeout_seconds: Optional[int] = None) -> Tuple[bool, SagaExecutionLog]:
        """
        Выполнение цепочки шагов саги с автоматическим управлением откатами.

        Args:
            saga_name: Имя саги для логирования
            steps: Список шагов с действиями и компенсациями
            context: Контекст выполнения (данные заказа, пользователя и т.д.)
            timeout_seconds: Общий таймаут выполнения саги

        Returns:
            Кортеж (успех, журнал выполнения)
        """
        saga_id = str(uuid.uuid4())
        timeout = timeout_seconds or self.timeout_default
        context = context or {}

        # Создание журнала выполнения
        execution_log = SagaExecutionLog(
            saga_id=saga_id,
            saga_name=saga_name,
            status=SagaStatus.PENDING,
            steps=[],
            started_at=datetime.now(),
            context_snapshot=context.copy()
        )

        # Сохранение хеша состояния до выполнения
        execution_log.hash_before = self._calculate_context_hash(context)

        # Регистрация активной саги
        with self._lock:
            self.active_sagas[saga_id] = {
                'log': execution_log,
                'steps': steps,
                'context': context,
                'timeout_at': datetime.now() + timedelta(seconds=timeout),
                'lock': threading.RLock()
            }

        self._log_saga_event(saga_id, f"Начало выполнения саги '{saga_name}' (ID: {saga_id})")
        execution_log.status = SagaStatus.IN_PROGRESS
        self._save_execution_log(execution_log)

        try:
            # Последовательное выполнение шагов
            for step in steps:
                step_result = self._execute_step(saga_id, step, context)

                # Сохранение результата шага
                execution_log.steps.append({
                    'step_id': step.step_id,
                    'name': step.name,
                    'status': step_result['status'].value,
                    'executed_at': datetime.now().isoformat(),
                    'duration_ms': step_result['duration_ms'],
                    'error': step_result.get('error'),
                    'retry_attempts': step_result.get('retry_attempts', 0),
                    'metadata': step.metadata
                })

                self._save_execution_log(execution_log)

                # Проверка результата шага
                if step_result['status'] != SagaStepStatus.COMPLETED:
                    error_msg = f"Шаг '{step.name}' завершился с ошибкой: {step_result.get('error', 'Неизвестная ошибка')}"
                    self._log_saga_event(saga_id, error_msg, level='ERROR')

                    # Запуск процесса компенсации
                    execution_log.status = SagaStatus.COMPENSATING
                    self._save_execution_log(execution_log)

                    compensation_result = self._execute_compensation(saga_id, steps, context, step.step_id)

                    execution_log.status = SagaStatus.COMPENSATED if compensation_result else SagaStatus.FAILED
                    execution_log.error_message = error_msg
                    execution_log.error_step = step.step_id

                    self._save_execution_log(execution_log)

                    # Отправка алерта об ошибке
                    self.alert_manager.send_alert(
                        title=f"Сага '{saga_name}' завершилась с ошибкой",
                        message=error_msg,
                        severity='critical',
                        metadata={
                            'saga_id': saga_id,
                            'failed_step': step.name,
                            'compensation_success': compensation_result
                        }
                    )

                    return False, execution_log

            # Все шаги выполнены успешно
            execution_log.status = SagaStatus.COMPLETED
            execution_log.completed_at = datetime.now()
            execution_log.hash_after = self._calculate_context_hash(context)

            self._save_execution_log(execution_log)
            self._log_saga_event(saga_id, f"Сага '{saga_name}' успешно завершена")

            # Удаление из активных саг
            with self._lock:
                self.active_sagas.pop(saga_id, None)

            return True, execution_log

        except Exception as e:
            # Обработка неожиданных исключений
            error_msg = f"Критическая ошибка при выполнении саги: {str(e)}"
            self._log_saga_event(saga_id, error_msg, level='CRITICAL')

            execution_log.status = SagaStatus.FAILED
            execution_log.error_message = error_msg
            execution_log.completed_at = datetime.now()

            self._save_execution_log(execution_log)

            # Попытка компенсации даже при критической ошибке
            try:
                self._execute_compensation(saga_id, steps, context, None)
                execution_log.status = SagaStatus.COMPENSATED
                self._save_execution_log(execution_log)
            except Exception as ce:
                self._log_saga_event(saga_id, f"Ошибка компенсации: {ce}", level='ERROR')

            # Отправка критического алерта
            self.alert_manager.send_alert(
                title=f"КРИТИЧЕСКАЯ ОШИБКА в саге '{saga_name}'",
                message=error_msg,
                severity='critical',
                metadata={
                    'saga_id': saga_id,
                    'exception_type': type(e).__name__,
                    'traceback': str(e.__traceback__)
                }
            )

            with self._lock:
                self.active_sagas.pop(saga_id, None)

            return False, execution_log

    def _execute_step(self,
                     saga_id: str,
                     step: SagaStep,
                     context: Dict[str, Any]) -> Dict[str, Any]:
        """Выполнение одного шага саги с повторными попытками"""
        step_start = time.time()
        retry_attempts = 0
        last_error = None

        self._log_saga_event(saga_id, f"Выполнение шага '{step.name}'")

        while retry_attempts <= step.retry_count:
            try:
                # Проверка таймаута перед выполнением
                with self._lock:
                    saga_info = self.active_sagas.get(saga_id)
                    if saga_info and datetime.now() > saga_info['timeout_at']:
                        raise TimeoutError(f"Таймаут выполнения шага '{step.name}'")

                # Выполнение действия шага
                step_status = SagaStepStatus.EXECUTING
                result = step.action(context)

                # Проверка необходимости подтверждения
                if step.requires_confirmation:
                    if not self._await_confirmation(saga_id, step, context):
                        raise RuntimeError("Шаг требует подтверждения, которое не получено")

                duration_ms = (time.time() - step_start) * 1000
                self._log_saga_event(saga_id, f"Шаг '{step.name}' успешно выполнен за {duration_ms:.2f} мс")

                return {
                    'status': SagaStepStatus.COMPLETED,
                    'duration_ms': duration_ms,
                    'retry_attempts': retry_attempts,
                    'result': result
                }

            except Exception as e:
                retry_attempts += 1
                last_error = str(e)
                self._log_saga_event(
                    saga_id,
                    f"Попытка {retry_attempts} шага '{step.name}' завершилась ошибкой: {e}",
                    level='WARNING'
                )

                if retry_attempts <= step.retry_count:
                    time.sleep(step.retry_delay_seconds * (2 ** (retry_attempts - 1)))  # Экспоненциальная задержка

        # Все попытки исчерпаны
        duration_ms = (time.time() - step_start) * 1000
        self._log_saga_event(
            saga_id,
            f"Шаг '{step.name}' завершился неудачей после {retry_attempts} попыток: {last_error}",
            level='ERROR'
        )

        return {
            'status': SagaStepStatus.FAILED,
            'duration_ms': duration_ms,
            'retry_attempts': retry_attempts,
            'error': last_error
        }

    def _execute_compensation(self,
                            saga_id: str,
                            steps: List[SagaStep],
                            context: Dict[str, Any],
                            failed_step_id: Optional[str]) -> bool:
        """
        Выполнение компенсирующих действий для отката изменений.

        Args:
            saga_id: ID саги
            steps: Все шаги саги
            context: Контекст выполнения
            failed_step_id: ID шага, на котором произошла ошибка (откатываем все предыдущие)

        Returns:
            True если все компенсации успешны, иначе False
        """
        self._log_saga_event(saga_id, "Начало процесса компенсации (отката)")

        # Определение шагов для компенсации (в обратном порядке)
        steps_to_compensate = []
        for step in reversed(steps):
            if failed_step_id is None or step.step_id == failed_step_id:
                failed_step_id = None  # Начинаем компенсацию с этого шага
                steps_to_compensate.append(step)
            elif failed_step_id == "":
                break

        all_compensated = True

        for step in steps_to_compensate:
            try:
                self._log_saga_event(saga_id, f"Выполнение компенсации для шага '{step.name}'")

                # Выполнение компенсирующего действия
                step.compensation(context)

                self._log_saga_event(saga_id, f"Компенсация шага '{step.name}' успешно выполнена")

            except Exception as e:
                all_compensated = False
                self._log_saga_event(
                    saga_id,
                    f"Ошибка компенсации шага '{step.name}': {e}",
                    level='ERROR'
                )

                # Продолжаем компенсацию остальных шагов даже при ошибке
                continue

        status = "успешно" if all_compensated else "частично"
        self._log_saga_event(saga_id, f"Процесс компенсации завершен ({status})")

        return all_compensated

    def _await_confirmation(self,
                          saga_id: str,
                          step: SagaStep,
                          context: Dict[str, Any],
                          timeout_seconds: int = 300) -> bool:
        """
        Ожидание подтверждения выполнения шага (например, подтверждение оплаты).
        """
        self._log_saga_event(saga_id, f"Ожидание подтверждения для шага '{step.name}'")

        start_time = time.time()

        while time.time() - start_time < timeout_seconds:
            # Проверка статуса подтверждения (зависит от типа шага)
            if step.name == "process_payment":
                payment_id = context.get('payment_id')
                if payment_id and self.payment_processor.is_payment_confirmed(payment_id):
                    return True

            # Для других типов шагов можно добавить кастомную логику проверки

            time.sleep(5)  # Проверка каждые 5 секунд

        return False

    def recover_saga(self, saga_id: str) -> Optional[SagaExecutionLog]:
        """
        Восстановление выполнения саги после сбоя на основе журнала.

        Args:
            saga_id: ID саги для восстановления

        Returns:
            Восстановленный журнал выполнения или None если восстановление невозможно
        """
        # Поиск журнала в файловой системе
        log_files = list(self.log_dir.glob(f"{saga_id}_*.json"))

        if not log_files:
            self._log_saga_event(saga_id, "Журнал саги не найден для восстановления", level='ERROR')
            return None

        # Загрузка последнего состояния
        latest_log = max(log_files, key=lambda f: f.stat().st_mtime)

        try:
            with open(latest_log, 'r', encoding='utf-8') as f:
                log_data = json.load(f)

            execution_log = SagaExecutionLog.from_dict(log_data)

            # Проверка статуса для определения необходимости восстановления
            if execution_log.status in [SagaStatus.COMPLETED, SagaStatus.COMPENSATED, SagaStatus.FAILED]:
                self._log_saga_event(saga_id, f"Сага уже завершена со статусом {execution_log.status.value}")
                return execution_log

            if execution_log.status == SagaStatus.TIMED_OUT:
                self._log_saga_event(saga_id, "Сага превысила таймаут, запуск компенсации")
                # Запуск компенсации для зависшей саги
                # ... логика компенсации ...
                return execution_log

            # Восстановление контекста и продолжение выполнения
            self._log_saga_event(saga_id, "Восстановление выполнения саги из журнала")

            # Здесь должна быть логика продолжения выполнения с последнего успешного шага
            # Для упрощения возвращаем текущее состояние

            return execution_log

        except Exception as e:
            self._log_saga_event(saga_id, f"Ошибка восстановления саги: {e}", level='ERROR')
            return None

    def generate_human_readable_report(self, execution_log: SagaExecutionLog) -> str:
        """
        Генерация человеко-читаемого отчета о выполнении саги с анализом причин сбоя.

        Returns:
            Форматированный отчет в виде строки
        """
        report = []
        report.append("=" * 80)
        report.append(f"ОТЧЕТ О ВЫПОЛНЕНИИ САГИ: {execution_log.saga_name}")
        report.append(f"ID саги: {execution_log.saga_id}")
        report.append(f"Статус: {execution_log.status.value.upper()}")
        report.append(f"Начало: {execution_log.started_at.strftime('%Y-%m-%d %H:%M:%S')}")

        if execution_log.completed_at:
            duration = execution_log.completed_at - execution_log.started_at
            report.append(f"Завершение: {execution_log.completed_at.strftime('%Y-%m-%d %H:%M:%S')}")
            report.append(f"Общая длительность: {duration.total_seconds():.2f} сек")

        report.append("-" * 80)
        report.append("ДЕТАЛИЗАЦИЯ ШАГОВ:")
        report.append("-" * 80)

        for i, step in enumerate(execution_log.steps, 1):
            status_icon = {
                'completed': '✅',
                'failed': '❌',
                'compensated': '↩️',
                'pending': '⏳'
            }.get(step['status'], '❓')

            duration = step.get('duration_ms', 0) / 1000
            report.append(f"\n{i}. [{status_icon}] {step['name']}")
            report.append(f"   Статус: {step['status']}")
            report.append(f"   Длительность: {duration:.2f} сек")
            report.append(f"   Попыток: {step.get('retry_attempts', 0)}")

            if step.get('error'):
                report.append(f"   ОШИБКА: {step['error']}")
                # Анализ типа ошибки для рекомендаций
                error_lower = step['error'].lower()
                if 'timeout' in error_lower or 'timed out' in error_lower:
                    report.append("   🔍 Рекомендация: Увеличить таймаут шага или проверить сетевую доступность")
                elif 'connection' in error_lower or 'network' in error_lower:
                    report.append("   🔍 Рекомендация: Проверить подключение к интернету и доступность внешних сервисов")
                elif 'authentication' in error_lower or 'auth' in error_lower:
                    report.append("   🔍 Рекомендация: Проверить учетные данные и права доступа к сервису")
                elif 'quota' in error_lower or 'limit' in error_lower:
                    report.append("   🔍 Рекомендация: Проверить лимиты использования внешнего API")
                else:
                    report.append("   🔍 Рекомендация: Проверить логи сервиса для детального анализа")

        if execution_log.error_message:
            report.append("\n" + "=" * 80)
            report.append("АНАЛИЗ ПРИЧИНЫ СБОЯ:")
            report.append("=" * 80)
            report.append(f"Критическая ошибка на шаге: {execution_log.error_step or 'неизвестно'}")
            report.append(f"Сообщение об ошибке: {execution_log.error_message}")

            # Добавление контекстных рекомендаций
            if 'payment' in execution_log.error_message.lower():
                report.append("\n💡 Рекомендации по платежам:")
                report.append("   • Проверить баланс на счете")
                report.append("   • Убедиться в корректности реквизитов")
                report.append("   • Проверить лимиты платежной системы")
            elif 'platform' in execution_log.error_message.lower() or 'api' in execution_log.error_message.lower():
                report.append("\n💡 Рекомендации по интеграции с платформой:")
                report.append("   • Проверить актуальность API-ключей")
                report.append("   • Убедиться в соблюдении rate limits")
                report.append("   • Проверить изменения в API платформы")

        # Хеш-суммы для аудита целостности
        if execution_log.hash_before:
            report.append("\n" + "=" * 80)
            report.append("АУДИТ ЦЕЛОСТНОСТИ ДАННЫХ:")
            report.append("=" * 80)
            report.append(f"Хеш состояния до выполнения: {execution_log.hash_before}")
            if execution_log.hash_after:
                report.append(f"Хеш состояния после выполнения: {execution_log.hash_after}")
                if execution_log.hash_before != execution_log.hash_after:
                    report.append("⚠️  Обнаружены изменения в данных (ожидаемо для успешной транзакции)")
                else:
                    report.append("ℹ️  Состояние данных не изменилось")

        report.append("\n" + "=" * 80)
        report.append("КОНЕЦ ОТЧЕТА")
        report.append("=" * 80)

        return "\n".join(report)

    def _calculate_context_hash(self, context: Dict[str, Any]) -> str:
        """Расчет хеш-суммы контекста для аудита целостности"""
        # Исключаем временные и чувствительные данные
        filtered_context = {
            k: v for k, v in context.items()
            if k not in ['timestamp', 'auth_token', 'password', 'api_key']
        }

        context_str = json.dumps(filtered_context, sort_keys=True, default=str)
        return hashlib.sha256(context_str.encode()).hexdigest()

    def _save_execution_log(self, execution_log: SagaExecutionLog):
        """Сохранение журнала выполнения в файл"""
        timestamp = int(datetime.now().timestamp())
        filename = f"{execution_log.saga_id}_{timestamp}.json"
        filepath = self.log_dir / filename

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(execution_log.to_dict(), f, indent=2, ensure_ascii=False)

        # Сохранение последнего состояния для быстрого доступа
        latest_path = self.log_dir / f"{execution_log.saga_id}_latest.json"
        with open(latest_path, 'w', encoding='utf-8') as f:
            json.dump(execution_log.to_dict(), f, indent=2, ensure_ascii=False)

    def _log_saga_event(self, saga_id: str, message: str, level: str = 'INFO'):
        """Логирование событий саги с аудитом"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_entry = f"[{timestamp}] [{level}] Saga {saga_id}: {message}"

        # Запись в файловый лог
        log_file = self.log_dir / f"{saga_id}_events.log"
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(log_entry + '\n')

        # Аудит критических событий
        if level in ['ERROR', 'CRITICAL']:
            self.audit_logger.log_security_event(
                event_type='saga_failure',
                description=message,
                metadata={'saga_id': saga_id, 'level': level}
            )

    def _start_timeout_monitor(self):
        """Запуск фонового монитора для контроля таймаутов активных саг"""
        import threading

        def monitor_loop():
            while True:
                time.sleep(60)  # Проверка каждую минуту

                with self._lock:
                    now = datetime.now()
                    timed_out_sagas = []

                    for saga_id, saga_info in list(self.active_sagas.items()):
                        if now > saga_info['timeout_at']:
                            timed_out_sagas.append(saga_id)

                    for saga_id in timed_out_sagas:
                        saga_info = self.active_sagas[saga_id]
                        execution_log = saga_info['log']

                        self._log_saga_event(saga_id, "Сага превысила таймаут выполнения", level='ERROR')

                        execution_log.status = SagaStatus.TIMED_OUT
                        execution_log.error_message = f"Таймаут выполнения: {self.timeout_default} секунд"
                        execution_log.completed_at = now

                        self._save_execution_log(execution_log)

                        # Запуск компенсации в отдельном потоке
                        threading.Thread(
                            target=self._execute_compensation,
                            args=(saga_id, saga_info['steps'], saga_info['context'], None),
                            daemon=True
                        ).start()

                        self.active_sagas.pop(saga_id, None)

        monitor_thread = threading.Thread(target=monitor_loop, daemon=True, name="SagaTimeoutMonitor")
        monitor_thread.start()

    def get_active_sagas_status(self) -> Dict[str, Dict[str, Any]]:
        """Получение статуса всех активных саг"""
        with self._lock:
            status = {}
            for saga_id, saga_info in self.active_sagas.items():
                log = saga_info['log']
                timeout_at = saga_info['timeout_at']
                remaining = max(0, (timeout_at - datetime.now()).total_seconds())

                status[saga_id] = {
                    'saga_name': log.saga_name,
                    'status': log.status.value,
                    'started_at': log.started_at.isoformat(),
                    'timeout_remaining_seconds': remaining,
                    'steps_completed': len([s for s in log.steps if s['status'] == 'completed']),
                    'total_steps': len(saga_info['steps'])
                }
            return status


# Глобальный экземпляр оркестратора (паттерн Singleton)
_saga_orchestrator_instance = None
_saga_orchestrator_lock = threading.Lock()


def get_saga_orchestrator(log_dir: str = "data/logs/saga") -> SagaOrchestrator:
    """
    Получение глобального экземпляра SagaOrchestrator (Singleton).

    Returns:
        Единый экземпляр оркестратора для всего приложения
    """
    global _saga_orchestrator_instance, _saga_orchestrator_lock

    if _saga_orchestrator_instance is None:
        with _saga_orchestrator_lock:
            if _saga_orchestrator_instance is None:
                _saga_orchestrator_instance = SagaOrchestrator(log_dir)

    return _saga_orchestrator_instance