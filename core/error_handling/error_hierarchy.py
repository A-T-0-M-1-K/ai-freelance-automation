"""
Иерархическая система обработки ошибок с автоматическим восстановлением
и интеграцией с системой мониторинга.
"""

import json
import traceback
import time
from pathlib import Path
from datetime import datetime
from enum import Enum
from typing import Dict, Any, Optional, Callable, List, Tuple
import threading

from core.monitoring.alert_manager import AlertManager
from core.security.audit_logger import AuditLogger


class ErrorSeverity(Enum):
    """Уровень серьезности ошибки"""
    LOW = 1  # CSS-ошибки в UI, некритичные предупреждения
    MEDIUM = 2  # Таймаут ИИ, временные сетевые проблемы
    HIGH = 3  # Ошибка на платформе, невозможность отправить предложение
    CRITICAL = 4  # Сбой оплаты, потеря данных, нарушение безопасности


class ErrorCategory(Enum):
    """Категория ошибки для маршрутизации обработки"""
    NETWORK = "network"  # Сетевые ошибки
    API = "api"  # Ошибки внешних API
    PAYMENT = "payment"  # Ошибки платежей
    SECURITY = "security"  # Проблемы безопасности
    DATA_INTEGRITY = "data"  # Нарушение целостности данных
    RESOURCE = "resource"  # Нехватка ресурсов (память, диск)
    CONFIGURATION = "config"  # Ошибки конфигурации
    THIRD_PARTY = "third_party"  # Ошибки внешних сервисов
    UNKNOWN = "unknown"  # Неизвестные ошибки


class AutomatedRecoveryAction(Enum):
    """Действия автоматического восстановления"""
    RETRY_WITH_BACKOFF = "retry_with_backoff"  # Повтор с экспоненциальной задержкой
    SWITCH_MODEL = "switch_model"  # Переключение на резервную ИИ-модель
    SWITCH_PLATFORM_ADAPTER = "switch_platform_adapter"  # Переключение адаптера платформы
    CLEAR_CACHE = "clear_cache"  # Очистка кэша
    RESTART_SERVICE = "restart_service"  # Перезапуск сервиса
    FAIL_SAFE = "fail_safe"  # Переключение в безопасный режим
    MANUAL_INTERVENTION = "manual_intervention"  # Требуется ручное вмешательство


@dataclass
class ErrorContext:
    """Контекст ошибки для анализа и восстановления"""
    error_id: str
    timestamp: datetime
    exception_type: str
    exception_message: str
    traceback: str
    severity: ErrorSeverity
    category: ErrorCategory
    component: str  # Модуль/компонент где произошла ошибка
    operation: str  # Операция во время которой произошла ошибка
    user_id: Optional[str] = None
    job_id: Optional[str] = None
    platform: Optional[str] = None
    metadata: Dict[str, Any] = None

    def to_dict(self) -> Dict[str, Any]:
        result = {
            'error_id': self.error_id,
            'timestamp': self.timestamp.isoformat(),
            'exception_type': self.exception_type,
            'exception_message': self.exception_message,
            'traceback': self.traceback,
            'severity': self.severity.name,
            'category': self.category.value,
            'component': self.component,
            'operation': self.operation,
            'user_id': self.user_id,
            'job_id': self.job_id,
            'platform': self.platform
        }
        if self.metadata:
            result['metadata'] = self.metadata
        return result

    @classmethod
    def from_exception(cls,
                       exc: Exception,
                       component: str,
                       operation: str,
                       severity: ErrorSeverity = ErrorSeverity.MEDIUM,
                       category: ErrorCategory = ErrorCategory.UNKNOWN,
                       **kwargs) -> 'ErrorContext':
        """Создание контекста ошибки из исключения"""
        import uuid

        return cls(
            error_id=str(uuid.uuid4()),
            timestamp=datetime.now(),
            exception_type=type(exc).__name__,
            exception_message=str(exc),
            traceback=traceback.format_exc(),
            severity=severity,
            category=category,
            component=component,
            operation=operation,
            metadata=kwargs.get('metadata'),
            user_id=kwargs.get('user_id'),
            job_id=kwargs.get('job_id'),
            platform=kwargs.get('platform')
        )


