"""
Голосовой ассистент для управления системой через голосовые команды
Поддержка: русский/английский, интеграция с Алисой/Сири/Google Assistant
"""
import asyncio
import json
import logging
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass
from enum import Enum
import websockets
import aiohttp
from pydub import AudioSegment
import io

from core.services.base_service import BaseService, ExecutionContext, ServiceResult
from plugins.ai_plugins.whisper_plugin import WhisperPlugin
from services.ai_services.copywriting_service import CopywritingService
from core.communication.multilingual_support import MultilingualSupport

logger = logging.getLogger(__name__)


class VoicePlatform(Enum):
    YANDEX_ALICE = "yandex_alice"
    GOOGLE_ASSISTANT = "google_assistant"
    AMAZON_ALEXA = "amazon_alexa"
    SIRI = "siri"
    CUSTOM_WEBRTC = "custom_webrtc"


@dataclass
class VoiceCommand:
    """Структура распознанной голосовой команды"""
    text: str
    language: str
    confidence: float
    intent: str
    entities: Dict[str, Any]
    platform: VoicePlatform
    audio_duration_ms: int
    timestamp: str


class VoiceIntent(Enum):
    """Типы намерений голосовых команд"""
    START_TASK = "start_task"
    STOP_TASK = "stop_task"
    GET_STATUS = "get_status"
    GENERATE_CONTENT = "generate_content"
    TRANSLATE_TEXT = "translate_text"
    CHECK_FINANCES = "check_finances"
    SEND_MESSAGE = "send_message"
    UNKNOWN = "unknown"


