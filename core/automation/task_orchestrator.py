# AI_FREELANCE_AUTOMATION/core/automation/task_orchestrator.py

"""
Task Orchestrator — координатор выполнения заказов.
Разбивает задачу на подзадачи, назначает AI-сервисы, управляет параллельным выполнением,
контролирует качество и обеспечивает отказоустойчивость.
"""

import asyncio
import logging
import traceback
from typing import Dict, List, Any, Optional, Union
from dataclasses import dataclass, asdict
from pathlib import Path

from core.dependency.service_locator import ServiceLocator
from core.config.unified_config_manager import UnifiedConfigManager
from core.monitoring.intelligent_monitoring_system import IntelligentMonitoringSystem
from core.security.audit_logger import AuditLogger
from core.learning.continuous_learning_system import ContinuousLearningSystem
from services.ai_services.transcription_service import TranscriptionService
from services.ai_services.translation_service import TranslationService
from services.ai_services.copywriting_service import CopywritingService
from services.ai_services.editing_service import EditingService
from services.ai_services.proofreading_service import ProofreadingService

logger = logging.getLogger("TaskOrchestrator")
audit_logger = AuditLogger("task_orchestrator")


@dataclass
class Subtask:
    id: str
    type: str  # "transcription", "translation", "copywriting", etc.
    input_data: Union[str, Path]
    output_path: Path
    status: str = "pending"  # pending → running → completed / failed
    retries: int = 0
    max_retries: int = 3
    metadata: Dict[str, Any] = None


@dataclass
class JobContext:
    job_id: str
    client_id: str
    job_type: str  # e.g., "transcription_en_to_ru"
    source_file: Optional[Path] = None
    target_language: Optional[str] = None
    tone: Optional[str] = None
    word_count: Optional[int] = None
    deadline: Optional[str] = None
    requirements: Dict[str, Any] = None


