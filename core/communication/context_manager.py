# AI_FREELANCE_AUTOMATION/core/communication/context_manager.py

"""
Context Manager for AI-driven client communication.
Maintains conversation state, recovers from failures, and ensures context continuity
across platforms (Upwork, Kwork, etc.).
"""

import json
import logging
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Union
from pathlib import Path

from core.config.unified_config_manager import UnifiedConfigManager
from core.security.audit_logger import AuditLogger
from core.performance.intelligent_cache_system import IntelligentCacheSystem
from core.monitoring.intelligent_monitoring_system import IntelligentMonitoringSystem


class ContextManager:
    """
    Manages conversational context per job or client.
    Ensures continuity, recovery, and efficient memory usage.
    """

    def __init__(
        self,
        config_manager: UnifiedConfigManager,
        audit_logger: AuditLogger,
        cache_system: IntelligentCacheSystem,
        monitoring_system: IntelligentMonitoringSystem,
        data_root: Union[str, Path] = "data/conversations"
    ):
        self.config = config_manager.get_section("communication")
        self.audit_logger = audit_logger
        self.cache = cache_system
        self.monitoring = monitoring_system
        self.data_root = Path(data_root)
        self.logger = logging.getLogger("ContextManager")

        # Ensure directory exists
        self.data_root.mkdir(parents=True, exist_ok=True)

        # Load limits from config
        self.max_messages_per_context = self.config.get("max_messages_per_context", 50)
        self.context_ttl_hours = self.config.get("context_ttl_hours", 72)
        self.auto_persist = self.config.get("auto_persist", True)

        self.logger.info("Intialized ContextManager with max %d messages, TTL %d hours",
                         self.max_messages_per_context, self.context_ttl_hours)

    def _get_context_path(self, job_id: str) -> Path:
        """Return filesystem path for a given job's context."""
        return self.data_root / job_id / "context.json"

    def _load_context_from_disk(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Load context from disk if it exists and is not expired."""
        path = self._get_context_path(job_id)
        if not path.exists():
            return None

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Check TTL
            last_update = datetime.fromisoformat(data.get("last_updated", ""))
            if datetime.now() - last_update > timedelta(hours=self.context_ttl_hours):
                self.logger.warning("Context for job %s expired. Discarding.", job_id)
                path.unlink(missing_ok=True)
                return None

            return data
        except (json.JSONDecodeError, OSError, ValueError) as e:
            self.logger.error("Failed to load context for job %s: %s", job_id, e)
            self.audit_logger.log_security_event(
                "context_load_failure",
                {"job_id": job_id, "error": str(e)}
            )
            return None

    def get_context(self, job_id: str) -> Dict[str, Any]:
        """
        Retrieve full context for a job. Attempts cache first, then disk.
        Returns empty context if none exists.
        """
        # Try cache
        cached = self.cache.get(f"ctx:{job_id}")
        if cached is not None:
            self.monitoring.increment_metric("context_cache_hit")
            return cached

        # Try disk
        disk_data = self._load_context_from_disk(job_id)
        if disk_data is not None:
            self.cache.set(f"ctx:{job_id}", disk_data, ttl=3600)
            self.monitoring.increment_metric("context_disk_load")
            return disk_data

        # Fresh context
        new_context = {
            "job_id": job_id,
            "messages": [],
            "metadata": {
                "platform": None,
                "client_id": None,
                "created_at": datetime.now().isoformat(),
                "last_updated": datetime.now().isoformat()
            }
        }
        self.monitoring.increment_metric("context_new_created")
        return new_context

    def update_context(
        self,
        job_id: str,
        message: Dict[str, Any],
        metadata_updates: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Add a new message to the context and persist it.
        Automatically trims old messages and updates timestamps.
        """
        context = self.get_context(job_id)

        # Append message
        context["messages"].append({
            "timestamp": datetime.now().isoformat(),
            "role": message.get("role", "user"),
            "content": message.get("content", ""),
            "platform_message_id": message.get("platform_message_id"),
            "attachments": message.get("attachments", [])
        })

        # Trim to max length
        if len(context["messages"]) > self.max_messages_per_context:
            removed = context["messages"][:len(context["messages"]) - self.max_messages_per_context]
            context["messages"] = context["messages"][-self.max_messages_per_context:]
            self.logger.debug("Trimmed %d old messages from context of job %s", len(removed), job_id)

        # Update metadata
        if metadata_updates:
            context["metadata"].update(metadata_updates)
        context["metadata"]["last_updated"] = datetime.now().isoformat()

        # Save to cache
        self.cache.set(f"ctx:{job_id}", context, ttl=3600)

        # Persist to disk if enabled
        if self.auto_persist:
            success = self._persist_context(job_id, context)
            if success:
                self.audit_logger.log_data_access("context_saved", {"job_id": job_id})
            return success

        return True

    def _persist_context(self, job_id: str, context: Dict[str, Any]) -> bool:
        """Save context to disk safely."""
        path = self._get_context_path(job_id)
        path.parent.mkdir(parents=True, exist_ok=True)

        temp_path = path.with_suffix(".tmp")
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(context, f, ensure_ascii=False, indent=2)
            temp_path.replace(path)
            return True
        except (OSError, TypeError) as e:
            self.logger.critical("Failed to persist context for job %s: %s", job_id, e)
            self.audit_logger.log_security_event(
                "context_persistence_failure",
                {"job_id": job_id, "error": str(e)}
            )
            return False

    def clear_context(self, job_id: str) -> bool:
        """Remove context from cache and disk (e.g., after job completion)."""
        self.cache.delete(f"ctx:{job_id}")
        path = self._get_context_path(job_id)
        try:
            if path.exists():
                path.unlink()
            (path.parent / "messages.json").unlink(missing_ok=True)  # legacy cleanup
            self.logger.info("Cleared context for job %s", job_id)
            return True
        except OSError as e:
            self.logger.error("Failed to delete context files for job %s: %s", job_id, e)
            return False

    def get_active_job_ids(self) -> List[str]:
        """Return list of all job IDs with active contexts (for recovery)."""
        if not self.data_root.exists():
            return []
        return [d.name for d in self.data_root.iterdir() if d.is_dir()]

    def recover_all_contexts(self) -> int:
        """
        On startup, ensure all contexts are loaded into cache.
        Returns number of recovered contexts.
        """
        recovered = 0
        for job_id in self.get_active_job_ids():
            ctx = self._load_context_from_disk(job_id)
            if ctx:
                self.cache.set(f"ctx:{job_id}", ctx, ttl=7200)
                recovered += 1
        self.logger.info("Recovered %d contexts on startup", recovered)
        return recovered