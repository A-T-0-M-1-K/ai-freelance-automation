# core/ai_management/model_registry.py
"""
Central registry for all AI models used in the system.
Tracks model metadata, status, capabilities, and compatibility.
Supports hot-swapping, lazy loading, and performance monitoring.
Thread-safe and designed for autonomous operation.
"""

import asyncio
import logging
from typing import Dict, Any, Optional, Set, List
from dataclasses import dataclass, asdict
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class ModelMetadata:
    """Immutable metadata describing an AI model."""
    name: str
    task_type: str  # e.g., 'transcription', 'translation', 'copywriting'
    version: str
    model_path: Path
    supported_languages: Set[str]
    required_memory_mb: int
    expected_latency_ms: float
    provider: str  # e.g., 'openai', 'local', 'anthropic'
    is_fallback: bool = False
    tags: List[str] = None

    def __post_init__(self):
        if self.tags is None:
            self.tags = []


class ModelRegistry:
    """
    Thread-safe registry of all AI models available to the system.
    Used by IntelligentModelManager to select, load, and monitor models.
    """

    def __init__(self):
        self._models: Dict[str, ModelMetadata] = {}
        self._lock = asyncio.Lock()
        self._task_type_index: Dict[str, Set[str]] = {}  # task_type -> {model_name}
        logger.info("Intialized empty AI Model Registry.")

    async def register_model(self, metadata: ModelMetadata) -> bool:
        """
        Register a new model in the registry.
        Returns True if registered successfully, False if name conflict.
        """
        async with self._lock:
            if metadata.name in self._models:
                logger.warning(f"Model '{metadata.name}' already registered. Skipping.")
                return False

            self._models[metadata.name] = metadata

            # Update task-type index
            if metadata.task_type not in self._task_type_index:
                self._task_type_index[metadata.task_type] = set()
            self._task_type_index[metadata.task_type].add(metadata.name)

            logger.info(
                f"✅ Registered AI model: {metadata.name} "
                f"(task={metadata.task_type}, provider={metadata.provider})"
            )
            return True

    async def unregister_model(self, model_name: str) -> bool:
        """Remove a model from the registry. Returns True if removed."""
        async with self._lock:
            if model_name not in self._models:
                return False

            metadata = self._models.pop(model_name)
            self._task_type_index[metadata.task_type].discard(model_name)
            if not self._task_type_index[metadata.task_type]:
                del self._task_type_index[metadata.task_type]

            logger.info(f"🗑️ Unregistered model: {model_name}")
            return True

    async def get_model(self, model_name: str) -> Optional[ModelMetadata]:
        """Retrieve model metadata by name."""
        async with self._lock:
            return self._models.get(model_name)

    async def get_models_by_task(self, task_type: str) -> List[ModelMetadata]:
        """Get all models capable of handling a given task type."""
        async with self._lock:
            names = self._task_type_index.get(task_type, set())
            return [self._models[name] for name in names if name in self._models]

    async def get_all_models(self) -> List[ModelMetadata]:
        """Return a copy of all registered models."""
        async with self._lock:
            return list(self._models.values())

    async def has_model(self, model_name: str) -> bool:
        """Check if model exists in registry."""
        async with self._lock:
            return model_name in self._models

    async def update_model_tags(self, model_name: str, tags: List[str]) -> bool:
        """Update tags for an existing model (e.g., 'high_quality', 'low_cost')."""
        async with self._lock:
            if model_name not in self._models:
                return False
            self._models[model_name].tags = tags.copy()
            return True

    def to_dict(self) -> Dict[str, Any]:
        """Serialize registry state for diagnostics or persistence."""
        return {
            "models": {
                name: asdict(meta) for name, meta in self._models.items()
            },
            "task_index": {
                task: list(models) for task, models in self._task_type_index.items()
            }
        }

    async def validate_model_interface(self, model_name: str, expected_methods: Set[str]) -> bool:
        """
        Optional runtime validation: check if loaded model object has required methods.
        This method is a placeholder — actual validation happens in model loader.
        """
        # In practice, this would be called by IntelligentModelManager after loading.
        logger.debug(f"Interface validation for '{model_name}' is delegated to model loader.")
        return True


# Singleton instance (optional pattern — can also be managed via DI)
_MODEL_REGISTRY_INSTANCE: Optional[ModelRegistry] = None


def get_model_registry() -> ModelRegistry:
    """Global access point to the model registry (singleton)."""
    global _MODEL_REGISTRY_INSTANCE
    if _MODEL_REGISTRY_INSTANCE is None:
        _MODEL_REGISTRY_INSTANCE = ModelRegistry()
    return _MODEL_REGISTRY_INSTANCE