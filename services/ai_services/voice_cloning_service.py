"""
Сервис клонирования голоса для создания персонализированного голосового бренда
Использует: Whisper (распознавание) + Tortoise-TTS (синтез)
"""
import os
import torch
import logging
from typing import Optional, Dict, Any, List
from pathlib import Path
import soundfile as sf
from datetime import datetime

from core.services.base_service import BaseService, ExecutionContext, ServiceResult
from plugins.ai_plugins.whisper_plugin import WhisperPlugin

logger = logging.getLogger(__name__)


class VoiceCloningService(BaseService):
    """
    Сервис для клонирования голоса фрилансера
    Создает персонализированный голосовой бренд для:
    - Аудио-доставок работ
    - Голосовой коммуникации с клиентами
    - Создания аудио-контента
    """

    def __init__(self):
        super().__init__(service_name="voice_cloning")
        self.whisper_plugin = WhisperPlugin()
        self.tortoise_model = None
        self.voice_samples: Dict[str, List[str]] = {}  # voice_id -> [sample_paths]
        self.voices_dir = Path("data/voices")
        self.voices_dir.mkdir(parents=True, exist_ok=True)

        logger.info("Инициализирован сервис клонирования голоса")

    async def _load_dependencies(self):
        """Загрузка моделей Tortoise-TTS"""
        try:
            # Импорт Tortoise-TTS
            from tortoise.api import TextToSpeech
            from tortoise.utils.audio import load_audio

            self.load_audio_util = load_audio

            # Загрузка модели Tortoise-TTS
            logger.info("Загрузка модели Tortoise-TTS...")
            self.tortoise_model = TextToSpeech(
                use_hifigan=True,
                kv_cache=True,
                ar_checkpoint='tortoise-tts/tortoise-v2-ar-ckpt',
                diff_checkpoint='tortoise-tts/tortoise-v2-diffusion-ckpt'
            )

            # Инициализация Whisper для распознавания образцов голоса
            if not self.whisper_plugin._initialized:
                await self.whisper_plugin.initialize()

            self._initialized = True
            logger.info("Модели Tortoise-TTS успешно загружены")

        except ImportError as e:
            logger.error(f"Ошибка импорта Tortoise-TTS: {str(e)}")
            logger.info("Установите зависимости: pip install tortoise-tts soundfile")
            raise
        except Exception as e:
            logger.error(f"Ошибка загрузки моделей: {str(e)}")
            raise

    async def create_voice_profile(self,
                                   voice_id: str,
                                   sample_audio_paths: List[str],
                                   voice_name: str = "My Voice",
                                   context: Optional[ExecutionContext] = None) -> ServiceResult:
        """
        Создание профиля голоса на основе образцов
        """
        if not self._initialized:
            if not await self.initialize():
                return ServiceResult.failure(
                    error="Не удалось инициализировать сервис клонирования голоса",
                    error_type="InitializationError",
                    stack_trace="",
                    context=context or ExecutionContext(task_id="unknown"),
                    execution_time=0.0
                )

        start_time = datetime.now().timestamp()

        try:
            # Валидация аудио-образцов
            if len(sample_audio_paths) < 3:
                return ServiceResult.failure(
                    error="Требуется минимум 3 аудио-образца для создания профиля голоса",
                    error_type="ValidationError",
                    stack_trace="",
                    context=context or ExecutionContext(task_id="unknown"),
                    execution_time=0.0
                )

            # Создание директории для голоса
            voice_dir = self.voices_dir / voice_id
            voice_dir.mkdir(parents=True, exist_ok=True)

            # Копирование и анализ образцов
            processed_samples = []

            for i, audio_path in enumerate(sample_audio_paths):
                if not os.path.exists(audio_path):
                    logger.warning(f"Аудио-образец не найден: {audio_path}")
                    continue

                # Распознавание речи для анализа качества
                transcription_result = await self.whisper_plugin.transcribe_audio(audio_path)

                if transcription_result.success:
                    # Сохранение обработанного образца
                    sample_dest = voice_dir / f"sample_{i + 1}.wav"

                    # Конвертация в нужный формат (16kHz, mono)
                    self._convert_audio_format(audio_path, str(sample_dest))

                    processed_samples.append({
                        "path": str(sample_dest),
                        "transcription": transcription_result.data.get("text", ""),
                        "duration": transcription_result.data.get("duration", 0),
                        "confidence": transcription_result.data.get("confidence", 0)
                    })

            if len(processed_samples) < 2:
                return ServiceResult.failure(
                    error="Недостаточно качественных аудио-образцов",
                    error_type="ValidationError",
                    stack_trace="",
                    context=context or ExecutionContext(task_id="unknown"),
                    execution_time=0.0
                )

            # Сохранение метаданных голоса
            voice_metadata = {
                "voice_id": voice_id,
                "voice_name": voice_name,
                "created_at": datetime.now().isoformat(),
                "samples_count": len(processed_samples),
                "samples": processed_samples,
                "total_duration": sum(s["duration"] for s in processed_samples),
                "languages": list(set(t["transcription"][:10] for t in processed_samples))
            }

            metadata_path = voice_dir / "metadata.json"
            with open(metadata_path, 'w', encoding='utf-8') as f:
                json.dump(voice_metadata, f, ensure_ascii=False, indent=2)

            # Сохранение ссылки на образцы
            self.voice_samples[voice_id] = [s["path"] for s in processed_samples]

            execution_time = datetime.now().timestamp() - start_time

            return ServiceResult.success(
                data={
                    "voice_id": voice_id,
                    "voice_name": voice_name,
                    "samples_processed": len(processed_samples),
                    "total_duration": voice_metadata["total_duration"],
                    "voice_profile_path": str(voice_dir),
                    "metadata_path": str(metadata_path)
                },
                context=context or ExecutionContext(task_id="unknown"),
                execution_time=execution_time
            )

        except Exception as e:
            execution_time = datetime.now().timestamp() - start_time
            return ServiceResult.failure(
                error=f"Ошибка создания профиля голоса: {str(e)}",
                error_type=type(e).__name__,
                stack_trace="",
                context=context or ExecutionContext(task_id="unknown"),
                execution_time=execution_time,
                rollback_required=True
            )

    def _convert_audio_format(self, input_path: str, output_path: str):
        """Конвертация аудио в формат 16kHz mono WAV"""
        try:
            import librosa

            # Загрузка аудио
            audio, sr = librosa.load(input_path, sr=16000, mono=True)

            # Сохранение в WAV
            sf.write(output_path, audio, 16000)

        except Exception as e:
            logger.error(f"Ошибка конвертации аудио {input_path}: {str(e)}")
            raise

    async def synthesize_speech(self,
                                voice_id: str,
                                text: str,
                                output_path: str,
                                preset: str = "fast",
                                context: Optional[ExecutionContext] = None) -> ServiceResult:
        """
        Синтез речи с использованием клонированного голоса
        """
        if not self._initialized:
            if not await self.initialize():
                return ServiceResult.failure(
                    error="Не удалось инициализировать сервис клонирования голоса",
                    error_type="InitializationError",
                    stack_trace="",
                    context=context or ExecutionContext(task_id="unknown"),
                    execution_time=0.0
                )

        start_time = datetime.now().timestamp()

        try:
            # Проверка существования профиля голоса
            if voice_id not in self.voice_samples:
                voice_dir = self.voices_dir / voice_id
                metadata_path = voice_dir / "metadata.json"

                if not metadata_path.exists():
                    return ServiceResult.failure(
                        error=f"Профиль голоса '{voice_id}' не найден",
                        error_type="VoiceNotFoundError",
                        stack_trace="",
                        context=context or ExecutionContext(task_id="unknown"),
                        execution_time=0.0
                    )

                # Загрузка метаданных
                with open(metadata_path, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)

                self.voice_samples[voice_id] = [s["path"] for s in metadata["samples"]]

            # Загрузка образцов голоса
            voice_samples = [self.load_audio_util(p) for p in self.voice_samples[voice_id]]

            # Генерация речи
            logger.info(f"Генерация речи с голосом '{voice_id}'...")

            # Выбор пресета
            presets = {
                "ultra_fast": {"num_autoregressive_samples": 16, "diffusion_iterations": 2},
                "fast": {"num_autoregressive_samples": 32, "diffusion_iterations": 4},
                "standard": {"num_autoregressive_samples": 64, "diffusion_iterations": 8},
                "high_quality": {"num_autoregressive_samples": 128, "diffusion_iterations": 16}
            }

            gen_kwargs = presets.get(preset, presets["standard"])

            # Генерация
            generated = self.tortoise_model.tts_with_preset(
                text,
                voice_samples=voice_samples,
                preset=preset
            )

            # Сохранение аудио
            output_dir = Path(output_path).parent
            output_dir.mkdir(parents=True, exist_ok=True)

            if isinstance(generated, list):
                # Несколько вариантов - выбираем первый
                audio = generated[0]
            else:
                audio = generated

            # Сохранение в файл
            sf.write(output_path, audio.squeeze().cpu().numpy(), 24000)

            execution_time = datetime.now().timestamp() - start_time

            return ServiceResult.success(
                data={
                    "audio_path": output_path,
                    "text": text,
                    "voice_id": voice_id,
                    "duration": len(audio.squeeze()) / 24000,
                    "preset": preset,
                    "execution_time": execution_time
                },
                context=context or ExecutionContext(task_id="unknown"),
                execution_time=execution_time
            )

        except Exception as e:
            execution_time = datetime.now().timestamp() - start_time
            return ServiceResult.failure(
                error=f"Ошибка синтеза речи: {str(e)}",
                error_type=type(e).__name__,
                stack_trace="",
                context=context or ExecutionContext(task_id="unknown"),
                execution_time=execution_time
            )

    async def generate_audio_delivery(self,
                                      voice_id: str,
                                      project_name: str,
                                      deliverables_summary: str,
                                      client_name: str,
                                      output_dir: str,
                                      context: Optional[ExecutionContext] = None) -> ServiceResult:
        """
        Генерация аудио-доставки работы для клиента
        """
        # Формирование текста аудио-сообщения
        message_template = f"""
        Здравствуйте, {client_name}!

        Рад сообщить, что работа над проектом "{project_name}" завершена.

        Основные результаты:
        {deliverables_summary}

        Все материалы доступны в личном кабинете. Пожалуйста, ознакомьтесь и дайте обратную связь.

        Спасибо за сотрудничество!
        """

        # Генерация аудио
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = Path(output_dir) / f"delivery_{project_name}_{timestamp}.wav"

        result = await self.synthesize_speech(
            voice_id=voice_id,
            text=message_template,
            output_path=str(output_path),
            preset="high_quality",
            context=context
        )

        if result.success:
            result.data["delivery_type"] = "audio_message"
            result.data["client_name"] = client_name
            result.data["project_name"] = project_name

        return result

    async def list_available_voices(self) -> Dict[str, Any]:
        """Получение списка доступных голосовых профилей"""
        voices = {}

        for voice_dir in self.voices_dir.iterdir():
            if voice_dir.is_dir():
                metadata_path = voice_dir / "metadata.json"
                if metadata_path.exists():
                    with open(metadata_path, 'r', encoding='utf-8') as f:
                        metadata = json.load(f)
                        voices[metadata["voice_id"]] = metadata

        return {
            "voices_count": len(voices),
            "voices": voices,
            "default_voice": next(iter(voices.keys())) if voices else None
        }

    async def delete_voice_profile(self, voice_id: str) -> bool:
        """Удаление профиля голоса"""
        try:
            voice_dir = self.voices_dir / voice_id

            if voice_dir.exists():
                import shutil
                shutil.rmtree(voice_dir)

            if voice_id in self.voice_samples:
                del self.voice_samples[voice_id]

            logger.info(f"Профиль голоса '{voice_id}' удален")
            return True

        except Exception as e:
            logger.error(f"Ошибка удаления профиля голоса '{voice_id}': {str(e)}")
            return False

    async def health_check(self) -> Dict[str, Any]:
        """Проверка здоровья сервиса"""
        base_health = await super().health_check()

        voices_info = await self.list_available_voices()

        return {
            **base_health,
            "tortoise_model_loaded": self.tortoise_model is not None,
            "whisper_initialized": self.whisper_plugin._initialized,
            "available_voices": voices_info["voices_count"],
            "voice_profiles": list(voices_info["voices"].keys())
        }