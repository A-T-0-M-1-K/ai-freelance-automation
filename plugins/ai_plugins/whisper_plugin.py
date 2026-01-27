"""
Whisper Plugin с контекстными менеджерами для предотвращения утечек памяти CUDA
"""
import torch
import logging
from typing import Optional, Dict, Any
from contextlib import contextmanager
from transformers import WhisperProcessor, WhisperForConditionalRecognition
from core.services.base_service import BaseService, ExecutionContext, ServiceResult

logger = logging.getLogger(__name__)


class WhisperPlugin(BaseService):
    """
    Плагин для работы с Whisper моделями с безопасным управлением памятью
    """

    def __init__(self, model_name: str = "openai/whisper-medium"):
        super().__init__(service_name="whisper_plugin")
        self.model_name = model_name
        self.model: Optional[WhisperForConditionalRecognition] = None
        self.processor: Optional[WhisperProcessor] = None
        self.device = "cuda" if torch.cuda.is_available() else "cpu"

    async def _load_dependencies(self):
        """Безопасная загрузка модели с обработкой ошибок"""
        try:
            logger.info(f"Загрузка Whisper модели '{self.model_name}' на устройстве {self.device}...")

            # Использование контекстного менеджера для безопасной загрузки
            async with self._cuda_memory_guard("model_loading"):
                self.processor = WhisperProcessor.from_pretrained(self.model_name)
                self.model = WhisperForConditionalRecognition.from_pretrained(self.model_name)

                if self.device == "cuda":
                    self.model = self.model.to(self.device)
                    self.model = self.model.half()  # FP16 для экономии памяти

            # Очистка кэша CUDA после загрузки
            if self.device == "cuda":
                torch.cuda.empty_cache()

            self._initialized = True
            logger.info(f"Whisper модель '{self.model_name}' успешно загружена")

        except Exception as e:
            logger.error(f"Ошибка загрузки Whisper модели: {str(e)}")
            # Обязательная очистка памяти даже при ошибках
            await self._cleanup_cuda_memory()
            raise

    @contextmanager
    def _cuda_memory_guard(self, operation: str):
        """
        Контекстный менеджер для отслеживания использования памяти CUDA
        и автоматической очистки при исключениях
        """
        if self.device != "cuda":
            yield
            return

        try:
            # Сохранение состояния памяти до операции
            memory_before = torch.cuda.memory_allocated() / 1024 ** 2  # MB
            logger.debug(f"[CUDA] Память до {operation}: {memory_before:.2f}MB")

            yield

            # Проверка утечек после операции
            memory_after = torch.cuda.memory_allocated() / 1024 ** 2
            delta = memory_after - memory_before

            if delta > 100:  # Более 100MB утечка
                logger.warning(f"[CUDA] Возможная утечка памяти в {operation}: +{delta:.2f}MB")

            logger.debug(f"[CUDA] Память после {operation}: {memory_after:.2f}MB (дельта: {delta:+.2f}MB)")

        except Exception as e:
            logger.error(f"[CUDA] Ошибка в операции {operation}: {str(e)}")
            # Принудительная очистка памяти при исключениях
            torch.cuda.empty_cache()
            raise

    async def transcribe_audio(self, audio_path: str, language: str = "ru",
                               context: Optional[ExecutionContext] = None) -> ServiceResult:
        """
        Транскрибация аудио с безопасным управлением памятью
        """
        if not self._initialized:
            if not await self.initialize():
                return ServiceResult.failure(
                    error="Не удалось инициализировать Whisper модель",
                    error_type="InitializationError",
                    stack_trace="",
                    context=context or ExecutionContext(task_id="unknown"),
                    execution_time=0.0
                )

        start_time = time.time()

        try:
            # Безопасная обработка аудио с автоматической очисткой памяти
            async with self._transcription_context(audio_path, language):
                # Здесь будет логика транскрибации
                result = await self._perform_transcription(audio_path, language, context)
                return result

        except Exception as e:
            execution_time = time.time() - start_time
            return ServiceResult.failure(
                error=f"Ошибка транскрибации: {str(e)}",
                error_type=type(e).__name__,
                stack_trace="",
                context=context or ExecutionContext(task_id="unknown"),
                execution_time=execution_time,
                rollback_required=True
            )
        finally:
            # Гарантированная очистка памяти после каждой операции
            if self.device == "cuda":
                torch.cuda.empty_cache()

    @contextmanager
    def _transcription_context(self, audio_path: str, language: str):
        """
        Контекстный менеджер для безопасной транскрибации
        """
        # Отслеживание использования памяти
        if self.device == "cuda":
            torch.cuda.reset_peak_memory_stats()

        try:
            logger.debug(f"Начало транскрибации: {audio_path}, язык: {language}")
            yield
            logger.debug("Транскрибация завершена успешно")

        except Exception as e:
            logger.error(f"Ошибка транскрибации {audio_path}: {str(e)}")
            raise
        finally:
            # Вывод пикового использования памяти
            if self.device == "cuda":
                peak_memory = torch.cuda.max_memory_allocated() / 1024 ** 2
                logger.debug(f"[CUDA] Пиковое использование памяти: {peak_memory:.2f}MB")
                torch.cuda.empty_cache()

    async def _perform_transcription(self, audio_path: str, language: str,
                                     context: Optional[ExecutionContext]) -> ServiceResult:
        """
        Фактическая транскрибация аудио
        """
        import librosa

        # Загрузка аудио
        audio_array, sampling_rate = librosa.load(audio_path, sr=16000)

        # Предобработка
        inputs = self.processor(audio_array, sampling_rate=16000, return_tensors="pt")

        if self.device == "cuda":
            inputs = inputs.to(self.device)

        # Генерация транскрипции
        with torch.no_grad():  # Отключение градиентов для экономии памяти
            predicted_ids = self.model.generate(
                inputs.input_features,
                language=language,
                max_length=448  # Ограничение длины для предотвращения OOM
            )

        # Декодирование
        transcription = self.processor.batch_decode(predicted_ids, skip_special_tokens=True)[0]

        return ServiceResult.success(
            data={"text": transcription, "language": language, "audio_path": audio_path},
            context=context or ExecutionContext(task_id="unknown"),
            execution_time=0.0  # Будет установлено в основном методе
        )

    async def cleanup(self):
        """Полная очистка ресурсов модели"""
        if self.model is not None:
            del self.model
            self.model = None

        if self.processor is not None:
            del self.processor
            self.processor = None

        await self._cleanup_cuda_memory()
        self._initialized = False
        logger.info("Whisper плагин: ресурсы полностью освобождены")

    async def _cleanup_cuda_memory(self):
        """Очистка памяти CUDA"""
        if self.device == "cuda":
            try:
                torch.cuda.empty_cache()
                torch.cuda.reset_peak_memory_stats()
                logger.debug("[CUDA] Память очищена")
            except Exception as e:
                logger.warning(f"Ошибка очистки памяти CUDA: {str(e)}")

    async def health_check(self) -> Dict[str, Any]:
        """Проверка здоровья плагина"""
        base_health = await super().health_check()

        cuda_info = {}
        if self.device == "cuda":
            try:
                cuda_info = {
                    "cuda_available": torch.cuda.is_available(),
                    "device_name": torch.cuda.get_device_name(0),
                    "memory_allocated_mb": torch.cuda.memory_allocated() / 1024 ** 2,
                    "memory_reserved_mb": torch.cuda.memory_reserved() / 1024 ** 2,
                    "memory_free_mb": torch.cuda.mem_get_info()[0] / 1024 ** 2
                }
            except Exception as e:
                cuda_info = {"error": str(e)}

        return {
            **base_health,
            "model_loaded": self._initialized,
            "model_name": self.model_name,
            "device": self.device,
            "cuda_info": cuda_info
        }