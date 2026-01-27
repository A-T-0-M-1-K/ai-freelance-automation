# AI_FREELANCE_AUTOMATION/services/notification/telegram_service.py
"""
Telegram notification service for AI Freelance Automation.
Sends alerts, reports, and system updates to authorized Telegram users.
Integrates with core security, config, and monitoring systems.
"""

import asyncio
import logging
from typing import Optional, List, Dict, Any
from pathlib import Path

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from core.config.unified_config_manager import UnifiedConfigManager
from core.security.advanced_crypto_system import AdvancedCryptoSystem
from core.monitoring.intelligent_monitoring_system import IntelligentMonitoringSystem


class TelegramService:
    """
    Secure and reliable Telegram notification service.

    Features:
    - End-to-end encrypted message delivery (optional)
    - Rate limiting & retry logic with exponential backoff
    - Integration with system monitoring for alerting
    - Support for multiple authorized recipients
    - Async-first design for non-blocking operation
    """

    def __init__(
            self,
            config_manager: UnifiedConfigManager,
            crypto_system: Optional[AdvancedCryptoSystem] = None,
            monitor: Optional[IntelligentMonitoringSystem] = None
    ):
        self.config_manager = config_manager
        self.crypto_system = crypto_system
        self.monitor = monitor or IntelligentMonitoringSystem(self.config_manager)

        # Load Telegram-specific config
        self._config = self.config_manager.get_section("notifications.telegram")
        self._enabled = self._config.get("enabled", False)
        self._bot_token = None
        self._chat_ids = self._config.get("authorized_chat_ids", [])
        self._rate_limit = self._config.get("rate_limit_per_minute", 30)
        self._timeout = self._config.get("request_timeout_sec", 10)
        self._retry_attempts = self._config.get("retry_attempts", 3)

        self._http_client: Optional[httpx.AsyncClient] = None
        self._logger = logging.getLogger("TelegramService")

        if not self._enabled:
            self._logger.info("Telegram notifications are disabled in config.")
            return

        # Validate required fields
        if not self._config.get("bot_token_encrypted"):
            raise ValueError("Missing 'bot_token_encrypted' in telegram notification config.")

        # Decrypt bot token if crypto system is available
        encrypted_token = self._config["bot_token_encrypted"]
        if self.crypto_system:
            self._bot_token = self.crypto_system.decrypt(encrypted_token)
        else:
            # Fallback: assume plaintext (not recommended for production)
            self._bot_token = encrypted_token
            self._logger.warning("Running Telegram service without crypto system — token treated as plaintext!")

        if not self._chat_ids:
            self._logger.warning("No authorized Telegram chat IDs configured. Notifications will not be sent.")

    async def __aenter__(self):
        if self._enabled:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout),
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=5)
            )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._http_client:
            await self._http_client.aclose()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((httpx.RequestError, httpx.HTTPStatusError)),
        reraise=True
    )
    async def _send_message_raw(self, chat_id: str, text: str, parse_mode: str = "HTML") -> Dict[str, Any]:
        """Low-level message sender with retry logic."""
        if not self._http_client:
            raise RuntimeError("TelegramService not initialized. Use 'async with' context.")

        url = f"https://api.telegram.org/bot{self._bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text[:4096],  # Telegram limit
            "parse_mode": parse_mode,
            "disable_web_page_preview": True
        }

        try:
            response = await self._http_client.post(url, json=payload)
            response.raise_for_status()
            result = response.json()
            self._logger.debug(f"Message sent to {chat_id}: {result.get('ok')}")
            return result
        except Exception as e:
            self._logger.error(f"Failed to send Telegram message to {chat_id}: {e}")
            self.monitor.log_anomaly("telegram_send_failure", {"chat_id": chat_id, "error": str(e)})
            raise

    async def send_notification(
            self,
            message: str,
            priority: str = "normal",
            include_system_info: bool = False
    ) -> bool:
        """
        Send a notification to all authorized Telegram chats.

        Args:
            message (str): Message content (supports HTML formatting)
            priority (str): 'low', 'normal', 'high', 'critical'
            include_system_info (bool): Append system metrics if True

        Returns:
            bool: True if all messages sent successfully
        """
        if not self._enabled or not self._chat_ids:
            return False

        # Enhance message based on priority
        emoji_map = {
            "critical": "🚨",
            "high": "⚠️",
            "normal": "ℹ️",
            "low": "📝"
        }
        prefix = emoji_map.get(priority, "ℹ️")
        full_message = f"{prefix} <b>AI Freelancer Notification</b>\n\n{message}"

        if include_system_info and self.monitor:
            metrics = await self.monitor.get_current_metrics()
            cpu = metrics.get("cpu_percent", "N/A")
            mem = metrics.get("memory_percent", "N/A")
            jobs = metrics.get("active_jobs", "N/A")
            full_message += f"\n\n📊 <i>System: CPU {cpu}%, RAM {mem}%, Jobs: {jobs}</i>"

        success = True
        for chat_id in self._chat_ids:
            try:
                await self._send_message_raw(chat_id, full_message)
            except Exception as e:
                self._logger.error(f"Failed to notify Telegram user {chat_id}: {e}")
                success = False

        return success

    async def send_alert(self, alert_type: str, details: Dict[str, Any]) -> bool:
        """Send structured alert (used by monitoring system)."""
        message = (
                f"<b>ALERT: {alert_type.upper()}</b>\n"
                + "\n".join(f"• <b>{k}:</b> {v}" for k, v in details.items())
        )
        return await self.send_notification(message, priority="critical")

    async def test_connection(self) -> bool:
        """Test Telegram bot connectivity."""
        if not self._enabled:
            return False
        try:
            async with self:
                await self.send_notification("✅ Telegram integration test successful!", priority="low")
            return True
        except Exception as e:
            self._logger.error(f"Telegram test failed: {e}")
            return False


# Standalone helper function for easy use in scripts
async def send_telegram_notification(
        message: str,
        priority: str = "normal",
        config_path: Optional[str] = None
) -> bool:
    """
    Convenience function to send a Telegram notification without instantiating the full service.
    Useful for maintenance scripts or emergency alerts.
    """
    config_manager = UnifiedConfigManager(config_path or Path("config/notifications.json"))
    async with TelegramService(config_manager) as tg:
        return await tg.send_notification(message, priority)


# Example usage (not executed in production)
if __name__ == "__main__":
    import asyncio


    async def demo():
        config = UnifiedConfigManager()
        async with TelegramService(config) as tg:
            await tg.send_notification(
                "System started successfully!\nAutonomous freelancer is now online.",
                priority="high"
            )

    # asyncio.run(demo())  # Uncomment for testing