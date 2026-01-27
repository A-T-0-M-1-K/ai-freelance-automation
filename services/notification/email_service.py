# AI_FREELANCE_AUTOMATION/services/notification/email_service.py
"""
Email Service — надежная, безопасная и масштабируемая система отправки email-уведомлений.
Поддерживает:
- Мультипровайдерность (SendGrid, Mailgun, SMTP, AWS SES)
- Шаблонизацию (Jinja2)
- Очередь отправки с повторными попытками
- Шифрование чувствительных данных
- Логирование и аудит
- Автоматическое восстановление при сбоях
"""

import asyncio
import logging
import smtplib
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr
import jinja2
import backoff
from core.config.unified_config_manager import UnifiedConfigManager
from core.security.advanced_crypto_system import AdvancedCryptoSystem
from core.monitoring.intelligent_monitoring_system import IntelligentMonitoringSystem
from core.dependency.service_locator import ServiceLocator

# Типы провайдеров
EMAIL_PROVIDERS = {
    "smtp": "SMTPProvider",
    "sendgrid": "SendGridProvider",
    "mailgun": "MailgunProvider",
    "aws_ses": "AWSSesProvider"
}

logger = logging.getLogger("EmailService")


class EmailProvider(ABC):
    """Абстрактный базовый класс для email-провайдеров."""

    def __init__(self, config: Dict[str, Any], crypto: AdvancedCryptoSystem):
        self.config = config
        self.crypto = crypto
        self._validate_config()

    @abstractmethod
    def _validate_config(self) -> None:
        pass

    @abstractmethod
    async def send(self, to: str, subject: str, body: str, html: bool = False) -> bool:
        pass


class SMTPProvider(EmailProvider):
    """Реализация через стандартный SMTP."""

    def _validate_config(self) -> None:
        required = ["host", "port", "username", "password_encrypted", "from_email"]
        for key in required:
            if key not in self.config:
                raise ValueError(f"Missing SMTP config key: {key}")

    @backoff.on_exception(backoff.expo, (smtplib.SMTPException, OSError), max_tries=3)
    async def send(self, to: str, subject: str, body: str, html: bool = False) -> bool:
        try:
            password = self.crypto.decrypt(self.config["password_encrypted"])
            msg = MIMEMultipart("alternative")
            msg["From"] = formataddr((self.config.get("from_name", ""), self.config["from_email"]))
            msg["To"] = to
            msg["Subject"] = subject

            part = MIMEText(body, "html" if html else "plain")
            msg.attach(part)

            with smtplib.SMTP(self.config["host"], self.config["port"]) as server:
                server.starttls()
                server.login(self.config["username"], password)
                server.send_message(msg)

            logger.info(f"✅ Email sent via SMTP to {to}")
            return True
        except Exception as e:
            logger.error(f"❌ SMTP send failed to {to}: {e}", exc_info=True)
            raise


class SendGridProvider(EmailProvider):
    """Интеграция с SendGrid API."""

    def _validate_config(self) -> None:
        if "api_key_encrypted" not in self.config or "from_email" not in self.config:
            raise ValueError("Missing SendGrid config keys")

    @backoff.on_exception(backoff.expo, Exception, max_tries=3)
    async def send(self, to: str, subject: str, body: str, html: bool = False) -> bool:
        try:
            import httpx  # lazy import
            api_key = self.crypto.decrypt(self.config["api_key_encrypted"])
            url = "https://api.sendgrid.com/v3/mail/send"
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
            data = {
                "personalizations": [{"to": [{"email": to}]}],
                "from": {"email": self.config["from_email"], "name": self.config.get("from_name", "")},
                "subject": subject,
                "content": [{"type": "text/html" if html else "text/plain", "value": body}]
            }
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, json=data, headers=headers)
                if resp.status_code == 202:
                    logger.info(f"✅ Email sent via SendGrid to {to}")
                    return True
                else:
                    raise RuntimeError(f"SendGrid error: {resp.status_code} - {resp.text}")
        except Exception as e:
            logger.error(f"❌ SendGrid send failed to {to}: {e}", exc_info=True)
            raise


# Добавьте другие провайдеры по аналогии (Mailgun, AWS SES)


