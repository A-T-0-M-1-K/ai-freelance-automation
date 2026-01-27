"""
Расширенный голосовой ассистент для переговоров с клиентами:
- Анализ тона и эмоций в реальном времени
- Генерация подсказок ответов на основе контекста
- Автоматическая адаптация стиля общения под клиента
"""

import json
import time
import threading
from pathlib import Path
from typing import Dict, Any, List, Optional, Callable
from datetime import datetime
import queue

import speech_recognition as sr
import pyttsx3
from transformers import pipeline

from core.communication.sentiment_analyzer import SentimentAnalyzer
from core.communication.tone_adjuster import ToneAdjuster
from core.ai_management.ai_model_hub import get_ai_model_hub
from services.ai_services.translation_service import TranslationService


class VoiceAssistantEnhanced:
    """
    Расширенный голосовой ассистент для поддержки переговоров с клиентами.
    Работает в фоновом режиме, анализируя речь клиента и предоставляя подсказки фрилансеру.
    """

    def __init__(self,
                 language: str = 'ru',
                 enable_realtime_analysis: bool = True,
                 enable_suggestions: bool = True,
                 enable_auto_response: bool = False):
        self.language = language
        self.enable_realtime_analysis = enable_realtime_analysis
        self.enable_suggestions = enable_suggestions
        self.enable_auto_response = enable_auto_response

        # Инициализация компонентов
        self.sentiment_analyzer = SentimentAnalyzer()
        self.tone_adjuster = ToneAdjuster()
        self.translation_service = TranslationService()
        self.ai_hub = get_ai_model_hub()

        # Распознавание речи
        self.recognizer = sr.Recognizer()
        self.microphone = sr.Microphone()

        # Синтез речи (для режима авто-ответа)
        self.tts_engine = pyttsx3.init()
        self.tts_engine.setProperty('rate', 150)  # Скорость речи

        # Очереди для обработки в реальном времени
        self.audio_queue = queue.Queue(maxsize=10)
        self.analysis_queue = queue.Queue(maxsize=5)
        self.suggestion_queue = queue.Queue(maxsize=3)

        # Состояние ассистента
        self.is_active = False
        self.current_conversation: Dict[str, Any] = {}
        self.conversation_history: List[Dict[str, Any]] = []

        # Потоки обработки
        self.processing_thread = None
        self.analysis_thread = None

        # Настройки конфиденциальности
        self.record_conversations = False
        self.anonymize_data = True

    def start_assistant(self, conversation_context: Optional[Dict[str, Any]] = None):
        """Запуск голосового ассистента для сессии переговоров"""
        if self.is_active:
            self.stop_assistant()

        self.is_active = True
        self.current_conversation = conversation_context or {
            'client_name': 'Unknown',
            'project_type': 'general',
            'budget_range': 'medium',
            'client_sentiment': 'neutral',
            'negotiation_stage': 'initial'
        }

        # Запуск потоков обработки
        self.processing_thread = threading.Thread(
            target=self._audio_processing_loop,
            name="VoiceAssistantAudioProcessing",
            daemon=True
        )
        self.analysis_thread = threading.Thread(
            target=self._analysis_loop,
            name="VoiceAssistantAnalysis",
            daemon=True
        )

        self.processing_thread.start()
        self.analysis_thread.start()

        print("🎤 Голосовой ассистент запущен. Говорите для анализа...")

        # Калибровка микрофона
        with self.microphone as source:
            print("🔊 Калибровка микрофона (5 секунд тишины)...")
            self.recognizer.adjust_for_ambient_noise(source, duration=5)
            print("✅ Калибровка завершена")

    def stop_assistant(self):
        """Остановка голосового ассистента"""
        self.is_active = False

        if self.processing_thread and self.processing_thread.is_alive():
            self.processing_thread.join(timeout=2.0)

        if self.analysis_thread and self.analysis_thread.is_alive():
            self.analysis_thread.join(timeout=2.0)

        # Сохранение истории разговора если требуется
        if self.record_conversations and self.conversation_history:
            self._save_conversation_history()

        print("⏹️  Голосовой ассистент остановлен")

    def _audio_processing_loop(self):
        """Основной цикл захвата и распознавания аудио"""
        while self.is_active:
            try:
                with self.microphone as source:
                    # Захват аудио с таймаутом
                    audio = self.recognizer.listen(source, timeout=5, phrase_time_limit=15)

                    # Помещение в очередь для асинхронной обработки
                    if not self.audio_queue.full():
                        self.audio_queue.put(audio)

                    # Небольшая пауза между захватами
                    time.sleep(0.5)

            except sr.WaitTimeoutError:
                # Тишина — продолжаем ожидание
                continue
            except Exception as e:
                print(f"⚠️  Ошибка захвата аудио: {e}")
                time.sleep(1.0)  # Пауза перед повторной попыткой

    def _analysis_loop(self):
        """Цикл анализа аудио и генерации подсказок"""
        while self.is_active:
            try:
                # Получение аудио из очереди
                if not self.audio_queue.empty():
                    audio = self.audio_queue.get(timeout=1.0)

                    # Распознавание речи
                    text = self._recognize_speech(audio)

                    if text:
                        # Анализ текста
                        analysis = self._analyze_client_speech(text)

                        # Сохранение в историю
                        self.conversation_history.append({
                            'timestamp': datetime.now().isoformat(),
                            'speaker': 'client',
                            'text': text,
                            'analysis': analysis
                        })

                        # Генерация подсказок
                        if self.enable_suggestions:
                            suggestions = self._generate_response_suggestions(text, analysis)

                            # Вывод подсказок пользователю
                            self._display_suggestions(suggestions, analysis)

                        # Автоматический ответ (если включен)
                        if self.enable_auto_response and analysis.get('sentiment_score', 0) > 0.7:
                            self._generate_and_speak_response(text, analysis)

                time.sleep(0.1)  # Короткая пауза для снижения нагрузки

            except queue.Empty:
                time.sleep(0.5)
            except Exception as e:
                print(f"⚠️  Ошибка анализа: {e}")
                time.sleep(1.0)

    def _recognize_speech(self, audio: sr.AudioData) -> Optional[str]:
        """Распознавание речи с использованием нескольких бэкендов"""
        try:
            # Попытка распознавания через Google Web Speech API (онлайн)
            text = self.recognizer.recognize_google(audio, language=f"{self.language}-{self.language.upper()}")
            return text.strip()
        except sr.UnknownValueError:
            # Не удалось распознать речь
            return None
        except sr.RequestError as e:
            # Ошибка API — попытка офлайн распознавания
            print(f"⚠️  Ошибка онлайн-распознавания: {e}. Используется офлайн-режим...")
            return self._offline_speech_recognition(audio)

    def _offline_speech_recognition(self, audio: sr.AudioData) -> Optional[str]:
        """Офлайн распознавание речи через Vosk или аналоги"""
        # Заглушка — в реальной системе интеграция с Vosk/Whisper
        return None

    def _analyze_client_speech(self, text: str) -> Dict[str, Any]:
        """Комплексный анализ речи клиента"""
        analysis = {}

        # Анализ тональности и эмоций
        sentiment = self.sentiment_analyzer.analyze(text, language=self.language)
        analysis['sentiment'] = sentiment.get('label', 'neutral')
        analysis['sentiment_score'] = sentiment.get('score', 0.5)
        analysis['emotions'] = sentiment.get('emotions', {})

        # Анализ намерений
        intent = self._detect_intent(text)
        analysis['intent'] = intent

        # Анализ ключевых тем
        topics = self._extract_topics(text)
        analysis['topics'] = topics

        # Анализ стиля общения клиента
        communication_style = self._analyze_communication_style(text)
        analysis['communication_style'] = communication_style

        # Определение уровня удовлетворенности
        satisfaction = self._estimate_satisfaction(text, sentiment)
        analysis['satisfaction_level'] = satisfaction

        # Рекомендации по стилю ответа
        recommended_tone = self.tone_adjuster.recommend_tone(
            client_sentiment=sentiment.get('label', 'neutral'),
            negotiation_stage=self.current_conversation.get('negotiation_stage', 'initial'),
            project_type=self.current_conversation.get('project_type', 'general')
        )
        analysis['recommended_tone'] = recommended_tone

        return analysis

    def _detect_intent(self, text: str) -> str:
        """Определение намерения клиента"""
        text_lower = text.lower()

        if any(kw in text_lower for kw in ['цена', 'стоимость', 'бюджет', 'дорого', 'дешево']):
            return 'price_negotiation'
        elif any(kw in text_lower for kw in ['срок', 'время', 'когда', 'задержка', 'срочно']):
            return 'timeline_discussion'
        elif any(kw in text_lower for kw in ['качество', 'переделать', 'исправить', 'ошибка']):
            return 'quality_concern'
        elif any(kw in text_lower for kw in ['отлично', 'хорошо', 'спасибо', 'доволен']):
            return 'positive_feedback'
        elif any(kw in text_lower for kw in ['привет', 'здравствуйте', 'начать']):
            return 'greeting'
        else:
            return 'general_discussion'

    def _extract_topics(self, text: str) -> List[str]:
        """Извлечение ключевых тем из текста"""
        # В реальной системе — использование NER или тематического моделирования
        topics = []

        keywords_map = {
            'payment': ['оплата', 'деньги', 'счёт', 'транзакция', 'платеж'],
            'delivery': ['сдача', 'дедлайн', 'финал', 'результат', 'готово'],
            'revision': ['правка', 'исправление', 'доработка', 'редактирование'],
            'scope': ['объём', 'требования', 'спецификация', 'техзадание']
        }

        text_lower = text.lower()
        for topic, keywords in keywords_map.items():
            if any(kw in text_lower for kw in keywords):
                topics.append(topic)

        return topics or ['general']

    def _analyze_communication_style(self, text: str) -> str:
        """Анализ стиля общения клиента"""
        # Эвристика на основе длины сообщений и формальности
        if len(text.split()) < 5:
            return 'concise'
        elif any(kw in text.lower() for kw in ['пожалуйста', 'спасибо', 'благодарю', 'уважаемый']):
            return 'polite_formal'
        elif text.endswith('!') or '😀' in text or '😊' in text:
            return 'friendly_enthusiastic'
        else:
            return 'neutral'

    def _estimate_satisfaction(self, text: str, sentiment: Dict[str, Any]) -> str:
        """Оценка уровня удовлетворенности клиента"""
        score = sentiment.get('score', 0.5)
        label = sentiment.get('label', 'neutral')

        if label == 'positive' and score > 0.8:
            return 'very_satisfied'
        elif label == 'positive':
            return 'satisfied'
        elif label == 'neutral':
            return 'neutral'
        elif label == 'negative' and score > 0.7:
            return 'dissatisfied'
        else:
            return 'very_dissatisfied'

    def _generate_response_suggestions(self, client_text: str, analysis: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Генерация подсказок для ответа фрилансеру"""
        suggestions = []

        # Контекст для генерации
        context = {
            'client_message': client_text,
            'client_sentiment': analysis.get('sentiment', 'neutral'),
            'client_intent': analysis.get('intent', 'general_discussion'),
            'recommended_tone': analysis.get('recommended_tone', 'professional'),
            'project_type': self.current_conversation.get('project_type', 'general'),
            'negotiation_stage': self.current_conversation.get('negotiation_stage', 'initial')
        }

        # Генерация через ИИ
        try:
            model = self.ai_hub.get_model(task_type='text_generation', language=self.language)

            prompt = self._build_suggestion_prompt(context)
            response = model(prompt, max_length=300, num_return_sequences=3, temperature=0.7)

            # Парсинг ответов
            for i, suggestion in enumerate(response[:3]):
                suggestions.append({
                    'id': i + 1,
                    'text': self._clean_generated_text(suggestion.get('generated_text', suggestion)),
                    'tone': analysis.get('recommended_tone', 'professional'),
                    'confidence': 0.9 - (i * 0.2)  # Уменьшение уверенности для альтернатив
                })

        except Exception as e:
            print(f"⚠️  Ошибка генерации подсказок: {e}")
            # Резервные шаблонные подсказки
            suggestions = self._get_template_suggestions(analysis)

        return suggestions

    def _build_suggestion_prompt(self, context: Dict[str, Any]) -> str:
        """Формирование промпта для генерации подсказок"""
        sentiment = context['client_sentiment']
        intent = context['client_intent']
        tone = context['recommended_tone']

        prompt = f"""Ты — профессиональный фрилансер, ведущий переговоры с клиентом.
Клиент говорит: "{context['client_message']}"

Анализ клиента:
- Настроение: {sentiment}
- Намерение: {intent}
- Этап переговоров: {context['negotiation_stage']}

Сгенерируй 3 варианта ответа в тоне "{tone}" на русском языке.
Ответы должны быть краткими (1-2 предложения), профессиональными и направленными на развитие диалога.

Вариант 1:"""

        return prompt

    def _clean_generated_text(self, text: str) -> str:
        """Очистка сгенерированного текста от артефактов"""
        # Удаление повторяющихся частей промпта
        lines = text.split('\n')
        cleaned = []

        for line in lines:
            line = line.strip()
            if line and not line.startswith('Ты —') and not line.startswith('Клиент говорит:') and not line.startswith(
                    'Анализ клиента:'):
                cleaned.append(line)

        return ' '.join(cleaned)[:250]  # Ограничение длины

    def _get_template_suggestions(self, analysis: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Резервные шаблонные подсказки при ошибке ИИ"""
        sentiment = analysis.get('sentiment', 'neutral')
        intent = analysis.get('intent', 'general_discussion')

        templates = {
            'positive': [
                "Рад, что вам нравится! Что ещё можно улучшить?",
                "Отлично! Готов продолжить работу в том же темпе.",
                "Спасибо за обратную связь! Давайте обсудим следующие шаги."
            ],
            'negative': [
                "Понимаю ваше беспокойство. Давайте разберёмся и исправим ситуацию.",
                "Извините за доставленные неудобства. Что именно нужно переделать?",
                "Важно для меня качество работы. Предложу решение проблемы."
            ],
            'neutral': [
                "Понял вас. Уточните, пожалуйста, детали?",
                "Спасибо за информацию. Какой следующий шаг?",
                "Хорошо, учту ваши пожелания. Что ещё важно для проекта?"
            ]
        }

        base_templates = templates.get(sentiment, templates['neutral'])

        return [
            {'id': i + 1, 'text': tpl, 'tone': analysis.get('recommended_tone', 'professional'), 'confidence': 0.7}
            for i, tpl in enumerate(base_templates[:3])
        ]

    def _display_suggestions(self, suggestions: List[Dict[str, Any]], analysis: Dict[str, Any]):
        """Отображение подсказок пользователю в консоли"""
        print("\n" + "=" * 80)
        print("💡 ПОДСКАЗКИ ДЛЯ ОТВЕТА:")
        print("=" * 80)

        # Отображение анализа клиента
        print(f"👤 Настроение клиента: {analysis.get('sentiment', 'нейтральное').upper()}")
        print(f"🎯 Намерение: {analysis.get('intent', 'общее обсуждение')}")
        print(f"💬 Рекомендуемый тон: {analysis.get('recommended_tone', 'профессиональный')}")
        print()

        # Отображение вариантов ответа
        for suggestion in suggestions:
            confidence = suggestion['confidence'] * 100
            print(f"[Вариант {suggestion['id']}] (уверенность: {confidence:.0f}%)")
            print(f"   {suggestion['text']}")
            print()

        print("=" * 80 + "\n")

    def _generate_and_speak_response(self, client_text: str, analysis: Dict[str, Any]):
        """Генерация и озвучивание автоматического ответа"""
        if not self.enable_auto_response:
            return

        # Генерация ответа
        suggestions = self._generate_response_suggestions(client_text, analysis)
        if suggestions:
            best_response = suggestions[0]['text']

            # Озвучивание
            print(f"🤖 Авто-ответ: {best_response}")
            self.tts_engine.say(best_response)
            self.tts_engine.runAndWait()

    def _save_conversation_history(self):
        """Сохранение истории разговора в файл"""
        if not self.conversation_history:
            return

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"conversation_{timestamp}.json"
        filepath = Path("data/conversations") / filename

        # Анонимизация если требуется
        history_to_save = self.conversation_history
        if self.anonymize_data:
            history_to_save = self._anonymize_history(history_to_save)

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump({
                'session_id': timestamp,
                'context': self.current_conversation,
                'history': history_to_save,
                'timestamp': datetime.now().isoformat()
            }, f, indent=2, ensure_ascii=False)

        print(f"💾 История разговора сохранена: {filepath}")

    def _anonymize_history(self, history: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Анонимизация персональных данных в истории"""
        anonymized = []

        for entry in history:
            text = entry.get('text', '')
            # Замена потенциальных персональных данных
            text = re.sub(r'\b[\w\.-]+@[\w\.-]+\.\w+\b', '[EMAIL]', text)  # Email
            text = re.sub(r'\+?\d[\d\s\-\(\)]{7,}\d', '[PHONE]', text)  # Телефон
            text = re.sub(r'\b[A-ZА-Я][a-zа-я]+\s+[A-ZА-Я][a-zа-я]+\b', '[NAME]', text)  # Имя Фамилия

            anonymized.append({**entry, 'text': text})

        return anonymized

    def set_negotiation_context(self, context: Dict[str, Any]):
        """Обновление контекста переговоров"""
        self.current_conversation.update(context)
        print(f"🔄 Контекст переговоров обновлён: {context}")

    def enable_auto_response_mode(self, enable: bool = True):
        """Включение/отключение режима автоматических ответов"""
        self.enable_auto_response = enable
        status = "включён" if enable else "отключён"
        print(f"🤖 Режим авто-ответов {status}")


# Пример использования
if __name__ == "__main__":
    # Создание ассистента
    assistant = VoiceAssistantEnhanced(
        language='ru',
        enable_realtime_analysis=True,
        enable_suggestions=True,
        enable_auto_response=False  # По умолчанию отключено для безопасности
    )

    # Запуск с контекстом переговоров
    assistant.set_negotiation_context({
        'client_name': 'Иван Петров',
        'project_type': 'copywriting',
        'budget_range': 'medium',
        'negotiation_stage': 'price_discussion'
    })

    try:
        assistant.start_assistant()

        # Работа ассистента в течение 5 минут
        print("\n🎤 Ассистент работает... Говорите для анализа (Ctrl+C для остановки)\n")
        time.sleep(300)

    except KeyboardInterrupt:
        print("\n⏹️  Остановка ассистента...")
    finally:
        assistant.stop_assistant()