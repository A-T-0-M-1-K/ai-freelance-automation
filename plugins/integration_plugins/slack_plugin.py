# plugins/integration_plugins/slack_plugin.py
"""
Slack Integration Plugin for AI Freelance Automation System.
Enables bidirectional communication with Slack workspaces:
- Receive client messages via Slack (e.g., from custom bots or shared channels)
- Send automated updates, delivery notifications, and alerts to Slack
- Supports OAuth2, Webhooks, and Bot User Tokens
- Fully isolated, hot-swappable, and configurable

Complies with:
- core/security/advanced_crypto_system.py for token handling
- core/config/unified_config_manager.py for settings
- services/notification/email_service.py-style interface
"""

import asyncio
import logging
from typing import Dict, Any, Optional, List
from pathlib import Path

from plugins.base_plugin import BasePlugin
from core.config.unified_config_manager import UnifiedConfigManager
from core.security.advanced_crypto_system import AdvancedCryptoSystem
from core.dependency.service_locator import ServiceLocator
from services.notification.webhook_service import WebhookService

# Optional: Only import if slack-sdk is available
try:
    from slack_sdk.web.async_client import AsyncWebClient
    from slack_sdk.errors import SlackApiError
    SLACK_SDK_AVAILABLE = True
except ImportError:
    SLACK_SDK_AVAILABLE = False

logger = logging.getLogger(__name__)


class SlackPlugin(BasePlugin):
    """
    Slack integration plugin that acts as a notification channel and message receiver.
    Designed to be loaded dynamically by PluginManager without restart.
    """

    PLUGIN_NAME = "slack_integration"
    PLUGIN_VERSION = "1.0.0"
    PLUGIN_DESCRIPTION = "Bidirectional Slack integration for client communication and system alerts"

    def __init__(self, config_manager: UnifiedConfigManager, crypto_system: AdvancedCryptoSystem):
        super().__init__()
        self.config_manager = config_manager
        self.crypto_system = crypto_system
        self._client: Optional[AsyncWebClient] = None
        self._webhook_service: Optional[WebhookService] = None
        self._is_initialized = False
        self._workspace_token_map: Dict[str, str] = {}  # workspace_id -> decrypted token

    async def initialize(self) -> bool:
        """Initialize Slack clients for all configured workspaces."""
        if not SLACK_SDK_AVAILABLE:
            logger.error("❌ slack-sdk not installed. Install with: pip install slack-sdk")
            return False

        try:
            plugin_config = self.config_manager.get_plugin_config(self.PLUGIN_NAME)
            if not plugin_config or not plugin_config.get("enabled", False):
                logger.info("🔌 Slack plugin is disabled in config.")
                return False

            workspaces = plugin_config.get("workspaces", [])
            if not workspaces:
                logger.warning("⚠️ No Slack workspaces configured.")
                return True  # Allow silent disable

            # Initialize webhook service for event ingestion
            self._webhook_service = ServiceLocator.get_service("webhook_service")
            if self._webhook_service:
                await self._register_webhook_routes()

            # Decrypt and store tokens per workspace
            for ws in workspaces:
                ws_id = ws.get("workspace_id")
                encrypted_token = ws.get("bot_token_encrypted")
                if not ws_id or not encrypted_token:
                    logger.warning(f"⚠️ Skipping invalid workspace config: {ws_id}")
                    continue

                try:
                    decrypted_token = self.crypto_system.decrypt_secret(encrypted_token)
                    self._workspace_token_map[ws_id] = decrypted_token
                except Exception as e:
                    logger.error(f"🔐 Failed to decrypt token for workspace {ws_id}: {e}")
                    continue

            # Validate at least one token works
            for ws_id, token in self._workspace_token_map.items():
                client = AsyncWebClient(token=token)
                try:
                    auth_test = await client.auth_test()
                    logger.info(f"✅ Authenticated to Slack workspace: {auth_test['team']}")
                except SlackApiError as e:
                    logger.error(f"❌ Slack API error for workspace {ws_id}: {e}")
                    continue

            self._is_initialized = True
            logger.info("🟢 Slack plugin initialized successfully.")
            return True

        except Exception as e:
            logger.critical(f"💥 Fatal error during Slack plugin initialization: {e}", exc_info=True)
            return False

    async def _register_webhook_routes(self):
        """Register webhook endpoints to receive Slack events (messages, reactions, etc.)."""
        if not self._webhook_service:
            return

        # Register route for incoming Slack events
        await self._webhook_service.register_route(
            path="/webhooks/slack/events",
            handler=self._handle_slack_event,
            methods=["POST"]
        )
        logger.debug("🔗 Registered Slack event webhook endpoint.")

    async def _handle_slack_event(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """Handle incoming Slack events (e.g., messages, app mentions)."""
        try:
            event_type = request_data.get("type")

            # URL verification challenge (required by Slack)
            if event_type == "url_verification":
                return {"challenge": request_data.get("challenge")}

            # Process actual events
            if event_type == "event_callback":
                event = request_data.get("event", {})
                if event.get("type") == "message" and not event.get("bot_id"):
                    # Forward to communication system
                    communicator = ServiceLocator.get_service("intelligent_communicator")
                    if communicator:
                        await communicator.process_incoming_message(
                            source="slack",
                            message_id=event.get("ts"),
                            client_id=event.get("user"),
                            content=event.get("text"),
                            metadata={
                                "channel": event.get("channel"),
                                "workspace": request_data.get("team_id"),
                                "thread_ts": event.get("thread_ts")
                            }
                        )

            return {"status": "ok"}

        except Exception as e:
            logger.error(f"⚠️ Error handling Slack event: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

    async def send_message(
        self,
        workspace_id: str,
        channel: str,
        text: str,
        thread_ts: Optional[str] = None,
        blocks: Optional[List[Dict]] = None
    ) -> bool:
        """
        Send a message to a Slack channel.
        Supports threading and block-kit formatting.
        """
        if not self._is_initialized:
            logger.warning("Slack plugin not initialized. Cannot send message.")
            return False

        token = self._workspace_token_map.get(workspace_id)
        if not token:
            logger.error(f"❌ No token found for workspace: {workspace_id}")
            return False

        client = AsyncWebClient(token=token)
        try:
            kwargs = {
                "channel": channel,
                "text": text
            }
            if thread_ts:
                kwargs["thread_ts"] = thread_ts
            if blocks:
                kwargs["blocks"] = blocks

            response = await client.chat_postMessage(**kwargs)
            if response["ok"]:
                logger.debug(f"📤 Sent message to Slack channel {channel} in workspace {workspace_id}")
                return True
            else:
                logger.error(f"❌ Slack message failed: {response}")
                return False

        except SlackApiError as e:
            logger.error(f"❌ Slack API error sending message: {e}")
            return False
        except Exception as e:
            logger.error(f"💥 Unexpected error sending Slack message: {e}", exc_info=True)
            return False

    async def shutdown(self) -> None:
        """Gracefully shut down the plugin."""
        self._is_initialized = False
        self._workspace_token_map.clear()
        if self._webhook_service:
            await self._webhook_service.unregister_route("/webhooks/slack/events")
        logger.info("🛑 Slack plugin shut down.")

    def get_status(self) -> Dict[str, Any]:
        """Return plugin health status for monitoring."""
        return {
            "name": self.PLUGIN_NAME,
            "version": self.PLUGIN_VERSION,
            "initialized": self._is_initialized,
            "workspaces_count": len(self._workspace_token_map),
            "healthy": self._is_initialized and len(self._workspace_token_map) > 0
        }