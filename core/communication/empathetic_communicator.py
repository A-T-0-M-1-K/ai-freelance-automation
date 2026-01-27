# AI_FREELANCE_AUTOMATION/core/communication/empathetic_communicator.py

"""
Empathetic Communicator — AI-driven communication module that interacts with clients
as a human freelancer would, using emotional intelligence, context awareness, and multilingual support.

Key responsibilities:
- Generate human-like, emotionally appropriate responses
- Maintain conversation context across sessions
- Adapt tone based on client sentiment
- Support 50+ languages via multilingual pipeline
- Log all interactions for audit and learning
- Recover gracefully from errors (self-healing)
"""

import asyncio
import logging
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from datetime import datetime

from core.dependency.service_locator import ServiceLocator
from core.config.unified_config_manager import UnifiedConfigManager
from core.security.audit_logger import AuditLogger
from core.learning.continuous_learning_system import ContinuousLearningSystem

# Local imports (relative to core.communication)
from .sentiment_analyzer import SentimentAnalyzer
from .context_manager import ConversationContextManager
from .multilingual_support import MultilingualSupport
from .tone_adjuster import ToneAdjuster


@dataclass
class Message:
    """Immutable message structure for internal processing."""
    content: str
    sender: str  # "client" or "system"
    timestamp: datetime
    language: str = "en"
    metadata: Optional[Dict[str, Any]] = None


