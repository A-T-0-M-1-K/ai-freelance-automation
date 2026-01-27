# plugins/integration_plugins/email_plugin.py
"""
Email Integration Plugin for AI Freelance Automation System.
Supports secure, templated email sending with attachments, retries, and audit logging.
Integrates with system-wide config, security, and monitoring subsystems.
"""

import os
import smtplib
import ssl
from pathlib import Path
from typing import Optional, List, Dict, Any, Union
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import logging

from core.config.unified_config_manager import UnifiedConfigManager
from core.security.advanced_crypto_system import AdvancedCryptoSystem
from core.monitoring.intelligent_monitoring_system import IntelligentMonitoringSystem
from core.dependency.service_locator import ServiceLocator

# Инициализация логгера модуля
logger = logging.getLogger(__name__)


class EmailPlugin:
    """
    Secure and reliable email sender plugin.
    Supports multiple providers (SMTP), templating, encryption of credentials,
    retry logic, and full audit trail.
    """

    PLUGIN_NAME = "email_integration"
    SUPPORTED_PROVIDERS = {"smtp"}

    def __init__(self):
        self.config_manager: UnifiedConfigManager = ServiceLocator.get_service("config_manager")
        self.crypto: AdvancedCryptoSystem = ServiceLocator.get_service("crypto_system")
        self.monitor: IntelligentMonitoringSystem = ServiceLocator.get_service("monitoring_system")

        # Загрузка конфигурации email
        self.email_config = self.config_manager.get_section("notifications").get("email", {})
        if not self.email_config:
            raise ValueError("Email configuration missing in 'notifications.email' section.")

        self.enabled = self.email_config.get("enabled", False)
        if not self.enabled:
            logger.warning("📧 Email plugin is disabled in config.")
            return

        self.provider = self.email_config.get("provider", "smtp").lower()
        if self.provider not in self.SUPPORTED_PROVIDERS:
            raise ValueError(f"Unsupported email provider: {self.provider}")

        # Расшифровка учетных данных
        encrypted_creds = self.email_config.get("credentials_encrypted")
        if not encrypted_creds:
            raise ValueError("Encrypted email credentials not found in config.")

        try:
            raw_creds = self.crypto.decrypt_data(encrypted_creds)
            self.credentials = eval(raw_creds)  # безопасно, т.к. контролируем источник
        except Exception as e:
            logger.critical("🔐 Failed to decrypt email credentials.", exc_info=True)
            raise RuntimeError("Email credential decryption failed") from e

        self.smtp_host = self.email_config.get("smtp_host")
        self.smtp_port = self.email_config.get("smtp_port", 587)
        self.use_tls = self.email_config.get("use_tls", True)
        self.sender_name = self.email_config.get("sender_name", "AI Freelancer")
        self.sender_email = self.credentials.get("email")
        self.password = self.credentials.get("password")

        # Валидация обязательных полей
        if not all([self.smtp_host, self.sender_email, self.password]):
            raise ValueError("Missing required SMTP/email fields in decrypted credentials or config.")

        logger.info(f"📧 Email plugin initialized for {self.sender_email} via {self.smtp_host}:{self.smtp_port}")

    def send_email(
        self,
        to: Union[str, List[str]],
        subject: str,
        body_text: Optional[str] = None,
        body_html: Optional[str] = None,
        template_name: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        attachments: Optional[List[Union[str, Path]]] = None,
        priority: str = "normal",
    ) -> bool:
        """
        Send an email using configured SMTP settings.

        Args:
            to: Recipient email(s)
            subject: Email subject
            body_text: Plain text body (optional if body_html provided)
            body_html: HTML body (optional if body_text provided)
            template_name: Name of template from /templates/email/ (e.g., 'bid_template.html')
            context: Context variables for template rendering
            attachments: List of file paths to attach
            priority: 'low', 'normal', 'high'

        Returns:
            bool: True if sent successfully
        """
        if not self.enabled:
            logger.warning("📧 Attempt to send email while plugin is disabled.")
            return False

        # Рендеринг шаблона, если указан
        if template_name:
            body_html = self._render_template(template_name, context or {})

        if not body_text and not body_html:
            raise ValueError("Either body_text, body_html, or template_name must be provided.")

        # Формирование сообщения
        msg = MIMEMultipart("alternative")
        msg["From"] = f"{self.sender_name} <{self.sender_email}>"
        msg["Subject"] = subject
        msg["X-Priority"] = {"low": "5", "normal": "3", "high": "1"}.get(priority, "3")

        if isinstance(to, list):
            msg["To"] = ", ".join(to)
            recipients = to
        else:
            msg["To"] = to
            recipients = [to]

        # Добавление частей тела
        if body_text:
            msg.attach(MIMEText(body_text, "plain", "utf-8"))
        if body_html:
            msg.attach(MIMEText(body_html, "html", "utf-8"))

        # Вложения
        if attachments:
            for file_path in attachments:
                path = Path(file_path)
                if not path.exists():
                    logger.warning(f"📎 Attachment not found: {path}")
                    continue
                with open(path, "rb") as f:
                    part = MIMEBase("application", "octet-stream")
                    part.set_payload(f.read())
                encoders.encode_base64(part)
                part.add_header("Content-Disposition", f'attachment; filename="{path.name}"')
                msg.attach(part)

        # Отправка с retry
        max_retries = self.email_config.get("max_retries", 3)
        retry_delay = self.email_config.get("retry_delay_sec", 2)

        for attempt in range(1, max_retries + 1):
            try:
                self._send_smtp(msg, recipients)
                self.monitor.log_metric("email.sent.success", 1)
                self._audit_log("EMAIL_SENT", {"to": recipients, "subject": subject})
                logger.info(f"✅ Email sent successfully to {recipients}")
                return True

            except Exception as e:
                logger.warning(f"📧 Email send attempt {attempt}/{max_retries} failed: {e}")
                self.monitor.log_metric("email.sent.failure", 1)
                if attempt == max_retries:
                    self._audit_log("EMAIL_SEND_FAILED", {"error": str(e), "to": recipients})
                    logger.error(f"❌ All attempts to send email failed after {max_retries} tries.")
                    return False
                else:
                    import time
                    time.sleep(retry_delay * attempt)  # exponential backoff

        return False

    def _render_template(self, template_name: str, context: Dict[str, Any]) -> str:
        """Render email template from /templates/email/ directory."""
        template_dir = Path("templates/email")
        if not template_dir.exists():
            raise FileNotFoundError(f"Email template directory not found: {template_dir}")

        template_path = template_dir / template_name
        if not template_path.exists():
            raise FileNotFoundError(f"Email template not found: {template_path}")

        with open(template_path, "r", encoding="utf-8") as f:
            template_str = f.read()

        # Простая подстановка {{ key }} → value
        for key, value in context.items():
            placeholder = "{{ " + str(key) + " }}"
            template_str = template_str.replace(placeholder, str(value))

        return template_str

    def _send_smtp(self, msg: MIMEMultipart, recipients: List[str]):
        """Low-level SMTP sending."""
        context_ssl = ssl.create_default_context()

        if self.use_tls:
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls(context=context_ssl)
                server.login(self.sender_email, self.password)
                server.send_message(msg, to_addrs=recipients)
        else:
            with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, context=context_ssl) as server:
                server.login(self.sender_email, self.password)
                server.send_message(msg, to_addrs=recipients)

    def _audit_log(self, event: str, details: Dict[str, Any]):
        """Log to system audit trail."""
        audit_logger = ServiceLocator.get_service("audit_logger")
        if audit_logger:
            audit_logger.log_event(
                source=self.PLUGIN_NAME,
                event_type=event,
                details=details
            )

    def health_check(self) -> Dict[str, Any]:
        """Return plugin health status for monitoring system."""
        return {
            "plugin": self.PLUGIN_NAME,
            "status": "healthy" if self.enabled else "disabled",
            "provider": self.provider,
            "sender": self.sender_email,
            "smtp_host": self.smtp_host,
            "enabled": self.enabled,
        }


# Регистрация плагина (опционально при старте)
def register_plugin():
    """Register this plugin in the PluginManager (called externally)."""
    from plugins.plugin_manager import PluginManager
    plugin_manager = ServiceLocator.get_service("plugin_manager")
    if plugin_manager:
        plugin_manager.register_plugin(EmailPlugin.PLUGIN_NAME, EmailPlugin())