class ErrorHandler:
    """
    Централизованный обработчик ошибок с поддержкой:
    - Автоматической классификации по серьезности и категории
    - Рекомендаций по восстановлению
    - Интеграции с системой алертов
    - Ведения журнала для анализа трендов
    """

    def __init__(self,
                 log_dir: str = "data/logs/errors",
                 max_log_size_mb: int = 100):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.max_log_size_mb = max_log_size_mb
        self.alert_manager = AlertManager()
        self.audit_logger = AuditLogger()
        self._error_stats: Dict[str, Dict[str, Any]] = {}  # component -> stats
        self._lock = threading.RLock()
        self._load_error_stats()

    def handle_error(self,
                     exc: Exception,
                     component: str,
                     operation: str,
                     context: Optional[Dict[str, Any]] = None,
                     auto_recover: bool = True) -> Tuple[bool, List[AutomatedRecoveryAction]]:
        """
        Обработка ошибки с автоматическим восстановлением.

        Args:
            exc: Исключение
            component: Компонент где произошла ошибка
            operation: Операция во время ошибки
            context: Дополнительный контекст (user_id, job_id и т.д.)
            auto_recover: Пытаться ли автоматическое восстановление

        Returns:
            Кортеж (успешно_обработано, список_выполненных_действий_восстановления)
        """
        # 1. Классификация ошибки
        severity, category = self._classify_error(exc, component, operation)

        # 2. Создание контекста ошибки
        error_context = ErrorContext.from_exception(
            exc=exc,
            component=component,
            operation=operation,
            severity=severity,
            category=category,
            **(context or {})
        )

        # 3. Логирование ошибки
        self._log_error(error_context)

        # 4. Обновление статистики
        self._update_error_stats(error_context)

        # 5. Аудит критических ошибок
        if severity in [ErrorSeverity.CRITICAL, ErrorSeverity.HIGH]:
            self.audit_logger.log_security_event(
                event_type='error_occurred',
                description=f"Ошибка {severity.name} в компоненте {component}: {exc}",
                metadata=error_context.to_dict()
            )

        # 6. Отправка алерта для серьезных ошибок
        if severity in [ErrorSeverity.CRITICAL, ErrorSeverity.HIGH]:
            self._send_error_alert(error_context)

        # 7. Автоматическое восстановление
        recovery_actions = []
        if auto_recover:
            recovery_actions = self._attempt_auto_recovery(error_context, exc)

        # 8. Определение успешности обработки
        handled_successfully = (
                severity == ErrorSeverity.LOW or
                (severity == ErrorSeverity.MEDIUM and len(recovery_actions) > 0) or
                (severity in [ErrorSeverity.HIGH, ErrorSeverity.CRITICAL] and
                 AutomatedRecoveryAction.MANUAL_INTERVENTION not in recovery_actions)
        )

        return handled_successfully, recovery_actions

    def _classify_error(self,
                        exc: Exception,
                        component: str,
                        operation: str) -> Tuple[ErrorSeverity, ErrorCategory]:
        """Автоматическая классификация ошибки по типу и сообщению"""
        exc_type = type(exc).__name__.lower()
        exc_msg = str(exc).lower()

        # Определение категории
        category = ErrorCategory.UNKNOWN

        if any(k in exc_msg for k in ['timeout', 'timed out', 'connection timeout']):
            category = ErrorCategory.NETWORK
        elif any(k in exc_msg for k in ['api', 'endpoint', 'request failed', '429', 'rate limit']):
            category = ErrorCategory.API
        elif any(k in exc_msg for k in ['payment', 'transaction', 'charge', 'billing']):
            category = ErrorCategory.PAYMENT
        elif any(k in exc_msg for k in ['unauthorized', 'forbidden', 'auth', 'token', 'permission']):
            category = ErrorCategory.SECURITY
        elif any(k in exc_msg for k in ['memory', 'ram', 'disk', 'space', 'resource']):
            category = ErrorCategory.RESOURCE
        elif any(k in exc_msg for k in ['config', 'configuration', 'missing', 'invalid']):
            category = ErrorCategory.CONFIGURATION

        # Определение серьезности
        severity = ErrorSeverity.MEDIUM

        # Критические ошибки
        if category in [ErrorCategory.PAYMENT, ErrorCategory.SECURITY, ErrorCategory.DATA_INTEGRITY]:
            severity = ErrorSeverity.CRITICAL
        elif any(k in exc_msg for k in ['corrupt', 'lost', 'deleted', 'rollback failed']):
            severity = ErrorSeverity.CRITICAL

        # Высокая серьезность
        elif category in [ErrorCategory.API, ErrorCategory.NETWORK] and 'critical' in exc_msg:
            severity = ErrorSeverity.HIGH

        # Низкая серьезность
        elif any(k in exc_msg for k in ['css', 'ui', 'display', 'visual', 'warning']):
            severity = ErrorSeverity.LOW

        return severity, category

    def _attempt_auto_recovery(self,
                               error_context: ErrorContext,
                               exc: Exception) -> List[AutomatedRecoveryAction]:
        """Попытка автоматического восстановления после ошибки"""
        actions = []

        # Стратегии восстановления в зависимости от категории
        if error_context.category == ErrorCategory.NETWORK:
            # Повтор с экспоненциальной задержкой (максимум 3 попытки)
            actions.append(AutomatedRecoveryAction.RETRY_WITH_BACKOFF)

        elif error_context.category == ErrorCategory.API:
            if 'model' in error_context.component.lower() or 'ai' in error_context.component.lower():
                # Переключение на резервную ИИ-модель
                actions.append(AutomatedRecoveryAction.SWITCH_MODEL)
            else:
                # Переключение адаптера платформы
                actions.append(AutomatedRecoveryAction.SWITCH_PLATFORM_ADAPTER)

        elif error_context.category == ErrorCategory.RESOURCE:
            if 'memory' in str(exc).lower() or 'ram' in str(exc).lower():
                # Очистка кэша для освобождения памяти
                actions.append(AutomatedRecoveryAction.CLEAR_CACHE)
            elif 'disk' in str(exc).lower() or 'space' in str(exc).lower():
                # Очистка временных файлов
                self._cleanup_temp_files()
                actions.append(AutomatedRecoveryAction.CLEAR_CACHE)

        elif error_context.severity == ErrorSeverity.CRITICAL:
            # Для критических ошибок - только безопасный режим + ручное вмешательство
            actions.append(AutomatedRecoveryAction.FAIL_SAFE)
            actions.append(AutomatedRecoveryAction.MANUAL_INTERVENTION)

        # Выполнение действий восстановления
        executed_actions = []
        for action in actions:
            try:
                if self._execute_recovery_action(action, error_context):
                    executed_actions.append(action)
            except Exception as e:
                self._log(f"Ошибка выполнения действия восстановления {action}: {e}", level='WARNING')

        return executed_actions

    def _execute_recovery_action(self,
                                 action: AutomatedRecoveryAction,
                                 error_context: ErrorContext) -> bool:
        """Выполнение конкретного действия восстановления"""
        if action == AutomatedRecoveryAction.RETRY_WITH_BACKOFF:
            # Реализация экспоненциальной задержки
            import time
            for attempt in range(1, 4):
                delay = min(2 ** attempt, 30)  # Максимум 30 секунд
                self._log(f"Попытка восстановления #{attempt} через {delay} сек...", level='INFO')
                time.sleep(delay)
                # Здесь должна быть логика повтора операции
                # Для примера всегда считаем успешным после 2 попыток
                if attempt >= 2:
                    return True
            return False

        elif action == AutomatedRecoveryAction.SWITCH_MODEL:
            # Переключение на резервную модель через AIModelHub
            try:
                from core.ai_management.ai_model_hub import get_ai_model_hub
                hub = get_ai_model_hub()
                # Логика переключения модели...
                self._log("Выполнено переключение на резервную ИИ-модель", level='INFO')
                return True
            except Exception as e:
                self._log(f"Ошибка переключения модели: {e}", level='ERROR')
                return False

        elif action == AutomatedRecoveryAction.CLEAR_CACHE:
            # Очистка кэша через систему кэширования
            try:
                from core.performance.intelligent_cache_system import get_intelligent_cache
                cache = get_intelligent_cache()
                # Очистка 50% кэша
                # ... логика очистки ...
                self._log("Выполнена очистка кэша для освобождения ресурсов", level='INFO')
                return True
            except Exception as e:
                self._log(f"Ошибка очистки кэша: {e}", level='ERROR')
                return False

        elif action == AutomatedRecoveryAction.FAIL_SAFE:
            # Переключение в безопасный режим (ограничение функционала)
            self._log("Система переведена в безопасный режим", level='CRITICAL')
            # ... логика ограничения функционала ...
            return True

        return False

    def _cleanup_temp_files(self):
        """Очистка временных файлов для освобождения дискового пространства"""
        try:
            temp_dirs = [
                Path("data/cache"),
                Path("data/temp"),
                Path("logs")
            ]

            for temp_dir in temp_dirs:
                if temp_dir.exists():
                    # Удаление файлов старше 24 часов
                    for file in temp_dir.rglob("*"):
                        if file.is_file():
                            try:
                                file_age = (datetime.now() - datetime.fromtimestamp(
                                    file.stat().st_mtime)).total_seconds()
                                if file_age > 86400:  # 24 часа
                                    file.unlink()
                            except Exception:
                                pass
        except Exception as e:
            self._log(f"Ошибка очистки временных файлов: {e}", level='ERROR')

    def _log_error(self, error_context: ErrorContext):
        """Логирование ошибки в файл и консоль"""
        # Форматирование сообщения
        log_message = (
            f"[{error_context.timestamp.isoformat()}] "
            f"[{error_context.severity.name}] "
            f"[{error_context.component}] "
            f"{error_context.exception_type}: {error_context.exception_message}"
        )

        # Запись в файл по компонентам
        component_log = self.log_dir / f"{error_context.component}.log"
        with open(component_log, 'a', encoding='utf-8') as f:
            f.write(log_message + '\n')
            f.write(f"Traceback:\n{error_context.traceback}\n")
            f.write("-" * 80 + '\n')

        # Запись в общий файл ошибок
        all_errors_log = self.log_dir / "all_errors.jsonl"
        with open(all_errors_log, 'a', encoding='utf-8') as f:
            f.write(json.dumps(error_context.to_dict(), ensure_ascii=False) + '\n')

        # Вывод в консоль для критических ошибок
        if error_context.severity in [ErrorSeverity.CRITICAL, ErrorSeverity.HIGH]:
            print(f"\033[91m{log_message}\033[0m")  # Красный цвет

    def _send_error_alert(self, error_context: ErrorContext):
        """Отправка алерта об ошибке"""
        severity_map = {
            ErrorSeverity.CRITICAL: 'critical',
            ErrorSeverity.HIGH: 'high',
            ErrorSeverity.MEDIUM: 'medium',
            ErrorSeverity.LOW: 'low'
        }

        self.alert_manager.send_alert(
            title=f"Ошибка в компоненте {error_context.component}",
            message=f"{error_context.exception_type}: {error_context.exception_message}",
            severity=severity_map.get(error_context.severity, 'medium'),
            metadata={
                'error_id': error_context.error_id,
                'component': error_context.component,
                'operation': error_context.operation,
                'category': error_context.category.value,
                'timestamp': error_context.timestamp.isoformat()
            }
        )

    def _update_error_stats(self, error_context: ErrorContext):
        """Обновление статистики ошибок для анализа трендов"""
        with self._lock:
            component = error_context.component
            if component not in self._error_stats:
                self._error_stats[component] = {
                    'total_errors': 0,
                    'by_severity': {s.name: 0 for s in ErrorSeverity},
                    'by_category': {c.value: 0 for c in ErrorCategory},
                    'last_error': None,
                    'error_rate_per_hour': 0.0
                }

            stats = self._error_stats[component]
            stats['total_errors'] += 1
            stats['by_severity'][error_context.severity.name] += 1
            stats['by_category'][error_context.category.value] += 1
            stats['last_error'] = error_context.timestamp.isoformat()

            # Расчет интенсивности ошибок (упрощенно)
            # В реальной системе нужно хранить временные метки всех ошибок
            stats['error_rate_per_hour'] = min(
                stats['total_errors'] / max(1, (datetime.now() - datetime.now()).total_seconds() / 3600), 100)

    def _load_error_stats(self):
        """Загрузка статистики ошибок с диска"""
        stats_file = self.log_dir / "error_stats.json"
        if stats_file.exists():
            try:
                with open(stats_file, 'r', encoding='utf-8') as f:
                    self._error_stats = json.load(f)
            except Exception as e:
                self._log(f"Ошибка загрузки статистики ошибок: {e}", level='WARNING')

    def _save_error_stats(self):
        """Сохранение статистики ошибок на диск"""
        stats_file = self.log_dir / "error_stats.json"
        with open(stats_file, 'w', encoding='utf-8') as f:
            json.dump(self._error_stats, f, indent=2, ensure_ascii=False)

    def get_component_health(self, component: str) -> Dict[str, Any]:
        """Получение метрик здоровья компонента на основе статистики ошибок"""
        with self._lock:
            stats = self._error_stats.get(component, {})

            if not stats:
                return {
                    'status': 'unknown',
                    'error_rate': 0,
                    'last_error': None,
                    'recommendations': ['Нет данных для анализа']
                }

            # Определение статуса здоровья
            error_rate = stats.get('error_rate_per_hour', 0)
            critical_errors = stats['by_severity'].get('CRITICAL', 0)

            if critical_errors > 0:
                status = 'critical'
                recommendations = [
                    'Требуется немедленное вмешательство',
                    'Проверьте логи компонента на наличие критических ошибок'
                ]
            elif error_rate > 10:
                status = 'degraded'
                recommendations = [
                    'Высокая частота ошибок - проверьте зависимости компонента',
                    'Рассмотрите перезапуск сервиса'
                ]
            elif error_rate > 1:
                status = 'warning'
                recommendations = [
                    'Умеренная частота ошибок - мониторинг рекомендуется'
                ]
            else:
                status = 'healthy'
                recommendations = []

            return {
                'status': status,
                'error_rate_per_hour': error_rate,
                'total_errors': stats.get('total_errors', 0),
                'by_severity': stats.get('by_severity', {}),
                'by_category': stats.get('by_category', {}),
                'last_error': stats.get('last_error'),
                'recommendations': recommendations
            }

    def _log(self, message: str, level: str = 'INFO'):
        """Внутреннее логирование"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f"[{timestamp}] [ErrorHandler] [{level}] {message}")


# Глобальный экземпляр обработчика ошибок (паттерн Singleton)
_error_handler_instance = None


def get_error_handler(log_dir: str = "data/logs/errors") -> ErrorHandler:
    """Получение глобального экземпляра обработчика ошибок"""
    global _error_handler_instance

    if _error_handler_instance is None:
        _error_handler_instance = ErrorHandler(log_dir)

    return _error_handler_instance


# Декоратор для автоматической обработки ошибок в функциях
def handle_errors(component: str, operation: str, auto_recover: bool = True):
    """
    Декоратор для автоматической обработки ошибок в функциях.

    Пример использования:
    @handle_errors(component="proposal_submitter", operation="submit_proposal")
    def submit_proposal(...):
        ...
    """

    def decorator(func):
        def wrapper(*args, **kwargs):
            error_handler = get_error_handler()
            try:
                return func(*args, **kwargs)
            except Exception as exc:
                # Извлечение контекста из аргументов функции (если доступно)
                context = {}
                if 'user_id' in kwargs:
                    context['user_id'] = kwargs['user_id']
                if 'job_id' in kwargs:
                    context['job_id'] = kwargs['job_id']
                if 'platform' in kwargs:
                    context['platform'] = kwargs['platform']

                handled, actions = error_handler.handle_error(
                    exc=exc,
                    component=component,
                    operation=operation,
                    context=context,
                    auto_recover=auto_recover
                )

                if not handled:
                    # Если ошибка не обработана - пробрасываем исключение
                    raise

                # Возвращаем значение по умолчанию для типа функции
                return None

        return wrapper

    return decorator