class EmpatheticCommunicator:
    """
    Central communication engine that simulates human-like empathy and professionalism.
    Fully autonomous, self-monitoring, and integrated with AI services.
    """

    def __init__(
        self,
        config: Optional[UnifiedConfigManager] = None,
        service_locator: Optional[ServiceLocator] = None,
        audit_logger: Optional[AuditLogger] = None,
        learning_system: Optional[ContinuousLearningSystem] = None
    ):
        self.logger = logging.getLogger("EmpatheticCommunicator")
        self.config = config or UnifiedConfigManager()
        self.service_locator = service_locator or ServiceLocator()
        self.audit_logger = audit_logger or AuditLogger()
        self.learning_system = learning_system or ContinuousLearningSystem()

        # Initialize subcomponents
        self.sentiment_analyzer = SentimentAnalyzer(self.config)
        self.context_manager = ConversationContextManager(self.config)
        self.multilingual = MultilingualSupport(self.config)
        self.tone_adjuster = ToneAdjuster(self.config)

        self._initialized = False
        self.logger.info("🧠 EmpatheticCommunicator initialized (lazy-loaded components ready).")

    async def initialize(self) -> bool:
        """Lazy initialization of heavy AI models (e.g., sentiment, translation)."""
        if self._initialized:
            return True

        try:
            await self.sentiment_analyzer.load_model()
            await self.multilingual.initialize()
            await self.tone_adjuster.initialize()
            self._initialized = True
            self.logger.info("✅ EmpatheticCommunicator fully initialized.")
            return True
        except Exception as e:
            self.logger.error(f"❌ Failed to initialize communicator: {e}", exc_info=True)
            await self._trigger_recovery("initialization_failure", str(e))
            return False

    async def generate_response(
        self,
        client_message: str,
        job_id: str,
        client_id: str,
        platform: str = "unknown",
        language: str = "auto"
    ) -> str:
        """
        Generate an empathetic, context-aware response to a client message.

        Args:
            client_message (str): Raw message from client
            job_id (str): Unique job identifier
            client_id (str): Unique client identifier
            platform (str): Source platform (e.g., 'upwork', 'freelance_ru')
            language (str): Target language or 'auto' for detection

        Returns:
            str: Human-like, emotionally appropriate response
        """
        if not self._initialized:
            await self.initialize()

        # Normalize inputs
        client_message = client_message.strip()
        if not client_message:
            raise ValueError("Client message cannot be empty.")

        # Step 1: Detect language & translate to internal working language (e.g., English)
        detected_lang = await self.multilingual.detect_language(client_message)
        working_lang = "en"
        internal_msg = client_message
        if detected_lang != working_lang:
            internal_msg = await self.multilingual.translate(
                text=client_message,
                source_lang=detected_lang,
                target_lang=working_lang
            )

        # Step 2: Analyze sentiment
        sentiment = await self.sentiment_analyzer.analyze(internal_msg)
        self.logger.debug(f"Sentiment for job {job_id}: {sentiment}")

        # Step 3: Load conversation context
        context = await self.context_manager.get_context(job_id)
        context.add_message(Message(
            content=internal_msg,
            sender="client",
            timestamp=datetime.utcnow(),
            language=detected_lang
        ))

        # Step 4: Generate base response (placeholder — in real system, call LLM via ai_services)
        base_response = await self._generate_base_response(
            message=internal_msg,
            context=context,
            sentiment=sentiment,
            job_id=job_id
        )

        # Step 5: Adjust tone based on sentiment and client history
        adjusted_response = self.tone_adjuster.adjust(
            text=base_response,
            sentiment=sentiment,
            client_id=client_id,
            urgency=context.get_urgency_level()
        )

        # Step 6: Translate back to client's language if needed
        final_response = adjusted_response
        if language == "auto":
            target_lang = detected_lang
        else:
            target_lang = language

        if target_lang != working_lang:
            final_response = await self.multilingual.translate(
                text=adjusted_response,
                source_lang=working_lang,
                target_lang=target_lang
            )

        # Step 7: Log & store
        self._log_interaction(
            job_id=job_id,
            client_id=client_id,
            client_msg=client_message,
            ai_response=final_response,
            sentiment=sentiment,
            platform=platform
        )

        # Step 8: Update context
        context.add_message(Message(
            content=adjusted_response,
            sender="system",
            timestamp=datetime.utcnow(),
            language=working_lang
        ))
        await self.context_manager.save_context(job_id, context)

        # Step 9: Feed to learning system
        await self.learning_system.process_feedback(
            input_text=client_message,
            output_text=final_response,
            sentiment_score=sentiment.score,
            job_id=job_id,
            success=True  # Assume success; actual feedback may come later
        )

        return final_response

    async def _generate_base_response(
        self,
        message: str,
        context,
        sentiment,
        job_id: str
    ) -> str:
        """
        Placeholder for LLM integration. In production, this would call copywriting_service
        or a dedicated dialogue model via service_locator.
        """
        # Simulate intelligent response generation
        urgency_phrase = "I understand this is time-sensitive" if context.get_urgency_level() > 0.7 else ""
        empathy_phrase = (
            "I completely understand your concern." if sentiment.is_negative
            else "Great point!" if sentiment.is_positive
            else "Thank you for the update."
        )

        return f"{empathy_phrase} {urgency_phrase} I'm working on your request and will deliver high-quality results on time."

    def _log_interaction(
        self,
        job_id: str,
        client_id: str,
        client_msg: str,
        ai_response: str,
        sentiment: Any,
        platform: str
    ):
        """Log interaction for audit, analytics, and recovery."""
        log_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "job_id": job_id,
            "client_id": client_id,
            "platform": platform,
            "client_message": client_msg,
            "ai_response": ai_response,
            "sentiment_score": getattr(sentiment, 'score', 0.0),
            "sentiment_label": getattr(sentiment, 'label', 'neutral')
        }

        # Audit log (immutable, secure)
        self.audit_logger.log_event("COMMUNICATION_SENT", log_entry)

        # Application log
        self.logger.info(f"📨 Sent response to client {client_id} (job {job_id}) on {platform}")

    async def _trigger_recovery(self, error_type: str, details: str):
        """Escalate to emergency recovery system if available."""
        try:
            recovery = self.service_locator.get_service("emergency_recovery")
            if recovery:
                await recovery.handle_component_failure(
                    component="empathetic_communicator",
                    error_type=error_type,
                    details=details
                )
        except Exception as e:
            self.logger.critical(f"💥 Recovery escalation failed: {e}", exc_info=True)

    async def shutdown(self):
        """Graceful shutdown of all subcomponents."""
        await self.context_manager.flush_all()
        self.logger.info("🔌 EmpatheticCommunicator shut down gracefully.")