class VoiceAssistantPlugin(BaseService):
    """
    Голосовой ассистент с поддержкой мультиплатформенной интеграции
    """

    def __init__(self, whisper_plugin: WhisperPlugin, copywriting_service: CopywritingService):
        super().__init__(service_name="voice_assistant")
        self.whisper_plugin = whisper_plugin
        self.copywriting_service = copywriting_service
        self.multilingual = MultilingualSupport()
        self.active_sessions: Dict[str, Dict[str, Any]] = {}
        self.websocket_server = None
        self._intent_classifier = self._init_intent_classifier()

    async def _load_dependencies(self):
        """Инициализация зависимостей"""
        # Инициализация плагинов
        if not self.whisper_plugin._initialized:
            await self.whisper_plugin.initialize()

        if not self.copywriting_service._initialized:
            await self.copywriting_service.initialize()

        self._initialized = True
        logger.info("Голосовой ассистент инициализирован")

    def _init_intent_classifier(self) -> Dict[str, List[str]]:
        """Инициализация простого классификатора намерений (в продакшене — модель ИИ)"""
        return {
            VoiceIntent.START_TASK.value: [
                "начать задачу", "запусти задачу", "начать работу", "запусти работу",
                "start task", "begin task", "start job", "begin job"
            ],
            VoiceIntent.STOP_TASK.value: [
                "останови задачу", "прекрати работу", "останови работу",
                "stop task", "cancel task", "stop job", "cancel job"
            ],
            VoiceIntent.GET_STATUS.value: [
                "статус задачи", "как дела", "как прогресс", "проверь статус",
                "task status", "how is progress", "check status", "what's happening"
            ],
            VoiceIntent.GENERATE_CONTENT.value: [
                "напиши текст", "создай контент", "напиши статью", "сгенерируй текст",
                "write text", "create content", "write article", "generate text"
            ],
            VoiceIntent.TRANSLATE_TEXT.value: [
                "переведи текст", "перевод", "переведи на русский", "переведи на английский",
                "translate text", "translation", "translate to russian", "translate to english"
            ],
            VoiceIntent.CHECK_FINANCES.value: [
                "мои финансы", "сколько денег", "проверь доходы", "финансовый отчет",
                "my finances", "how much money", "check earnings", "financial report"
            ],
            VoiceIntent.SEND_MESSAGE.value: [
                "отправь сообщение", "напиши клиенту", "свяжись с клиентом",
                "send message", "message client", "contact client"
            ]
        }

    async def start_websocket_server(self, host: str = "0.0.0.0", port: int = 8765):
        """
        Запуск WebSocket сервера для приема аудио в реальном времени (WebRTC)
        """

        async def handler(websocket, path):
            session_id = str(id(websocket))
            logger.info(f"Новое голосовое соединение: {session_id}")

            try:
                async for message in websocket:
                    if isinstance(message, bytes):
                        # Аудио данные
                        result = await self.process_audio_stream(session_id, message)
                        await websocket.send(json.dumps(result))
                    else:
                        # Управляющие команды
                        command = json.loads(message)
                        result = await self.handle_voice_command(session_id, command)
                        await websocket.send(json.dumps(result))

            except Exception as e:
                logger.error(f"Ошибка в голосовом соединении {session_id}: {str(e)}")
            finally:
                await self.end_session(session_id)
                logger.info(f"Голосовое соединение закрыто: {session_id}")

        self.websocket_server = await websockets.serve(handler, host, port)
        logger.info(f"WebSocket сервер голосового ассистента запущен на {host}:{port}")

    async def process_audio_stream(self, session_id: str, audio_chunk: bytes) -> Dict[str, Any]:
        """
        Обработка потокового аудио (WebRTC)
        """
        # Создание сессии при первом чанке
        if session_id not in self.active_sessions:
            self.active_sessions[session_id] = {
                "audio_buffer": io.BytesIO(),
                "language": "ru",
                "last_activity": asyncio.get_event_loop().time(),
                "chunks_received": 0
            }

        session = self.active_sessions[session_id]
        session["audio_buffer"].write(audio_chunk)
        session["chunks_received"] += 1
        session["last_activity"] = asyncio.get_event_loop().time()

        # Обработка после получения достаточного объема аудио (3 секунды)
        if session["chunks_received"] >= 60:  # ~3 сек при 20мс чанках
            audio_data = session["audio_buffer"].getvalue()
            session["audio_buffer"].seek(0)
            session["audio_buffer"].truncate(0)
            session["chunks_received"] = 0

            # Распознавание речи
            transcription = await self._transcribe_audio_chunk(audio_data, session["language"])

            if transcription["confidence"] > 0.7:
                # Классификация намерения
                intent = self._classify_intent(transcription["text"], transcription["language"])

                # Выполнение команды
                result = await self._execute_voice_intent(
                    intent=intent,
                    text=transcription["text"],
                    entities=transcription["entities"],
                    session_id=session_id
                )

                return {
                    "type": "command_executed",
                    "transcription": transcription,
                    "intent": intent.value,
                    "result": result
                }

        return {"type": "chunk_received", "chunks": session["chunks_received"]}

    async def _transcribe_audio_chunk(self, audio_data: bytes, language: str) -> Dict[str, Any]:
        """
        Распознавание речи из аудио чанка
        """
        # Конвертация в формат для Whisper (WAV 16kHz mono)
        audio_segment = AudioSegment.from_file(io.BytesIO(audio_data), format="webm")
        audio_segment = audio_segment.set_frame_rate(16000).set_channels(1)

        # Сохранение во временный файл
        temp_path = f"/tmp/voice_{hash(audio_data)}.wav"
        audio_segment.export(temp_path, format="wav")

        try:
            # Транскрибация через Whisper
            result = await self.whisper_plugin.transcribe_audio(temp_path, language=language)

            if result.success:
                text = result.data["text"]
                confidence = self._estimate_confidence(text)

                # Извлечение сущностей (упрощенно)
                entities = self._extract_entities(text, language)

                return {
                    "text": text,
                    "language": language,
                    "confidence": confidence,
                    "entities": entities,
                    "duration_ms": len(audio_segment)
                }
            else:
                return {
                    "text": "",
                    "language": language,
                    "confidence": 0.0,
                    "entities": {},
                    "duration_ms": len(audio_segment),
                    "error": result.error
                }

        finally:
            # Очистка временного файла
            import os
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def _estimate_confidence(self, text: str) -> float:
        """Оценка уверенности распознавания (упрощенно)"""
        if not text or len(text.strip()) < 3:
            return 0.1

        # Простая эвристика: длина текста и отсутствие странных символов
        score = min(len(text) / 100, 1.0)
        if any(c in text for c in "?¿"):
            score *= 0.5

        return max(0.3, score)  # Минимум 0.3 для непустого текста

    def _extract_entities(self, text: str, language: str) -> Dict[str, Any]:
        """Извлечение сущностей из текста (упрощенно)"""
        entities = {}

        # Извлечение сумм денег
        import re
        money_matches = re.findall(r'(\d+[\.,]?\d*)\s*(?:руб|долл|евро|₽|\$|€)', text.lower())
        if money_matches:
            entities["amount"] = float(money_matches[0].replace(',', '.'))

        # Извлечение сроков
        if "завтра" in text.lower() or "tomorrow" in text.lower():
            entities["deadline"] = "tomorrow"
        elif "недел" in text.lower() or "week" in text.lower():
            entities["deadline"] = "week"

        return entities

    def _classify_intent(self, text: str, language: str) -> VoiceIntent:
        """Классификация намерения по тексту"""
        text_lower = text.lower()

        for intent, keywords in self._intent_classifier.items():
            for keyword in keywords:
                if keyword in text_lower:
                    return VoiceIntent(intent)

        return VoiceIntent.UNKNOWN

    async def _execute_voice_intent(self, intent: VoiceIntent, text: str,
                                    entities: Dict[str, Any], session_id: str) -> Any:
        """
        Выполнение голосовой команды в зависимости от намерения
        """
        context = ExecutionContext(
            task_id=f"voice_{session_id}_{int(asyncio.get_event_loop().time())}",
            metadata={"voice_command": text, "entities": entities}
        )

        if intent == VoiceIntent.GENERATE_CONTENT:
            # Генерация контента по голосовой команде
            prompt = self._extract_prompt_from_command(text, entities)
            result = await self.copywriting_service.generate_content(
                prompt=prompt,
                tone="professional",
                length=500,
                context=context
            )
            return result.data if result.success else {"error": result.error}

        elif intent == VoiceIntent.TRANSLATE_TEXT:
            # Перевод текста
            source_text = self._extract_text_to_translate(text)
            target_lang = entities.get("language", "en" if "английск" in text.lower() else "ru")

            result = await self.copywriting_service.translate_text(
                text=source_text,
                target_language=target_lang,
                context=context
            )
            return result.data if result.success else {"error": result.error}

        elif intent == VoiceIntent.CHECK_FINANCES:
            # Запрос финансовой информации (заглушка — в продакшене запрос к БД)
            return {
                "balance": 15000,
                "currency": "RUB",
                "pending_payments": 5000,
                "last_transaction": "2024-01-15"
            }

        else:
            # Неизвестная команда — генерация ответа через ИИ
            response_prompt = f"Пользователь сказал: '{text}'. Какой уместный ответ дать?"
            result = await self.copywriting_service.generate_content(
                prompt=response_prompt,
                tone="helpful",
                length=100,
                context=context
            )
            return {"response": result.data if result.success else "Не понимаю команду"}

    def _extract_prompt_from_command(self, text: str, entities: Dict[str, Any]) -> str:
        """Извлечение промпта для генерации из голосовой команды"""
        # Упрощенная логика — в продакшене использовать NLP модель
        common_phrases = [
            "напиши текст", "создай контент", "напиши статью", "сгенерируй текст",
            "write text", "create content", "write article", "generate text"
        ]

        for phrase in common_phrases:
            if phrase in text.lower():
                return text.lower().replace(phrase, "").strip().capitalize()

        return text

    def _extract_text_to_translate(self, text: str) -> str:
        """Извлечение текста для перевода"""
        # В реальной системе — распознавание через предыдущий контекст или явное указание
        return "Пример текста для перевода"  # Заглушка

    async def handle_platform_webhook(self, platform: VoicePlatform, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Обработка вебхуков от внешних голосовых платформ (Алиса, Google Assistant)
        """
        if platform == VoicePlatform.YANDEX_ALICE:
            return await self._handle_alice_webhook(payload)
        elif platform == VoicePlatform.GOOGLE_ASSISTANT:
            return await self._handle_google_webhook(payload)
        else:
            return {"error": f"Платформа {platform.value} не поддерживается"}

    async def _handle_alice_webhook(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Обработка вебхука от Яндекс Алисы"""
        # Структура запроса Алисы
        # https://yandex.ru/dev/dialogs/alice/doc/protocol-docpage/

        session_id = payload["session"]["session_id"]
        command_text = payload["request"]["command"]
        original_utterance = payload["request"]["original_utterance"]

        # Классификация намерения
        intent = self._classify_intent(command_text, language="ru")

        # Выполнение команды
        result = await self._execute_voice_intent(
            intent=intent,
            text=command_text,
            entities={},
            session_id=session_id
        )

        # Формирование ответа для Алисы
        response_text = self._format_alice_response(result, intent)

        return {
            "response": {
                "text": response_text,
                "end_session": False  # Продолжить диалог
            },
            "session": payload["session"],
            "version": payload["version"]
        }

    def _format_alice_response(self, result: Any, intent: VoiceIntent) -> str:
        """Форматирование ответа для Алисы"""
        if isinstance(result, dict) and "error" in result:
            return f"Произошла ошибка: {result['error']}"

        if intent == VoiceIntent.GENERATE_CONTENT:
            if isinstance(result, dict) and "content" in result:
                # Обрезка для голосового вывода (макс 1000 символов)
                content = result["content"]
                return content[:1000] + ("..." if len(content) > 1000 else "")
            return str(result)[:1000]

        elif intent == VoiceIntent.CHECK_FINANCES:
            if isinstance(result, dict):
                return f"Ваш баланс: {result.get('balance', 0)} {result.get('currency', 'RUB')}. Ожидаемые платежи: {result.get('pending_payments', 0)} {result.get('currency', 'RUB')}."

        return str(result)[:500]  # Ограничение длины ответа

    async def end_session(self, session_id: str):
        """Завершение голосовой сессии"""
        if session_id in self.active_sessions:
            session = self.active_sessions.pop(session_id)
            # Очистка буфера аудио
            if "audio_buffer" in session:
                session["audio_buffer"].close()
            logger.info(f"Голосовая сессия {session_id} завершена")

    async def cleanup_inactive_sessions(self, timeout_seconds: int = 300):
        """Очистка неактивных сессий"""
        current_time = asyncio.get_event_loop().time()
        to_remove = []

        for session_id, session in self.active_sessions.items():
            if current_time - session["last_activity"] > timeout_seconds:
                to_remove.append(session_id)

        for session_id in to_remove:
            await self.end_session(session_id)
            logger.info(f"Неактивная сессия {session_id} очищена")

    async def health_check(self) -> Dict[str, Any]:
        """Проверка здоровья голосового ассистента"""
        base_health = await super().health_check()

        return {
            **base_health,
            "active_sessions": len(self.active_sessions),
            "websocket_running": self.websocket_server is not None,
            "supported_platforms": [p.value for p in VoicePlatform],
            "intents_supported": [i.value for i in VoiceIntent]
        }