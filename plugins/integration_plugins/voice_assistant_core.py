import asyncio
import json
import re
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
import torch
from transformers import pipeline, WhisperProcessor, WhisperForConditionalGeneration
from core.communication.context_manager import ContextManager
from core.communication.multilingual_support import MultilingualSupport
from services.ai_services.voice_cloning_service import VoiceCloningService
from core.ai_management.lazy_model_loader import LazyModelLoader


class VoiceAssistantCore:
    """
    Ядро голосового ассистента с поддержкой:
    - Многоязычного распознавания речи (Whisper)
    - Контекстного понимания намерений
    - Управления задачами фриланса голосом
    - Голосовых отчётов с клонированием голоса
    - Интеграции с умными колонками (Яндекс.Станция, Google Home)
    """

    def __init__(self, config: Dict):
        self.config = config
        self.context_manager = ContextManager()
        self.multilingual = MultilingualSupport()
        self.voice_cloner = VoiceCloningService()
        self.loader = LazyModelLoader.get_instance()

        # Загрузка моделей (ленивая)
        self.whisper_model = None
        self.whisper_processor = None
        self.intent_classifier = None

        self.active_sessions: Dict[str, Dict] = {}  # session_id -> {user_id, context, last_interaction}
        self.voice_profiles: Dict[str, Dict] = {}  # user_id -> {voice_embedding, preferences}

        self._initialize_models()

    def _initialize_models(self):
        """Ленивая инициализация моделей при первом использовании"""
        # Модели будут загружены при первом вызове соответствующих методов
        pass

    async def transcribe_audio(self, audio_bytes: bytes, language: str = "ru") -> str:
        """
        Транскрибация аудио в текст с помощью Whisper.
        """
        # Ленивая загрузка модели
        if self.whisper_model is None:
            print("🔊 Загрузка модели Whisper для транскрибации...")
            model_name = self.config.get("whisper_model", "openai/whisper-medium")

            self.whisper_processor = await self.loader.load_model_async(
                model_name,
                model_class=WhisperProcessor,
                subfolder="processor"
            )

            self.whisper_model = await self.loader.load_model_async(
                model_name,
                model_class=WhisperForConditionalGeneration,
                torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
                device_map="auto" if torch.cuda.is_available() else "cpu"
            )

            print("✅ Модель Whisper загружена")

        # Конвертация аудио в формат для Whisper
        import io
        from pydub import AudioSegment

        # Конвертация в 16kHz моно PCM
        audio = AudioSegment.from_file(io.BytesIO(audio_bytes))
        audio = audio.set_frame_rate(16000).set_channels(1)
        audio_np = audio.get_array_of_samples()

        # Транскрибация
        inputs = self.whisper_processor(audio_np, sampling_rate=16000, return_tensors="pt")

        if torch.cuda.is_available():
            inputs = {k: v.cuda() for k, v in inputs.items()}

        with torch.no_grad():
            predicted_ids = self.whisper_model.generate(**inputs)

        transcription = self.whisper_processor.batch_decode(predicted_ids, skip_special_tokens=True)[0]

        # Логирование для улучшения модели
        self._log_transcription(audio_bytes, transcription, language)

        return transcription.strip()

    async def understand_intent(self, text: str, user_id: str, session_id: str) -> Dict:
        """
        Понимание намерений пользователя из текста.

        Поддерживаемые намерения:
        - Управление задачами: "запусти задачу для клиента Ивана", "покажи статус заказа #123"
        - Финансы: "какой мой доход за неделю?", "создай счёт для клиента"
        - Аналитика: "какая статистика за месяц?", "прогнозируй тренды на следующую неделю"
        - Портфолио: "обнови моё портфолио", "создай демо для проекта"
        - Системные: "настрой уведомления", "проверь здоровье системы"
        """
        # Загрузка классификатора намерений (можно использовать кастомную модель или правила)
        if self.intent_classifier is None:
            # Используем простые правила + регулярные выражения для начала
            # В продакшене заменить на fine-tuned BERT модель
            self.intent_classifier = self._build_rule_based_classifier()

        # Контекст из предыдущих взаимодействий
        context = self.context_manager.get_context(user_id, session_id)

        # Классификация намерения
        intent = self._classify_intent_with_context(text, context)

        # Извлечение сущностей (клиенты, заказы, даты)
        entities = self._extract_entities(text, context)

        # Обогащение контекста
        self.context_manager.update_context(
            user_id=user_id,
            session_id=session_id,
            new_input=text,
            intent=intent,
            entities=entities
        )

        return {
            "intent": intent,
            "entities": entities,
            "confidence": 0.9,  # Для правила-based; для ML модели — реальный скор
            "context": context,
            "suggested_actions": self._get_suggested_actions(intent, entities)
        }

    def _classify_intent_with_context(self, text: str, context: Dict) -> str:
        """Классификация намерения с учётом контекста"""
        text_lower = text.lower()

        # Проверка контекстных намерений (продолжение диалога)
        if context.get("last_intent") == "ask_job_status" and any(
                word in text_lower for word in ["да", "конечно", "покажи"]):
            return "show_job_details"

        # Основные намерения
        intent_patterns = {
            "start_task": [
                r"запусти задачу", r"начни работу", r"выполни заказ",
                r"обработай задачу", r"запусти обработку"
            ],
            "check_job_status": [
                r"статус заказа", r"как дела с заказом", r"проверь задачу",
                r"где мой заказ", r"ход выполнения"
            ],
            "financial_report": [
                r"доход за", r"статистика за", r"финансы за", r"сколько заработал",
                r"отчёт по доходам", r"финансовый отчёт"
            ],
            "market_analysis": [
                r"тренды", r"прогноз", r"анализ рынка", r"что востребовано",
                r"какие навыки", r"рыночная аналитика"
            ],
            "portfolio_update": [
                r"обнови портфолио", r"создай портфолио", r"покажи мои работы",
                r"демо проекта", r"интерактивное демо"
            ],
            "system_health": [
                r"здоровье системы", r"проверь систему", r"мониторинг",
                r"статус сервисов", r"есть ли ошибки"
            ],
            "client_management": [
                r"клиент", r"заказчик", r"покажи клиента", r"история клиента"
            ],
            "voice_report": [
                r"голосовой отчёт", r"озвучи статистику", r"расскажи про",
                r"прочитай отчёт", r"аудио отчёт"
            ]
        }

        for intent, patterns in intent_patterns.items():
            if any(re.search(pattern, text_lower) for pattern in patterns):
                return intent

        # По умолчанию — поиск информации
        return "search_information"

    def _extract_entities(self, text: str, context: Dict) -> Dict[str, Any]:
        """Извлечение сущностей из текста"""
        entities = {}
        text_lower = text.lower()

        # Извлечение номера заказа (#123 или заказ 123)
        order_match = re.search(r"#(\d+)|заказ\s+(\d+)", text_lower)
        if order_match:
            entities["job_id"] = order_match.group(1) or order_match.group(2)

        # Извлечение имени клиента
        # Простой подход — поиск в списке известных клиентов
        known_clients = self._get_known_clients()
        for client in known_clients:
            if client.lower() in text_lower:
                entities["client_name"] = client
                break

        # Извлечение периода времени
        time_periods = {
            "неделя": "week",
            "месяц": "month",
            "день": "day",
            "год": "year",
            "сегодня": "today",
            "вчера": "yesterday"
        }

        for ru_period, en_period in time_periods.items():
            if ru_period in text_lower:
                entities["time_period"] = en_period
                break

        # Извлечение из контекста (если сущность не указана явно)
        if "job_id" not in entities and context.get("last_job_id"):
            entities["job_id"] = context["last_job_id"]

        if "client_name" not in entities and context.get("last_client"):
            entities["client_name"] = context["last_client"]

        return entities

    def _get_known_clients(self) -> List[str]:
        """Получение списка известных клиентов из данных"""
        try:
            clients_index = json.loads(Path("data/clients/clients_index.json").read_text())
            return [client["name"] for client in clients_index.get("clients", [])]
        except:
            return ["Иван", "Мария", "Алексей", "Екатерина"]  # Фолбэк

    def _get_suggested_actions(self, intent: str, entities: Dict) -> List[str]:
        """Получение списка предложенных действий на основе намерения"""
        suggestions = {
            "start_task": [
                "Найти подходящие заказы на платформах",
                "Проанализировать требования заказа",
                "Подготовить предложение для клиента"
            ],
            "check_job_status": [
                "Показать детали заказа",
                "Проверить сроки выполнения",
                "Отправить статус клиенту"
            ],
            "financial_report": [
                "Сгенерировать подробный отчёт",
                "Экспортировать в Excel",
                "Показать графики доходов"
            ],
            "market_analysis": [
                "Показать тренды по навыкам",
                "Сравнить с прошлым периодом",
                "Рекомендовать новые направления"
            ]
        }

        return suggestions.get(intent, ["Выполнить действие", "Показать детали", "Отменить"])

    async def execute_voice_command(self, intent: str, entities: Dict, user_id: str) -> Dict:
        """
        Выполнение голосовой команды на основе распознанного намерения.
        """
        result = {
            "status": "success",
            "message": "",
            "data": None,
            "audio_response": None  # Опциональный аудио-ответ
        }

        try:
            if intent == "start_task":
                job_id = entities.get("job_id") or self._find_most_relevant_job(user_id)
                if job_id:
                    # Запуск задачи через оркестратор
                    from core.automation.task_orchestrator import TaskOrchestrator
                    orchestrator = TaskOrchestrator.get_instance()
                    await orchestrator.start_job_execution(job_id, user_id)

                    result["message"] = f"Задача для заказа #{job_id} запущена"
                    result["data"] = {"job_id": job_id, "status": "in_progress"}

            elif intent == "check_job_status":
                job_id = entities.get("job_id")
                if job_id:
                    # Получение статуса заказа
                    job_details = self._get_job_details(job_id)
                    result["message"] = f"Статус заказа #{job_id}: {job_details.get('status', 'неизвестно')}"
                    result["data"] = job_details

            elif intent == "financial_report":
                period = entities.get("time_period", "week")
                report = await self._generate_financial_report(user_id, period)
                result["message"] = f"Финансовый отчёт за {period}: {report['summary']}"
                result["data"] = report

                # Генерация голосового отчёта при запросе
                if entities.get("voice_report", False) or "озвуч" in entities.get("original_text", ""):
                    result["audio_response"] = await self._generate_voice_report(report, user_id)

            elif intent == "voice_report":
                # Прямой запрос на голосовой отчёт
                period = entities.get("time_period", "week")
                report = await self._generate_financial_report(user_id, period)
                audio = await self._generate_voice_report(report, user_id)

                result["message"] = "Голосовой отчёт сгенерирован"
                result["audio_response"] = audio
                result["data"] = {"report_summary": report["summary"], "audio_duration_sec": len(audio) / 16000}

            # ... другие намерения

            else:
                result["status"] = "unknown_intent"
                result[
                    "message"] = f"Неизвестное намерение: {intent}. Доступные команды: запусти задачу, статус заказа, отчёт за неделю"

        except Exception as e:
            result["status"] = "error"
            result["message"] = f"Ошибка выполнения команды: {str(e)}"
            import traceback
            print(f"Ошибка голосовой команды: {traceback.format_exc()}")

        # Логирование выполнения
        self._log_command_execution(user_id, intent, entities, result)

        return result

    async def _generate_voice_report(self, report_data: Dict, user_id: str) -> bytes:
        """
        Генерация аудио-отчёта с клонированным голосом пользователя.
        """
        # Формирование текста отчёта
        report_text = self._format_report_text(report_data)

        # Синтез речи с клонированным голосом
        audio_bytes = await self.voice_cloner.synthesize_speech(
            text=report_text,
            speaker_id=user_id,
            language="ru",
            emotion="neutral",
            speed=1.0
        )

        return audio_bytes

    def _format_report_text(self, report: Dict) -> str:
        """Форматирование данных отчёта в естественный текст для озвучки"""
        summary = report.get("summary", {})
        period = report.get("period", "неделя")

        # Пример формирования текста
        text = f"Ваш финансовый отчёт за {period}. "
        text += f"Общий доход: {summary.get('total_income', 0):.0f} рублей. "
        text += f"Количество завершённых заказов: {summary.get('completed_jobs', 0)}. "
        text += f"Средний чек: {summary.get('average_check', 0):.0f} рублей. "
        text += "Хороший результат!"

        return text

    def _find_most_relevant_job(self, user_id: str) -> Optional[str]:
        """Поиск наиболее релевантного заказа для пользователя (на основе контекста)"""
        # Логика поиска: последний активный заказ, заказ с приближающимся дедлайном и т.д.
        try:
            jobs_index = json.loads(Path("data/jobs/jobs_index.json").read_text())
            active_jobs = [
                job for job in jobs_index.get("jobs", [])
                if job.get("status") in ["in_progress", "revision"]
            ]

            if active_jobs:
                # Сортировка по дате обновления (самый свежий — первый)
                active_jobs.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
                return active_jobs[0].get("job_id")
        except:
            pass

        return None

    def _get_job_details(self, job_id: str) -> Dict:
        """Получение деталей заказа"""
        try:
            job_file = Path(f"data/jobs/{job_id}/job_details.json")
            if job_file.exists():
                return json.loads(job_file.read_text())
        except:
            pass

        return {"job_id": job_id, "status": "not_found", "error": "Заказ не найден"}

    async def _generate_financial_report(self, user_id: str, period: str) -> Dict:
        """Генерация финансового отчёта за период"""
        # Импорт внутри функции для избежания циклических зависимостей
        from core.analytics.market_analyzer import MarketAnalyzer

        analyzer = MarketAnalyzer.get_instance()
        report = await analyzer.generate_financial_report(user_id, period)

        return report

    def _log_transcription(self, audio: bytes, text: str, language: str):
        """Логирование транскрибации для улучшения модели"""
        log_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "language": language,
            "text": text,
            "audio_hash": hash(audio)  # Упрощённо; в продакшене — SHA256
        }

        log_file = Path("data/logs/voice_transcriptions.jsonl")
        log_file.parent.mkdir(parents=True, exist_ok=True)

        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')

    def _log_command_execution(self, user_id: str, intent: str, entities: Dict, result: Dict):
        """Логирование выполнения голосовой команды"""
        log_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "user_id": user_id,
            "intent": intent,
            "entities": entities,
            "result_status": result["status"],
            "processing_time_ms": result.get("processing_time", 0)
        }

        log_file = Path("data/logs/voice_commands.jsonl")
        log_file.parent.mkdir(parents=True, exist_ok=True)

        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')

    def register_voice_profile(self, user_id: str, audio_sample: bytes, preferences: Dict = None):
        """
        Регистрация голосового профиля пользователя для персонализации.
        """
        # Извлечение голосовых признаков (в продакшене — через speaker embedding модель)
        voice_hash = hash(audio_sample)  # Упрощённо

        self.voice_profiles[user_id] = {
            "voice_hash": voice_hash,
            "registered_at": datetime.utcnow().isoformat(),
            "preferences": preferences or {},
            "sample_count": 1
        }

        # Сохранение на диск
        profiles_file = Path("data/voice_profiles.json")
        profiles = {}

        if profiles_file.exists():
            try:
                profiles = json.loads(profiles_file.read_text())
            except:
                pass

        profiles[user_id] = self.voice_profiles[user_id]

        with open(profiles_file, 'w', encoding='utf-8') as f:
            json.dump(profiles, f, indent=2, ensure_ascii=False)

        print(f"✅ Голосовой профиль зарегистрирован для пользователя {user_id}")

    async def handle_conversational_dialog(self, session_id: str, user_utterance: str, user_id: str) -> Dict:
        """
        Обработка многоходового диалога с сохранением контекста.
        """
        # Получение или создание сессии
        if session_id not in self.active_sessions:
            self.active_sessions[session_id] = {
                "user_id": user_id,
                "created_at": datetime.utcnow(),
                "last_interaction": datetime.utcnow(),
                "dialog_history": []
            }

        session = self.active_sessions[session_id]
        session["last_interaction"] = datetime.utcnow()

        # Добавление реплики в историю
        session["dialog_history"].append({
            "role": "user",
            "text": user_utterance,
            "timestamp": datetime.utcnow().isoformat()
        })

        # Распознавание намерения
        intent_result = await self.understand_intent(user_utterance, user_id, session_id)

        # Выполнение команды
        execution_result = await self.execute_voice_command(
            intent_result["intent"],
            intent_result["entities"],
            user_id
        )

        # Формирование ответа ассистента
        assistant_response = self._generate_assistant_response(intent_result, execution_result)

        # Добавление ответа в историю
        session["dialog_history"].append({
            "role": "assistant",
            "text": assistant_response,
            "timestamp": datetime.utcnow().isoformat()
        })

        # Очистка старых сессий (> 1 час неактивности)
        await self._cleanup_inactive_sessions()

        return {
            "response_text": assistant_response,
            "intent": intent_result["intent"],
            "entities": intent_result["entities"],
            "audio_response": execution_result.get("audio_response"),
            "suggested_actions": intent_result["suggested_actions"]
        }

    def _generate_assistant_response(self, intent_result: Dict, execution_result: Dict) -> str:
        """Генерация естественного ответа ассистента"""
        intent = intent_result["intent"]
        status = execution_result["status"]

        responses = {
            "start_task": {
                "success": "Задача успешно запущена. Я начну работу над заказом.",
                "error": "Не удалось запустить задачу. Проверьте параметры."
            },
            "check_job_status": {
                "success": f"Статус заказа: {execution_result.get('data', {}).get('status', 'неизвестно')}",
                "error": "Не удалось получить статус заказа."
            },
            "financial_report": {
                "success": "Вот ваш финансовый отчёт. Доходы растут!",
                "error": "Ошибка генерации отчёта."
            }
        }

        default_responses = {
            "success": "Команда выполнена успешно.",
            "error": "Произошла ошибка при выполнении команды.",
            "unknown_intent": "Я не поняла команду. Попробуйте сказать: 'Какой статус заказа?' или 'Покажи доходы за неделю'"
        }

        return responses.get(intent, default_responses).get(status, default_responses.get(status, "Готово"))

    async def _cleanup_inactive_sessions(self, max_inactivity_minutes: int = 60):
        """Очистка неактивных сессий диалога"""
        now = datetime.utcnow()
        to_remove = []

        for session_id, session in self.active_sessions.items():
            last_interaction = session["last_interaction"]
            if isinstance(last_interaction, str):
                last_interaction = datetime.fromisoformat(last_interaction)

            if (now - last_interaction).total_seconds() / 60 > max_inactivity_minutes:
                to_remove.append(session_id)

        for session_id in to_remove:
            del self.active_sessions[session_id]

        if to_remove:
            print(f"🧹 Очищено {len(to_remove)} неактивных голосовых сессий")


