"""
AI Freelance Automation — Notification Services Package
=====================================================

Этот пакет предоставляет унифицированный интерфейс для отправки уведомлений
через различные каналы: email, Telegram, Discord, вебхуки и др.

Основные принципы:
- Единая точка импорта для всех сервисов уведомлений
- Поддержка плагинов (hot-swap без перезапуска)
- Изоляция зависимостей между провайдерами
- Соответствие стандартам логирования и безопасности ядра

Использование:
    from services.notification import EmailService, TelegramService
    email = EmailService(config)
    await email.send(recipient="user@example.com", subject="...", body="...")

Автоматическая регистрация всех сервисов через service_registry.py.
"""

# Импорты для удобства внешнего использования
from .email_service import EmailService
from .telegram_service import TelegramService
from .discord_service import DiscordService
from .webhook_service import WebhookService

# Публичный API пакета
__all__ = [
    "EmailService",
    "TelegramService",
    "DiscordService",
    "WebhookService",
]

# Опционально: автоматическая регистрация в реестре при импорте
# (раскомментировать, если используется eager-регистрация)
# from services.service_registry import ServiceRegistry
# ServiceRegistry.register("notification.email", EmailService)
# ServiceRegistry.register("notification.telegram", TelegramService)
# ServiceRegistry.register("notification.discord", DiscordService)
# ServiceRegistry.register("notification.webhook", WebhookService)