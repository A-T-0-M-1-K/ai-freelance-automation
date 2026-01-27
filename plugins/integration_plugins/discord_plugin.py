# plugins/integration_plugins/discord_plugin.py
"""
Discord Integration Plugin for AI Freelance Automation System.

This plugin enables:
- Receiving notifications from the system via Discord DMs or channels
- Optional two-way communication (e.g., client messages forwarded to Discord)
- Secure token handling with encryption
- Hot-swappable without restart
- Full audit logging and error recovery

Implements the BasePlugin interface for compatibility with PluginManager.
"""

import asyncio
import logging
from typing import Dict, Any, Optional
from pathlib import Path

from discord.ext import commands
import discord

from plugins.base_plugin import BasePlugin
from core.config.unified_config_manager import UnifiedConfigManager
from core.security.advanced_crypto_system import AdvancedCryptoSystem
from core.monitoring.intelligent_monitoring_system import IntelligentMonitoringSystem
from services.notification.notification_service import NotificationService


class DiscordPlugin(BasePlugin):
    """
    Discord notification and interaction plugin.
    Runs as a background task managed by PluginManager.
    """

    PLUGIN_NAME = "discord_integration"
    PLUGIN_VERSION = "1.2.0"
    PLUGIN_DESCRIPTION = "Secure Discord integration for notifications and client messaging"

    def __init__(
        self,
        config_manager: UnifiedConfigManager,
        crypto_system: AdvancedCryptoSystem,
        monitoring_system: IntelligentMonitoringSystem,
        notification_service: NotificationService,
    ):
        super().__init__()
        self.config_manager = config_manager
        self.crypto_system = crypto_system
        self.monitoring = monitoring_system
        self.notification_service = notification_service

        self.logger = logging.getLogger(f"Plugins.{self.PLUGIN_NAME}")
        self._bot: Optional[commands.Bot] = None
        self._task: Optional[asyncio.Task] = None
        self._enabled = False
        self._config: Dict[str, Any] = {}

    async def initialize(self) -> bool:
        """Initialize plugin from config and validate credentials."""
        try:
            self._config = self.config_manager.get_section("notifications").get("discord", {})
            if not self._config.get("enabled", False):
                self.logger.info("Discord plugin is disabled in config.")
                return False

            # Decrypt bot token securely
            encrypted_token = self._config.get("encrypted_bot_token")
            if not encrypted_token:
                self.logger.error("❌ Missing 'encrypted_bot_token' in Discord config")
                return False

            token = self.crypto_system.decrypt_secret(encrypted_token)
            if not token:
                self.logger.error("❌ Failed to decrypt Discord bot token")
                return False

            # Initialize Discord client
            intents = discord.Intents.default()
            intents.message_content = True  # Only if needed for 2-way
            self._bot = commands.Bot(command_prefix="!", intents=intents)

            # Register event handlers
            self._bot.event(self._on_ready)
            self._bot.event(self._on_message)

            # Register internal notification handler
            self.notification_service.register_handler("discord", self._send_notification)

            self._enabled = True
            self.logger.info("✅ Discord plugin initialized successfully")
            return True

        except Exception as e:
            self.logger.exception(f"💥 Failed to initialize Discord plugin: {e}")
            await self.monitoring.log_anomaly(
                source="DiscordPlugin",
                severity="critical",
                message=str(e),
                context={"action": "initialize"}
            )
            return False

    async def start(self) -> bool:
        """Start the Discord bot in background."""
        if not self._enabled or not self._bot:
            return False

        try:
            token = self.crypto_system.decrypt_secret(self._config["encrypted_bot_token"])
            self._task = asyncio.create_task(self._run_bot(token))
            self.logger.info("🟢 Discord bot started in background")
            return True
        except Exception as e:
            self.logger.exception(f"💥 Failed to start Discord bot: {e}")
            return False

    async def _run_bot(self, token: str):
        """Run Discord bot with error recovery."""
        while self._enabled:
            try:
                await self._bot.start(token)
            except discord.LoginFailure:
                self.logger.critical("❌ Invalid Discord token — check encryption and config")
                break
            except Exception as e:
                self.logger.warning(f"⚠️ Discord bot disconnected: {e}. Reconnecting in 5s...")
                await asyncio.sleep(5)
                continue

    async def _on_ready(self):
        """Called when bot is ready."""
        self.logger.info(f"✅ Logged into Discord as {self._bot.user}")

    async def _on_message(self, message: discord.Message):
        """Handle incoming messages (optional two-way)."""
        if message.author == self._bot.user:
            return

        # Example: forward client messages to internal system
        if self._config.get("forward_client_messages", False):
            # This would require mapping Discord user ID → client_id
            # For now, log only
            self.logger.info(f"📩 Received Discord message from {message.author}: {message.content}")

    async def _send_notification(self, payload: Dict[str, Any]) -> bool:
        """Internal method called by NotificationService."""
        if not self._enabled:
            return False

        try:
            channel_id = self._config.get("notification_channel_id")
            user_id = self._config.get("notification_user_id")

            if not channel_id and not user_id:
                self.logger.warning("No target (channel/user) configured for Discord notifications")
                return False

            embed = discord.Embed(
                title=payload.get("title", "Notification"),
                description=payload.get("message", ""),
                color=0x5865F2,
                timestamp=discord.utils.utcnow()
            )
            embed.set_footer(text="AI Freelance Automation")

            if channel_id:
                channel = self._bot.get_channel(int(channel_id))
                if channel:
                    await channel.send(embed=embed)
                else:
                    self.logger.warning(f"Channel {channel_id} not found")
            elif user_id:
                user = await self._bot.fetch_user(int(user_id))
                if user:
                    await user.send(embed=embed)
                else:
                    self.logger.warning(f"User {user_id} not found")

            return True

        except Exception as e:
            self.logger.exception(f"❌ Failed to send Discord notification: {e}")
            return False

    async def stop(self) -> bool:
        """Gracefully stop the plugin."""
        self._enabled = False
        if self._bot:
            await self._bot.close()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self.logger.info("🛑 Discord plugin stopped")
        return True

    def get_status(self) -> Dict[str, Any]:
        """Return plugin health status for monitoring."""
        return {
            "name": self.PLUGIN_NAME,
            "version": self.PLUGIN_VERSION,
            "enabled": self._enabled,
            "running": self._task is not None and not self._task.done(),
            "bot_user": str(self._bot.user) if self._bot and self._bot.user else None,
        }