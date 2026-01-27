# AI_FREELANCE_AUTOMATION/services/notification/discord_service.py
"""
Discord notification service for AI Freelance Automation.
Sends alerts, reports, and system messages to configured Discord channels.
Fully integrated with the unified config and monitoring systems.
"""

import asyncio
import logging
from typing import Optional, Dict, Any, Union
from pathlib import Path

import aiohttp
from core.config.unified_config_manager import UnifiedConfigManager
from core.security.advanced_crypto_system import AdvancedCryptoSystem
from core.monitoring.intelligent_monitoring_system import IntelligentMonitoringSystem
from services.notification.base_notification_service import BaseNotificationService

logger = logging.getLogger("DiscordService")


class DiscordService(BaseNotificationService):
    """
    Sends notifications via Discord Webhooks or Bot API.
    Supports rich embeds, file attachments, and multi-channel routing.
    """

    SERVICE_NAME = "discord"

    def __init__(
        self,
        config_manager: Optional[UnifiedConfigManager] = None,
        crypto_system: Optional[AdvancedCryptoSystem] = None,
        monitoring_system: Optional[IntelligentMonitoringSystem] = None,
    ):
        super().__init__()
        self.config_manager = config_manager or UnifiedConfigManager()
        self.crypto = crypto_system or AdvancedCryptoSystem()
        self.monitoring = monitoring_system or IntelligentMonitoringSystem()

        # Load Discord-specific config
        self._config = self.config_manager.get_section("notifications.discord")
        self._enabled = self._config.get("enabled", False)
        self._webhook_url = None
        self._bot_token = None
        self._default_channel_id = None

        if not self._enabled:
            logger.info("Discord notification service is disabled in config.")
            return

        self._initialize_credentials()
        logger.info("✅ Discord notification service initialized.")

    def _initialize_credentials(self):
        """Decrypt and load Discord credentials securely."""
        try:
            discord_config = self._config.get("credentials", {})
            encrypted_webhook = discord_config.get("webhook_url_encrypted")
            encrypted_token = discord_config.get("bot_token_encrypted")
            self._default_channel_id = discord_config.get("default_channel_id")

            if encrypted_webhook:
                self._webhook_url = self.crypto.decrypt(encrypted_webhook).decode("utf-8")
            if encrypted_token:
                self._bot_token = self.crypto.decrypt(encrypted_token).decode("utf-8")

            if not (self._webhook_url or self._bot_token):
                raise ValueError("Either webhook URL or bot token must be provided.")

        except Exception as e:
            logger.error(f"❌ Failed to initialize Discord credentials: {e}")
            self._enabled = False
            raise

    async def send_message(
        self,
        message: str,
        title: Optional[str] = None,
        channel_id: Optional[str] = None,
        embed_fields: Optional[Dict[str, Any]] = None,
        file_path: Optional[Union[str, Path]] = None,
        priority: str = "normal",
    ) -> bool:
        """
        Send a message to Discord via webhook or bot.

        Args:
            message (str): Main message content.
            title (str, optional): Embed title.
            channel_id (str, optional): Target channel (only for bot mode).
            embed_fields (dict, optional): Additional fields for embed.
            file_path (str|Path, optional): File to attach.
            priority (str): 'low', 'normal', 'high', 'critical'

        Returns:
            bool: True if sent successfully.
        """
        if not self._enabled:
            logger.debug("Discord service disabled — skipping message send.")
            return False

        try:
            embed = self._build_embed(message, title, embed_fields, priority)
            payload = {"embeds": [embed]}

            if self._webhook_url:
                return await self._send_via_webhook(payload, file_path)
            elif self._bot_token and channel_id:
                return await self._send_via_bot(channel_id, payload, file_path)
            else:
                logger.warning("No valid Discord delivery method configured.")
                return False

        except Exception as e:
            logger.exception(f"💥 Error sending Discord message: {e}")
            await self.monitoring.log_anomaly(
                source="DiscordService",
                anomaly_type="notification_failure",
                details={"error": str(e), "message_preview": message[:50]},
            )
            return False

    def _build_embed(
        self,
        description: str,
        title: Optional[str] = None,
        fields: Optional[Dict[str, Any]] = None,
        priority: str = "normal"
    ) -> Dict[str, Any]:
        """Construct a Discord embed object."""
        color_map = {
            "low": 0xAAAAAA,
            "normal": 0x3498db,
            "high": 0xe67e22,
            "critical": 0xe74c3c,
        }
        color = color_map.get(priority, color_map["normal"])

        embed = {
            "title": title or "AI Freelance Automation Alert",
            "description": description,
            "color": color,
            "footer": {"text": "Autonomous AI Freelancer • Powered by Neural Intelligence"},
        }

        if fields:
            embed["fields"] = [
                {"name": str(k), "value": str(v), "inline": True}
                for k, v in fields.items()
            ]

        return embed

    async def _send_via_webhook(self, payload: dict, file_path: Optional[Union[str, Path]] = None) -> bool:
        """Send message using Discord webhook."""
        async with aiohttp.ClientSession() as session:
            try:
                if file_path and Path(file_path).exists():
                    with open(file_path, "rb") as f:
                        data = aiohttp.FormData()
                        data.add_field("payload_json", json.dumps(payload))
                        data.add_field("file", f, filename=Path(file_path).name)
                        resp = await session.post(self._webhook_url, data=data)
                else:
                    resp = await session.post(
                        self._webhook_url,
                        json=payload,
                        headers={"Content-Type": "application/json"}
                    )

                success = resp.status in (200, 204)
                if not success:
                    logger.warning(f"Discord webhook returned {resp.status}: {await resp.text()}")
                return success

            except Exception as e:
                logger.exception(f"Webhook send failed: {e}")
                return False

    async def _send_via_bot(self, channel_id: str, payload: dict, file_path: Optional[Union[str, Path]] = None) -> bool:
        """Send message using Discord bot token (not implemented in MVP — placeholder)."""
        logger.warning("Bot-based Discord sending is not implemented in current version.")
        # In future: use discord.py or raw REST API with bot token
        return False

    async def test_connection(self) -> bool:
        """Test if Discord integration is working."""
        if not self._enabled:
            return False
        result = await self.send_message(
            "This is a test message from AI Freelance Automation.",
            title="🔔 Connection Test",
            priority="low"
        )
        if result:
            logger.info("✅ Discord connection test passed.")
        else:
            logger.error("❌ Discord connection test failed.")
        return result

    def get_status(self) -> Dict[str, Any]:
        """Return service health status for monitoring."""
        return {
            "service": self.SERVICE_NAME,
            "enabled": self._enabled,
            "configured": bool(self._webhook_url or self._bot_token),
            "default_channel": self._default_channel_id,
        }