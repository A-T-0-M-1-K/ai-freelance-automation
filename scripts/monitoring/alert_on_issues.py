# AI_FREELANCE_AUTOMATION/scripts/monitoring/alert_on_issues.py
"""
Скрипт для генерации оповещений при обнаружении критических проблем в системе.
Интегрируется с core/monitoring/ и services/notification/.
Поддерживает многоканальные уведомления: email, Telegram, Discord, webhook.
"""

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Dict, Any, List

# Добавляем корень проекта в PYTHONPATH для корректного импорта
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.config.unified_config_manager import UnifiedConfigManager
from core.monitoring.intelligent_monitoring_system import IntelligentMonitoringSystem
from services.notification.email_service import EmailService
from services.notification.telegram_service import TelegramService
from services.notification.discord_service import DiscordService
from services.notification.webhook_service import WebhookService
from logs.log_config import setup_script_logger


class AlertOnIssues:
    """
    Скрипт-обёртка для активации оповещений на основе данных мониторинга.
    Может запускаться как standalone задача (например, по cron или из scheduler.py).
    """

    def __init__(self):
        self.logger = setup_script_logger("alert_on_issues")
        self.config = UnifiedConfigManager()
        self.monitoring = IntelligentMonitoringSystem(self.config)
        self.alert_channels = self._init_alert_channels()

    def _init_alert_channels(self) -> Dict[str, Any]:
        """Инициализирует доступные каналы оповещения на основе конфигурации."""
        channels = {}
        notify_cfg = self.config.get("notifications", {})

        if notify_cfg.get("email", {}).get("enabled", False):
            try:
                channels["email"] = EmailService(self.config)
            except Exception as e:
                self.logger.warning(f"❌ Не удалось инициализировать EmailService: {e}")

        if notify_cfg.get("telegram", {}).get("enabled", False):
            try:
                channels["telegram"] = TelegramService(self.config)
            except Exception as e:
                self.logger.warning(f"❌ Не удалось инициализировать TelegramService: {e}")

        if notify_cfg.get("discord", {}).get("enabled", False):
            try:
                channels["discord"] = DiscordService(self.config)
            except Exception as e:
                self.logger.warning(f"❌ Не удалось инициализировать DiscordService: {e}")

        if notify_cfg.get("webhook", {}).get("enabled", False):
            try:
                channels["webhook"] = WebhookService(self.config)
            except Exception as e:
                self.logger.warning(f"❌ Не удалось инициализировать WebhookService: {e}")

        if not channels:
            self.logger.warning("⚠️ Ни один канал оповещения не активирован!")

        return channels

    async def check_and_alert(self) -> bool:
        """
        Проверяет метрики мониторинга и отправляет оповещения при обнаружении аномалий.
        Возвращает True, если были отправлены оповещения.
        """
        self.logger.info("🔍 Проверка системы на наличие критических проблем...")

        try:
            # Получаем текущие аномалии от системы мониторинга
            anomalies = await self.monitoring.detect_anomalies()
            if not anomalies:
                self.logger.info("✅ Аномалий не обнаружено.")
                return False

            self.logger.warning(f"🚨 Обнаружено {len(anomalies)} аномалий. Отправка оповещений...")

            alert_message = self._format_alert_message(anomalies)
            sent_any = False

            for channel_name, service in self.alert_channels.items():
                try:
                    if channel_name == "email":
                        await service.send_email(
                            subject="🚨 Критическая аномалия в AI Freelance Automation",
                            body=alert_message,
                            recipients=self.config.get("notifications.email.recipients", [])
                        )
                    elif channel_name == "telegram":
                        await service.send_message(alert_message)
                    elif channel_name == "discord":
                        await service.send_message(alert_message)
                    elif channel_name == "webhook":
                        await service.send_webhook({
                            "title": "Critical System Alert",
                            "message": alert_message,
                            "severity": "critical",
                            "timestamp": asyncio.get_event_loop().time()
                        })
                    self.logger.info(f"📤 Оповещение отправлено через {channel_name}")
                    sent_any = True
                except Exception as e:
                    self.logger.error(f"❌ Ошибка при отправке через {channel_name}: {e}")

            return sent_any

        except Exception as e:
            self.logger.critical(f"💥 Ошибка при проверке аномалий: {e}", exc_info=True)
            return False

    def _format_alert_message(self, anomalies: List[Dict[str, Any]]) -> str:
        """Форматирует сообщение об аномалиях для отправки."""
        lines = ["❗ **Обнаружены критические проблемы в системе AI Freelance Automation:**\n"]
        for i, anomaly in enumerate(anomalies, 1):
            metric = anomaly.get("metric", "unknown")
            value = anomaly.get("value", "N/A")
            threshold = anomaly.get("threshold", "N/A")
            description = anomaly.get("description", "Без описания")
            lines.append(f"{i}. **{metric}**: {value} (порог: {threshold}) — {description}")

        lines.append("\n🛠️ Система автоматического восстановления уже активирована.")
        lines.append("Подробности в логах: `logs/monitoring/anomalies.log`")
        return "\n".join(lines)

    async def run(self):
        """Основной метод запуска скрипта."""
        self.logger.info("🟢 Запуск скрипта alert_on_issues...")
        try:
            alerted = await self.check_and_alert()
            if alerted:
                self.logger.info("✅ Оповещения успешно отправлены.")
            else:
                self.logger.info("ℹ️ Оповещения не требовались.")
        except KeyboardInterrupt:
            self.logger.info("🛑 Скрипт прерван пользователем.")
        except Exception as e:
            self.logger.critical(f"💥 Непредвиденная ошибка: {e}", exc_info=True)
            sys.exit(1)


# === Точка входа для standalone-запуска ===
if __name__ == "__main__":
    script = AlertOnIssues()
    asyncio.run(script.run())