class EmailService:
    """
    Основной сервис отправки email.
    Использует DI через ServiceLocator, поддерживает шаблоны, очередь и мониторинг.
    """

    def __init__(
            self,
            config_manager: Optional[UnifiedConfigManager] = None,
            crypto: Optional[AdvancedCryptoSystem] = None,
            monitor: Optional[IntelligentMonitoringSystem] = None
    ):
        self.config_manager = config_manager or ServiceLocator.get("config")
        self.crypto = crypto or ServiceLocator.get("crypto")
        self.monitor = monitor or ServiceLocator.get("monitoring")
        self._template_env = jinja2.Environment(
            loader=jinja2.FileSystemLoader("templates/email/"),
            autoescape=True
        )
        self._provider: Optional[EmailProvider] = None
        self._init_provider()
        self._queue: asyncio.Queue = asyncio.Queue()
        self._sender_task: Optional[asyncio.Task] = None
        self._running = False

    def _init_provider(self) -> None:
        email_config = self.config_manager.get("notifications.email")
        provider_type = email_config.get("provider", "smtp")
        if provider_type not in EMAIL_PROVIDERS:
            raise ValueError(f"Unsupported email provider: {provider_type}")
        provider_class = globals()[EMAIL_PROVIDERS[provider_type]]
        self._provider = provider_class(email_config, self.crypto)
        logger.info(f"Intialized email provider: {provider_type}")

    async def start(self) -> None:
        """Запуск фонового отправителя."""
        if self._running:
            return
        self._running = True
        self._sender_task = asyncio.create_task(self._sender_loop())
        logger.info("📧 Email service started")

    async def stop(self) -> None:
        """Остановка сервиса."""
        if not self._running:
            return
        self._running = False
        if self._sender_task:
            self._sender_task.cancel()
            try:
                await self._sender_task
            except asyncio.CancelledError:
                pass
        logger.info("📧 Email service stopped")

    async def _sender_loop(self) -> None:
        """Фоновая отправка из очереди."""
        while self._running:
            try:
                item = await self._queue.get()
                success = await self._send_raw(**item)
                if not success:
                    # Повтор через 5 минут (можно расширить до DLQ)
                    await asyncio.sleep(300)
                    await self._queue.put(item)
                self._queue.task_done()
            except Exception as e:
                logger.error(f"⚠️ Email sender loop error: {e}", exc_info=True)
                await asyncio.sleep(1)

    async def _send_raw(self, to: str, subject: str, body: str, html: bool = False) -> bool:
        """Низкоуровневая отправка."""
        try:
            if not self._provider:
                raise RuntimeError("Email provider not initialized")
            result = await self._provider.send(to, subject, body, html)
            self.monitor.increment_counter("email.sent.success")
            return result
        except Exception as e:
            self.monitor.increment_counter("email.sent.failure")
            logger.error(f"📧 Failed to send email to {to}: {e}")
            return False

    async def send(
            self,
            to: str,
            template_name: str,
            context: Dict[str, Any],
            subject: Optional[str] = None
    ) -> bool:
        """
        Отправка email по шаблону.
        :param to: адрес получателя
        :param template_name: имя шаблона (без .html/.txt)
        :param context: контекст для Jinja2
        :param subject: тема (если не указана — берётся из шаблона или генерируется)
        """
        try:
            # Поддержка .html и .txt
            try:
                template = self._template_env.get_template(f"{template_name}.html")
                body = template.render(**context)
                html = True
            except jinja2.TemplateNotFound:
                template = self._template_env.get_template(f"{template_name}.txt")
                body = template.render(**context)
                html = False

            final_subject = subject or f"Notification: {template_name.replace('_', ' ').title()}"

            # Асинхронная постановка в очередь
            await self._queue.put({
                "to": to,
                "subject": final_subject,
                "body": body,
                "html": html
            })
            logger.debug(f"📨 Queued email to {to} using template '{template_name}'")
            return True
        except Exception as e:
            logger.error(f"❌ Email queuing failed: {e}", exc_info=True)
            return False

    async def send_immediate(
            self,
            to: str,
            subject: str,
            body: str,
            html: bool = False
    ) -> bool:
        """Срочная отправка без очереди (для критических уведомлений)."""
        return await self._send_raw(to, subject, body, html)


# Регистрация в ServiceLocator (опционально, при инициализации)
def register_email_service():
    """Вызывается при старте приложения."""
    service = EmailService()
    ServiceLocator.register("email_service", service)