# AI_FREELANCE_AUTOMATION/core/monitoring/alert_manager.py
"""
Alert Manager — централизованная система управления оповещениями.
Обрабатывает события от IntelligentMonitoringSystem, классифицирует их по серьезности,
выполняет действия (логирование, уведомление, эскалация, автоматическое восстановление)
и сохраняет историю алертов для анализа и обучения.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Callable, Awaitable
from pathlib import Path

from core.config.unified_config_manager import UnifiedConfigManager
from core.security.audit_logger import AuditLogger
from services.notification.email_service import EmailService
from services.notification.telegram_service import TelegramService
from core.dependency.service_locator import ServiceLocator


class AlertSeverity(Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class AlertCategory(Enum):
    SYSTEM = "system"
    AI = "ai"
    PAYMENT = "payment"
    PLATFORM = "platform"
    SECURITY = "security"
    PERFORMANCE = "performance"
    COMMUNICATION = "communication"


class AlertAction(Enum):
    LOG = "log"
    NOTIFY = "notify"
    ESCALATE = "escalate"
    RECOVER = "recover"
    IGNORE = "ignore"


class Alert:
    def __init__(
        self,
        source: str,
        message: str,
        severity: AlertSeverity,
        category: AlertCategory,
        metadata: Optional[Dict[str, Any]] = None,
        timestamp: Optional[datetime] = None,
    ):
        self.id: str = f"alert_{int(datetime.now(timezone.utc).timestamp() * 1e6)}"
        self.source = source
        self.message = message
        self.severity = severity
        self.category = category
        self.metadata = metadata or {}
        self.timestamp = timestamp or datetime.now(timezone.utc)
        self.handled = False
        self.actions_taken: List[AlertAction] = []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "message": self.message,
            "severity": self.severity.value,
            "category": self.category.value,
            "metadata": self.metadata,
            "timestamp": self.timestamp.isoformat(),
            "handled": self.handled,
            "actions_taken": [a.value for a in self.actions_taken],
        }

    def __repr__(self) -> str:
        return f"<Alert id={self.id} severity={self.severity.value} source={self.source}>"


class AlertManager:
    """
    Централизованный менеджер оповещений.
    Поддерживает:
      - классификацию алертов
      - реакцию на основе правил из конфигурации
      - интеграцию с notification-сервисами
      - автоматическое восстановление через EmergencyRecovery
      - аудит и сохранение истории
    """

    def __init__(self, config_manager: UnifiedConfigManager):
        self.config = config_manager
        self.logger = logging.getLogger("AlertManager")
        self.alert_history: List[Alert] = []
        self._alert_log_path = Path("logs/monitoring/alerts.log")
        self._alert_log_path.parent.mkdir(parents=True, exist_ok=True)

        # Загрузка стратегий реакции из конфига
        self._reaction_rules = self.config.get("monitoring.alert_rules", default={})
        self._init_notification_services()
        self._audit_logger = AuditLogger()

    def _init_notification_services(self):
        """Ленивая инициализация сервисов уведомлений."""
        self._email_service: Optional[EmailService] = None
        self._telegram_service: Optional[TelegramService] = None
        try:
            self._email_service = ServiceLocator.get_service("email")
            self._telegram_service = ServiceLocator.get_service("telegram")
        except Exception as e:
            self.logger.warning(f"Не удалось инициализировать notification-сервисы: {e}")

    async def handle_alert(self, alert: Alert) -> None:
        """
        Обрабатывает входящий алерт согласно правилам.
        Выполняет действия: логирование, уведомление, восстановление и т.д.
        """
        self.logger.info(f"Получен алерт: {alert}")
        self.alert_history.append(alert)

        # Сохраняем в файл
        self._log_alert_to_file(alert)

        # Аудит безопасности
        if alert.category == AlertCategory.SECURITY or alert.severity in (
            AlertSeverity.CRITICAL,
            AlertSeverity.ERROR,
        ):
            self._audit_logger.log_security_event(
                event_type="alert_triggered",
                details=alert.to_dict(),
                severity=alert.severity.value,
            )

        # Определяем действия на основе правил
        actions = self._determine_actions(alert)
        alert.actions_taken = actions

        # Выполняем действия
        for action in actions:
            await self._execute_action(alert, action)

        alert.handled = True
        self.logger.debug(f"Алерт {alert.id} обработан. Действия: {[a.value for a in actions]}")

    def _determine_actions(self, alert: Alert) -> List[AlertAction]:
        """Определяет список действий на основе категории и серьезности."""
        rules = self._reaction_rules.get(alert.category.value, {})
        severity_str = alert.severity.value

        # По умолчанию — логировать всё
        actions = [AlertAction.LOG]

        if severity_str in rules:
            rule = rules[severity_str]
            if rule.get("notify", False):
                actions.append(AlertAction.NOTIFY)
            if rule.get("escalate", False):
                actions.append(AlertAction.ESCALATE)
            if rule.get("recover", False):
                actions.append(AlertAction.RECOVER)
        elif alert.severity in (AlertSeverity.CRITICAL, AlertSeverity.ERROR):
            # Фолбэк для критических ошибок
            actions.extend([AlertAction.NOTIFY, AlertAction.RECOVER])

        return actions

    async def _execute_action(self, alert: Alert, action: AlertAction) -> None:
        """Выполняет конкретное действие."""
        if action == AlertAction.LOG:
            pass  # уже залогировано
        elif action == AlertAction.NOTIFY:
            await self._send_notifications(alert)
        elif action == AlertAction.RECOVER:
            await self._trigger_recovery(alert)
        elif action == AlertAction.ESCALATE:
            await self._escalate_alert(alert)
        elif action == AlertAction.IGNORE:
            self.logger.debug(f"Алерт {alert.id} проигнорирован.")

    async def _send_notifications(self, alert: Alert) -> None:
        """Отправляет уведомления через доступные каналы."""
        subject = f"[{alert.severity.value.upper()}] {alert.source}"
        body = f"Категория: {alert.category.value}\nСообщение: {alert.message}\n\nМетаданные:\n{json.dumps(alert.metadata, indent=2, ensure_ascii=False)}"

        tasks: List[Awaitable] = []

        if self._email_service:
            tasks.append(self._email_service.send_alert(subject, body))
        if self._telegram_service:
            tasks.append(self._telegram_service.send_alert(body))

        if tasks:
            try:
                await asyncio.gather(*tasks, return_exceptions=True)
            except Exception as e:
                self.logger.error(f"Ошибка при отправке уведомлений: {e}")

    async def _trigger_recovery(self, alert: Alert) -> None:
        """Запускает механизм аварийного восстановления."""
        try:
            recovery = ServiceLocator.get_service("emergency_recovery")
            if recovery:
                await recovery.handle_alert(alert)
            else:
                self.logger.warning("EmergencyRecovery недоступен для восстановления.")
        except Exception as e:
            self.logger.error(f"Не удалось запустить восстановление: {e}")

    async def _escalate_alert(self, alert: Alert) -> None:
        """Эскалирует алерт (например, в админку или внешнюю систему)."""
        # В будущем можно добавить вебхук, Jira, Sentry и т.д.
        self.logger.critical(f"Эскалация алерта: {alert.id} — требует ручного вмешательства!")

    def _log_alert_to_file(self, alert: Alert) -> None:
        """Записывает алерт в файл в формате JSONL."""
        try:
            with self._alert_log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(alert.to_dict(), ensure_ascii=False) + "\n")
        except Exception as e:
            self.logger.error(f"Не удалось записать алерт в файл: {e}")

    def get_recent_alerts(
        self,
        limit: int = 100,
        severity: Optional[AlertSeverity] = None,
        category: Optional[AlertCategory] = None,
    ) -> List[Dict[str, Any]]:
        """Возвращает последние алерты с фильтрацией."""
        filtered = self.alert_history
        if severity:
            filtered = [a for a in filtered if a.severity == severity]
        if category:
            filtered = [a for a in filtered if a.category == category]
        return [a.to_dict() for a in filtered[-limit:]]

    async def shutdown(self) -> None:
        """Корректное завершение работы."""
        self.logger.info("AlertManager завершает работу...")
        # Ничего особенного не требуется, но можно закрыть соединения