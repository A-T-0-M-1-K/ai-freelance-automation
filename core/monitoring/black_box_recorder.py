"""
Система "черного ящика" для записи состояния системы перед критическими операциями.
Позволяет воспроизвести состояние системы при возникновении ошибки для отладки.
"""

import json
import pickle
import base64
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional
import threading
import sqlite3

from core.security.encryption_engine import EncryptionEngine


class BlackBoxRecorder:
    """
    Запись "черного ящика" - сохранение полного состояния системы
    перед выполнением критических операций для последующего анализа при сбоях.
    """

    def __init__(self,
                 storage_dir: str = "data/blackbox",
                 max_storage_mb: int = 500,
                 retention_days: int = 7):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.max_storage_mb = max_storage_mb
        self.retention_days = retention_days
        self.encryption_engine = EncryptionEngine()
        self._db_path = self.storage_dir / "blackbox_index.db"
        self._lock = threading.RLock()
        self._init_database()
        self._cleanup_old_records()

    def _init_database(self):
        """Инициализация SQLite базы данных для индексации записей"""
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS recordings (
                    id TEXT PRIMARY KEY,
                    operation_name TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    component TEXT NOT NULL,
                    user_id TEXT,
                    job_id TEXT,
                    platform TEXT,
                    file_path TEXT NOT NULL,
                    file_size_bytes INTEGER NOT NULL,
                    checksum TEXT NOT NULL,
                    error_occurred BOOLEAN DEFAULT FALSE,
                    error_id TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON recordings(timestamp)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_operation ON recordings(operation_name)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_error ON recordings(error_occurred)")

    def record_state_before_action(self,
                                   operation_name: str,
                                   component: str,
                                   context: Optional[Dict[str, Any]] = None) -> str:
        """
        Запись состояния системы перед выполнением критической операции.

        Args:
            operation_name: Название операции (например, "submit_proposal")
            component: Компонент выполняющий операцию
            context: Контекст операции (user_id, job_id и т.д.)

        Returns:
            Уникальный идентификатор записи
        """
        import uuid
        recording_id = str(uuid.uuid4())
        timestamp = datetime.now()

        # Сбор состояния системы
        snapshot = self._capture_system_snapshot(context or {})

        # Сериализация и шифрование
        serialized = pickle.dumps(snapshot)
        encrypted = self.encryption_engine.encrypt(serialized)

        # Сохранение на диск
        filename = f"{timestamp.strftime('%Y%m%d_%H%M%S')}_{operation_name}_{recording_id[:8]}.enc"
        file_path = self.storage_dir / filename
        file_path.write_bytes(encrypted)

        # Расчет контрольной суммы
        checksum = hashlib.sha256(encrypted).hexdigest()

        # Сохранение метаданных в БД
        with self._lock, sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                INSERT INTO recordings 
                (id, operation_name, timestamp, component, user_id, job_id, platform, file_path, file_size_bytes, checksum)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                recording_id,
                operation_name,
                timestamp.isoformat(),
                component,
                context.get('user_id') if context else None,
                context.get('job_id') if context else None,
                context.get('platform') if context else None,
                str(file_path.relative_to(self.storage_dir)),
                len(encrypted),
                checksum
            ))

        self._log(f"Запись черного ящика создана: {recording_id} ({operation_name})")
        self._enforce_storage_limit()

        return recording_id

    def _capture_system_snapshot(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Захват полного состояния системы для записи"""
        import psutil
        import os
        import platform

        # Состояние памяти
        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()

        # Состояние процессора
        cpu_percent = psutil.cpu_percent(interval=0.1)
        cpu_freq = psutil.cpu_freq()

        # Состояние диска
        disk = psutil.disk_usage('/')

        # Сетевые соединения
        net_connections = len(psutil.net_connections())

        # Переменные окружения (без чувствительных данных)
        safe_env = {
            k: v for k, v in os.environ.items()
            if not any(s in k.lower() for s in ['key', 'token', 'password', 'secret', 'auth'])
        }

        # Конфигурация приложения (без чувствительных данных)
        app_config = self._get_safe_app_config()

        # Активные задачи и очереди
        active_tasks = self._get_active_tasks()

        return {
            'timestamp': datetime.now().isoformat(),
            'context': context,
            'system_info': {
                'platform': platform.system(),
                'platform_release': platform.release(),
                'platform_version': platform.version(),
                'architecture': platform.machine(),
                'processor': platform.processor(),
                'cpu_cores_physical': psutil.cpu_count(logical=False),
                'cpu_cores_logical': psutil.cpu_count(logical=True),
                'cpu_percent': cpu_percent,
                'cpu_freq_current': cpu_freq.current if cpu_freq else None,
                'cpu_freq_min': cpu_freq.min if cpu_freq else None,
                'cpu_freq_max': cpu_freq.max if cpu_freq else None
            },
            'memory': {
                'total_gb': mem.total / (1024 ** 3),
                'available_gb': mem.available / (1024 ** 3),
                'used_gb': mem.used / (1024 ** 3),
                'percent': mem.percent,
                'swap_total_gb': swap.total / (1024 ** 3),
                'swap_used_gb': swap.used / (1024 ** 3),
                'swap_percent': swap.percent
            },
            'disk': {
                'total_gb': disk.total / (1024 ** 3),
                'used_gb': disk.used / (1024 ** 3),
                'free_gb': disk.free / (1024 ** 3),
                'percent': disk.percent
            },
            'network': {
                'connections_count': net_connections,
                'bytes_sent_mb': psutil.net_io_counters().bytes_sent / (1024 ** 2),
                'bytes_recv_mb': psutil.net_io_counters().bytes_recv / (1024 ** 2)
            },
            'environment': safe_env,
            'app_config': app_config,
            'active_tasks': active_tasks,
            'loaded_modules': list(sys.modules.keys())[:50]  # Первые 50 модулей
        }

    def _get_safe_app_config(self) -> Dict[str, Any]:
        """Получение безопасной (без секретов) конфигурации приложения"""
        try:
            # Загрузка конфигурации без чувствительных полей
            config_path = Path("config/app_config.json")
            if config_path.exists():
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)

                # Фильтрация чувствительных полей
                def filter_secrets(obj):
                    if isinstance(obj, dict):
                        return {
                            k: filter_secrets(v)
                            for k, v in obj.items()
                            if not any(
                                s in k.lower() for s in ['key', 'token', 'password', 'secret', 'auth', 'credential'])
                        }
                    elif isinstance(obj, list):
                        return [filter_secrets(item) for item in obj]
                    else:
                        return obj

                return filter_secrets(config)
            return {}
        except Exception as e:
            return {'error_loading_config': str(e)}

    def _get_active_tasks(self) -> List[Dict[str, Any]]:
        """Получение списка активных задач системы"""
        # В реальной системе здесь должна быть интеграция с очередями задач
        # Для примера возвращаем заглушку
        return [
            {'task_id': 'task_123', 'type': 'proposal_submission', 'status': 'in_progress',
             'started_at': datetime.now().isoformat()}
        ]

    def mark_error_occurred(self, recording_id: str, error_id: str):
        """Пометка записи как связанной с ошибкой"""
        with self._lock, sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "UPDATE recordings SET error_occurred = TRUE, error_id = ? WHERE id = ?",
                (error_id, recording_id)
            )
        self._log(f"Запись {recording_id} помечена как связанная с ошибкой {error_id}")

    def retrieve_recording(self, recording_id: str) -> Optional[Dict[str, Any]]:
        """Извлечение и расшифровка записи по идентификатору"""
        with self._lock, sqlite3.connect(self._db_path) as conn:
            cursor = conn.execute(
                "SELECT file_path, checksum FROM recordings WHERE id = ?",
                (recording_id,)
            )
            row = cursor.fetchone()

            if not row:
                self._log(f"Запись {recording_id} не найдена", level='WARNING')
                return None

            file_path = self.storage_dir / row[0]
            expected_checksum = row[1]

            if not file_path.exists():
                self._log(f"Файл записи {recording_id} не найден на диске", level='ERROR')
                return None

            # Загрузка и проверка целостности
            encrypted_data = file_path.read_bytes()
            actual_checksum = hashlib.sha256(encrypted_data).hexdigest()

            if actual_checksum != expected_checksum:
                self._log(f"Контрольная сумма записи {recording_id} не совпадает!", level='CRITICAL')
                return None

            # Расшифровка
            try:
                decrypted = self.encryption_engine.decrypt(encrypted_data)
                snapshot = pickle.loads(decrypted)
                return snapshot
            except Exception as e:
                self._log(f"Ошибка расшифровки записи {recording_id}: {e}", level='ERROR')
                return None

    def generate_diagnostic_report(self, recording_id: str) -> str:
        """Генерация диагностического отчета на основе записи черного ящика"""
        snapshot = self.retrieve_recording(recording_id)
        if not snapshot:
            return f"Не удалось загрузить запись {recording_id}"

        report = []
        report.append("=" * 80)
        report.append(f"ДИАГНОСТИЧЕСКИЙ ОТЧЕТ ЧЕРНОГО ЯЩИКА: {recording_id}")
        report.append("=" * 80)
        report.append(f"Время записи: {snapshot['timestamp']}")
        report.append(f"Операция: {snapshot['context'].get('operation_name', 'N/A')}")
        report.append(f"Компонент: {snapshot['context'].get('component', 'N/A')}")
        report.append(f"User ID: {snapshot['context'].get('user_id', 'N/A')}")
        report.append(f"Job ID: {snapshot['context'].get('job_id', 'N/A')}")
        report.append(f"Платформа: {snapshot['context'].get('platform', 'N/A')}")
        report.append("-" * 80)
        report.append("СОСТОЯНИЕ СИСТЕМЫ:")
        report.append(f"  • CPU: {snapshot['system_info']['cpu_percent']}% загрузки")
        report.append(
            f"  • RAM: {snapshot['memory']['used_gb']:.2f} ГБ / {snapshot['memory']['total_gb']:.2f} ГБ ({snapshot['memory']['percent']}%)")
        report.append(
            f"  • Диск: {snapshot['disk']['used_gb']:.2f} ГБ / {snapshot['disk']['total_gb']:.2f} ГБ ({snapshot['disk']['percent']}%)")
        report.append(f"  • Сеть: {snapshot['network']['connections_count']} активных соединений")
        report.append("-" * 80)
        report.append("АНАЛИЗ РИСКОВ:")

        # Анализ рисков на основе состояния
        risks = []

        if snapshot['memory']['percent'] > 90:
            risks.append("⚠️  КРИТИЧЕСКИЙ УРОВЕНЬ ИСПОЛЬЗОВАНИЯ ПАМЯТИ (>90%)")
        elif snapshot['memory']['percent'] > 80:
            risks.append("⚠️  ВЫСОКИЙ УРОВЕНЬ ИСПОЛЬЗОВАНИЯ ПАМЯТИ (>80%)")

        if snapshot['disk']['percent'] > 95:
            risks.append("⚠️  КРИТИЧЕСКИЙ УРОВЕНЬ ЗАПОЛНЕНИЯ ДИСКА (>95%)")
        elif snapshot['disk']['percent'] > 90:
            risks.append("⚠️  ВЫСОКИЙ УРОВЕНЬ ЗАПОЛНЕНИЯ ДИСКА (>90%)")

        if snapshot['system_info']['cpu_percent'] > 95:
            risks.append("⚠️  КРИТИЧЕСКАЯ ЗАГРУЗКА CPU (>95%)")

        if not risks:
            risks.append("✅ Нет выявленных критических рисков в состоянии системы")

        for risk in risks:
            report.append(f"  {risk}")

        report.append("-" * 80)
        report.append("РЕКОМЕНДАЦИИ:")
        recommendations = [
            "1. Для операций с высоким потреблением памяти рассмотрите увеличение объема RAM",
            "2. Настройте автоматическую очистку временных файлов при заполнении диска >85%",
            "3. Используйте квантизацию моделей для снижения потребления памяти",
            "4. Настройте мониторинг ресурсов с алертами при превышении порогов"
        ]

        for rec in recommendations:
            report.append(f"  {rec}")

        report.append("=" * 80)
        report.append("КОНЕЦ ОТЧЕТА")
        report.append("=" * 80)

        return "\n".join(report)

    def _cleanup_old_records(self):
        """Очистка старых записей по политике хранения"""
        cutoff_date = datetime.now() - timedelta(days=self.retention_days)
        cutoff_timestamp = cutoff_date.isoformat()

        with self._lock, sqlite3.connect(self._db_path) as conn:
            # Получение записей для удаления
            cursor = conn.execute(
                "SELECT id, file_path FROM recordings WHERE timestamp < ?",
                (cutoff_timestamp,)
            )
            records_to_delete = cursor.fetchall()

            for record_id, file_path in records_to_delete:
                # Удаление файла
                full_path = self.storage_dir / file_path
                try:
                    if full_path.exists():
                        full_path.unlink()
                except Exception as e:
                    self._log(f"Ошибка удаления файла {file_path}: {e}", level='WARNING')

            # Удаление из БД
            conn.execute("DELETE FROM recordings WHERE timestamp < ?", (cutoff_timestamp,))

            if records_to_delete:
                self._log(
                    f"Удалено {len(records_to_delete)} старых записей черного ящика (старше {self.retention_days} дней)")

    def _enforce_storage_limit(self):
        """Принудительное соблюдение лимита хранилища"""
        # Получение текущего размера хранилища
        total_size = sum(f.stat().st_size for f in self.storage_dir.glob("*.enc") if f.is_file()) / (1024 ** 2)  # МБ

        if total_size > self.max_storage_mb:
            # Удаление самых старых записей до достижения лимита
            with sqlite3.connect(self._db_path) as conn:
                cursor = conn.execute("""
                    SELECT id, file_path 
                    FROM recordings 
                    ORDER BY timestamp ASC
                """)

                records = cursor.fetchall()
                size_to_free = total_size - (self.max_storage_mb * 0.8)  # Освободить до 80% лимита

                freed_size = 0
                deleted_count = 0

                for record_id, file_path in records:
                    if freed_size >= size_to_free:
                        break

                    full_path = self.storage_dir / file_path
                    if full_path.exists():
                        file_size = full_path.stat().st_size / (1024 ** 2)
                        try:
                            full_path.unlink()
                            freed_size += file_size
                            deleted_count += 1
                        except Exception as e:
                            self._log(f"Ошибка удаления файла {file_path}: {e}", level='WARNING')

                # Удаление из БД
                if deleted_count > 0:
                    conn.execute(f"DELETE FROM recordings WHERE id IN ({','.join('?' * deleted_count)})",
                                 [r[0] for r in records[:deleted_count]])
                    self._log(f"Освобождено {freed_size:.2f} МБ путем удаления {deleted_count} старых записей")

    def _log(self, message: str, level: str = 'INFO'):
        """Логирование событий черного ящика"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f"[{timestamp}] [BlackBoxRecorder] [{level}] {message}")


# Глобальный экземпляр рекордера (паттерн Singleton)
_black_box_recorder_instance = None


def get_black_box_recorder(storage_dir: str = "data/blackbox") -> BlackBoxRecorder:
    """Получение глобального экземпляра рекордера черного ящика"""
    global _black_box_recorder_instance

    if _black_box_recorder_instance is None:
        _black_box_recorder_instance = BlackBoxRecorder(storage_dir)

    return _black_box_recorder_instance


# Контекстный менеджер для автоматической записи черного ящика
from contextlib import contextmanager


@contextmanager
def black_box_context(operation_name: str, component: str, **context):
    """
    Контекстный менеджер для автоматической записи состояния перед операцией
    и пометки записи при возникновении ошибки.

    Пример использования:
    with black_box_context("submit_proposal", "proposal_engine", job_id=job_id, platform=platform):
        # Критическая операция
        submit_proposal(...)
    """
    recorder = get_black_box_recorder()
    recording_id = recorder.record_state_before_action(operation_name, component, context)

    try:
        yield recording_id
    except Exception as e:
        # При ошибке помечаем запись
        from core.error_handling.error_hierarchy import get_error_handler
        error_handler = get_error_handler()
        error_context = error_handler.handle_error(
            exc=e,
            component=component,
            operation=operation_name,
            context=context,
            auto_recover=False  # Не пытаться восстановить внутри контекста
        )
        recorder.mark_error_occurred(recording_id,
                                     error_context[0].error_id if hasattr(error_context[0], 'error_id') else 'unknown')
        raise