# Пример интеграции с WebSocket
async def websocket_voice_handler(websocket, session_id: str, user_id: str):
    """
    Обработчик WebSocket для голосового ассистента.
    """
    assistant = VoiceAssistantCore(config={})

    while True:
        try:
            message = await websocket.receive_json()
            message_type = message.get("type")

            if message_type == "audio_chunk":
                # Обработка аудио-чанка
                audio_bytes = message["audio"]  # base64 или бинарные данные
                transcription = await assistant.transcribe_audio(audio_bytes)

                await websocket.send_json({
                    "type": "transcription",
                    "text": transcription
                })

            elif message_type == "voice_command":
                # Обработка голосовой команды (уже распознанной)
                text = message["text"]
                result = await assistant.handle_conversational_dialog(
                    session_id=session_id,
                    user_utterance=text,
                    user_id=user_id
                )

                response = {
                    "type": "assistant_response",
                    "text": result["response_text"],
                    "intent": result["intent"],
                    "actions": result["suggested_actions"]
                }

                # Добавление аудио-ответа, если есть
                if result.get("audio_response"):
                    import base64
                    response["audio"] = base64.b64encode(result["audio_response"]).decode()
                    response["audio_format"] = "wav"

                await websocket.send_json(response)

            elif message_type == "register_voice":
                # Регистрация голосового профиля
                audio_sample = message["audio_sample"]
                assistant.register_voice_profile(user_id, audio_sample, message.get("preferences", {}))

                await websocket.send_json({
                    "type": "voice_registered",
                    "status": "success"
                })

        except Exception as e:
            await websocket.send_json({
                "type": "error",
                "message": str(e)
            })
            break