class TaskOrchestrator:
    """
    Основной оркестратор задач. Полностью автономен.
    """

    def __init__(
        self,
        config: UnifiedConfigManager,
        monitoring: Optional[IntelligentMonitoringSystem] = None,
        service_locator: Optional[ServiceLocator] = None,
        learning_system: Optional[ContinuousLearningSystem] = None
    ):
        self.config = config
        self.monitoring = monitoring or IntelligentMonitoringSystem(config)
        self.service_locator = service_locator or ServiceLocator()
        self.learning_system = learning_system or ContinuousLearningSystem(config)
        self.max_concurrent_tasks = config.get("automation.max_concurrent_tasks", default=10)
        self.semaphore = asyncio.Semaphore(self.max_concurrent_tasks)

        # Регистрация метрик
        self.monitoring.register_metric("tasks_completed", 0)
        self.monitoring.register_metric("tasks_failed", 0)
        self.monitoring.register_metric("subtasks_retried", 0)

        logger.info("✅ TaskOrchestrator initialized.")

    async def execute_job(self, job_context: JobContext) -> Dict[str, Any]:
        """
        Выполняет полный цикл обработки заказа.
        Возвращает результат с путями к deliverables и статусом.
        """
        audit_logger.log("JOB_START", {"job_id": job_context.job_id, "type": job_context.job_type})
        logger.info(f"▶️ Starting job {job_context.job_id} of type '{job_context.job_type}'")

        try:
            subtasks = await self._plan_subtasks(job_context)
            results = await self._execute_subtasks_parallel(subtasks)
            final_result = await self._assemble_final_deliverable(job_context, results)
            await self._log_success(job_context, final_result)
            return final_result

        except Exception as e:
            error_msg = f"Job {job_context.job_id} failed: {str(e)}"
            logger.error(error_msg, exc_info=True)
            audit_logger.log("JOB_FAILURE", {
                "job_id": job_context.job_id,
                "error": str(e),
                "traceback": traceback.format_exc()
            })
            self.monitoring.increment_metric("tasks_failed")
            # Передать в систему восстановления (внешний emergency_recovery)
            raise

    async def _plan_subtasks(self, job_context: JobContext) -> List[Subtask]:
        """Планирует подзадачи на основе типа заказа."""
        subtasks = []
        base_dir = Path("data/jobs") / job_context.job_id / "deliverables"
        base_dir.mkdir(parents=True, exist_ok=True)

        job_type = job_context.job_type.lower()

        if "transcription" in job_type:
            subtasks.append(Subtask(
                id=f"{job_context.job_id}_transcribe",
                type="transcription",
                input_data=job_context.source_file,
                output_path=base_dir / "transcript.txt"
            ))

        if "translation" in job_type:
            src_lang, tgt_lang = self._extract_langs(job_type)
            transcript_path = base_dir / "transcript.txt"
            if not transcript_path.exists():
                # Если нет транскрипции — добавить её как зависимость
                subtasks.insert(0, Subtask(
                    id=f"{job_context.job_id}_transcribe",
                    type="transcription",
                    input_data=job_context.source_file,
                    output_path=transcript_path
                ))
            subtasks.append(Subtask(
                id=f"{job_context.job_id}_translate",
                type="translation",
                input_data=transcript_path,
                output_path=base_dir / f"translation_{tgt_lang}.txt",
                metadata={"target_language": tgt_lang}
            ))

        if "copywriting" in job_type:
            subtasks.append(Subtask(
                id=f"{job_context.job_id}_copywrite",
                type="copywriting",
                input_data=job_context.requirements.get("brief", ""),
                output_path=base_dir / "copywriting_result.txt",
                metadata={
                    "tone": job_context.tone,
                    "word_count": job_context.word_count
                }
            ))

        if job_context.requirements.get("needs_editing", False):
            last_output = subtasks[-1].output_path if subtasks else None
            if last_output and last_output.exists():
                subtasks.append(Subtask(
                    id=f"{job_context.job_id}_edit",
                    type="editing",
                    input_data=last_output,
                    output_path=base_dir / "final_edited.txt"
                ))

        if job_context.requirements.get("needs_proofreading", True):
            input_for_proof = subtasks[-1].output_path if subtasks else None
            if input_for_proof:
                subtasks.append(Subtask(
                    id=f"{job_context.job_id}_proofread",
                    type="proofreading",
                    input_data=input_for_proof,
                    output_path=base_dir / "final_proofread.txt"
                ))

        logger.debug(f"Planned {len(subtasks)} subtasks for job {job_context.job_id}")
        return subtasks

    def _extract_langs(self, job_type: str) -> tuple[str, str]:
        # Пример: "translation_en_to_ru" → ("en", "ru")
        parts = job_type.replace("translation_", "").split("_to_")
        if len(parts) == 2:
            return parts[0], parts[1]
        return "auto", "en"  # fallback

    async def _execute_subtasks_parallel(self, subtasks: List[Subtask]) -> Dict[str, Path]:
        """Выполняет подзадачи с учётом зависимостей и ограничений по ресурсам."""
        results: Dict[str, Path] = {}
        tasks = []

        for subtask in subtasks:
            task = asyncio.create_task(self._execute_single_subtask_with_semaphore(subtask, results))
            tasks.append(task)

        await asyncio.gather(*tasks)
        return results

    async def _execute_single_subtask_with_semaphore(self, subtask: Subtask, results: Dict[str, Path]):
        async with self.semaphore:
            await self._execute_single_subtask(subtask, results)

    async def _execute_single_subtask(self, subtask: Subtask, results: Dict[str, Path]) -> None:
        """Выполняет одну подзадачу с повторными попытками."""
        while subtask.retries <= subtask.max_retries:
            try:
                subtask.status = "running"
                logger.info(f"▶️ Executing subtask {subtask.id} ({subtask.type})")

                service = await self._get_ai_service(subtask.type)
                if not service:
                    raise RuntimeError(f"No service found for type: {subtask.type}")

                # Выполнение
                if subtask.type == "transcription":
                    result_path = await service.transcribe(
                        audio_path=subtask.input_data,
                        output_path=subtask.output_path
                    )
                elif subtask.type == "translation":
                    with open(subtask.input_data, "r", encoding="utf-8") as f:
                        text = f.read()
                    translated = await service.translate(
                        text=text,
                        target_lang=subtask.metadata["target_language"]
                    )
                    with open(subtask.output_path, "w", encoding="utf-8") as f:
                        f.write(translated)
                    result_path = subtask.output_path
                elif subtask.type == "copywriting":
                    content = await service.generate(
                        prompt=subtask.input_data,
                        tone=subtask.metadata.get("tone"),
                        word_count=subtask.metadata.get("word_count")
                    )
                    with open(subtask.output_path, "w", encoding="utf-8") as f:
                        f.write(content)
                    result_path = subtask.output_path
                elif subtask.type == "editing":
                    with open(subtask.input_data, "r", encoding="utf-8") as f:
                        text = f.read()
                    edited = await service.edit(text)
                    with open(subtask.output_path, "w", encoding="utf-8") as f:
                        f.write(edited)
                    result_path = subtask.output_path
                elif subtask.type == "proofreading":
                    with open(subtask.input_data, "r", encoding="utf-8") as f:
                        text = f.read()
                    corrected = await service.proofread(text)
                    with open(subtask.output_path, "w", encoding="utf-8") as f:
                        f.write(corrected)
                    result_path = subtask.output_path
                else:
                    raise ValueError(f"Unsupported subtask type: {subtask.type}")

                # Успех
                subtask.status = "completed"
                results[subtask.id] = result_path
                self.monitoring.increment_metric("tasks_completed")
                logger.info(f"✅ Subtask {subtask.id} completed → {result_path}")
                return

            except Exception as e:
                subtask.retries += 1
                logger.warning(f"⚠️ Subtask {subtask.id} failed (attempt {subtask.retries}): {e}")
                self.monitoring.increment_metric("subtasks_retried")

                if subtask.retries > subtask.max_retries:
                    subtask.status = "failed"
                    logger.error(f"💥 Subtask {subtask.id} permanently failed after {subtask.max_retries} retries")
                    self.monitoring.increment_metric("tasks_failed")
                    raise

                # Задержка перед повтором (экспоненциальная)
                await asyncio.sleep(2 ** subtask.retries)

    async def _get_ai_service(self, service_type: str):
        """Получает AI-сервис через ServiceLocator или создаёт при первом вызове."""
        service_map = {
            "transcription": TranscriptionService,
            "translation": TranslationService,
            "copywriting": CopywritingService,
            "editing": EditingService,
            "proofreading": ProofreadingService,
        }
        if service_type not in service_map:
            return None

        service_class = service_map[service_type]
        service_key = f"ai_service_{service_type}"

        if not self.service_locator.has(service_key):
            service_instance = service_class(config=self.config)
            await service_instance.initialize()
            self.service_locator.register(service_key, service_instance)

        return self.service_locator.get(service_key)

    async def _assemble_final_deliverable(self, job_context: JobContext, results: Dict[str, Path]) -> Dict[str, Any]:
        """Собирает финальный результат для клиента."""
        deliverables = list(results.values())
        final_path = deliverables[-1] if deliverables else None

        if not final_path or not final_path.exists():
            raise RuntimeError("No valid deliverable produced")

        # Сохраняем метаданные результата
        result_meta = {
            "job_id": job_context.job_id,
            "deliverables": [str(p) for p in deliverables],
            "final_output": str(final_path),
            "status": "completed",
            "subtask_count": len(results)
        }

        # Сохраняем в data/jobs/{job_id}/job_details.json
        job_dir = Path("data/jobs") / job_context.job_id
        (job_dir / "job_details.json").write_text(
            json.dumps(result_meta, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )

        return result_meta

    async def _log_success(self, job_context: JobContext, result: Dict[str, Any]):
        """Логирует успешное завершение и отправляет данные в систему обучения."""
        audit_logger.log("JOB_SUCCESS", {"job_id": job_context.job_id})
        await self.learning_system.ingest_successful_job(job_context, result)

    async def shutdown(self):
        """Корректное завершение работы."""
        logger.info("🛑 Shutting down TaskOrchestrator...")
        # Здесь можно остановить фоновые задачи, если есть