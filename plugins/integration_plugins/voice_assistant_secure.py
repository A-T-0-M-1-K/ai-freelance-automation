import jwt
import datetime
import hashlib
import secrets
from typing import Dict, Optional
from fastapi import WebSocket, WebSocketDisconnect, HTTPException
from core.security.advanced_crypto_system import AdvancedCryptoSystem


class SecureVoiceAssistant:
    """
    Безопасная реализация голосового ассистента с аутентификацией по JWT и биометрии.
    """

    def __init__(self, secret_key: str):
        self.secret_key = secret_key
        self.crypto_system = AdvancedCryptoSystem()
        self.active_sessions: Dict[str, Dict] = {}  # session_id -> metadata
        self.voice_prints: Dict[str, str] = {}  # user_id -> voice_hash

    async def authenticate_websocket(self, websocket: WebSocket, token: str) -> Dict:
        """
        Аутентификация WebSocket-соединения через JWT токен.
        """
        try:
            # Декодирование и валидация JWT
            payload = jwt.decode(
                token,
                self.secret_key,
                algorithms=["HS256"],
                options={"require": ["exp", "user_id", "session_id"]}
            )

            # Проверка срока действия
            if datetime.datetime.utcnow().timestamp() > payload["exp"]:
                raise HTTPException(status_code=401, detail="Токен истёк")

            # Проверка активности сессии
            session_id = payload["session_id"]
            if session_id not in self.active_sessions:
                # Регистрация новой сессии
                self.active_sessions[session_id] = {
                    "user_id": payload["user_id"],
                    "created_at": datetime.datetime.utcnow(),
                    "last_activity": datetime.datetime.utcnow(),
                    "websocket": websocket,
                    "voice_authenticated": False
                }

            return payload

        except jwt.InvalidTokenError as e:
            raise HTTPException(status_code=401, detail=f"Невалидный токен: {str(e)}")

    async def voice_biometric_auth(self, websocket: WebSocket, audio_sample: bytes, user_id: str) -> bool:
        """
        Аутентификация по голосовому отпечатку (биометрия).
        """
        # Генерация хеша голосового образца
        voice_hash = hashlib.sha256(audio_sample).hexdigest()

        # Сравнение с сохранённым голосовым отпечатком
        stored_hash = self.voice_prints.get(user_id)

        if not stored_hash:
            # Первичная регистрация голоса пользователя
            self.voice_prints[user_id] = voice_hash
            print(f"✅ Голосовой отпечаток зарегистрирован для пользователя {user_id}")
            return True

        # Сравнение хешей с допуском на шум (5% различий)
        similarity = self._calculate_similarity(voice_hash, stored_hash)

        if similarity > 0.95:  # 95% совпадения
            # Обновление статуса сессии
            for session in self.active_sessions.values():
                if session.get("user_id") == user_id:
                    session["voice_authenticated"] = True
                    session["last_activity"] = datetime.datetime.utcnow()

            print(f"✅ Голосовая аутентификация успешна для пользователя {user_id}")
            return True

        print(f"❌ Голосовая аутентификация не пройдена для пользователя {user_id}")
        return False

    def _calculate_similarity(self, hash1: str, hash2: str) -> float:
        """
        Расчёт схожести двух хешей (простая реализация).
        Для продакшена использовать ML-модель сравнения голосов.
        """
        # Подсчёт совпадающих символов
        matches = sum(1 for a, b in zip(hash1, hash2) if a == b)
        return matches / max(len(hash1), len(hash2))

    async def handle_voice_command(self, websocket: WebSocket, command: str, session_id: str) -> Dict:
        """
        Обработка голосовой команды с проверкой аутентификации.
        """
        # Проверка существования сессии
        session = self.active_sessions.get(session_id)
        if not session:
            raise HTTPException(status_code=401, detail="Сессия не найдена")

        # Проверка голосовой аутентификации для критических команд
        critical_commands = ["платёж", "перевод", "удалить", "закрыть счёт"]
        if any(cmd in command.lower() for cmd in critical_commands):
            if not session.get("voice_authenticated", False):
                await websocket.send_json({
                    "status": "error",
                    "message": "Требуется голосовая аутентификация для этой команды",
                    "action": "request_voice_auth"
                })
                return {"status": "awaiting_auth"}

        # Шифрование команды перед обработкой
        encrypted_command = self.crypto_system.encrypt(command.encode())

        # Логирование безопасного события
        from core.security.audit_logger import AuditLogger
        audit = AuditLogger()
        audit.log_security_event(
            event_type="voice_command_executed",
            user_id=session["user_id"],
            details={"command_hash": hashlib.sha256(command.encode()).hexdigest()},
            risk_level="medium" if any(cmd in command.lower() for cmd in critical_commands) else "low"
        )

        # Дальнейшая обработка команды...
        return {"status": "success", "command": command}

    def generate_voice_jwt(self, user_id: str, expires_minutes: int = 15) -> str:
        """
        Генерация JWT токена для голосового интерфейса с коротким сроком жизни.
        """
        payload = {
            "user_id": user_id,
            "session_id": secrets.token_hex(16),
            "type": "voice_assistant",
            "exp": datetime.datetime.utcnow() + datetime.timedelta(minutes=expires_minutes),
            "iat": datetime.datetime.utcnow(),
            "jti": secrets.token_urlsafe(32)  # Уникальный идентификатор токена
        }

        token = jwt.encode(payload, self.secret_key, algorithm="HS256")
        return token

    async def cleanup_inactive_sessions(self, max_inactivity_minutes: int = 30):
        """
        Очистка неактивных сессий для предотвращения утечек памяти.
        """
        now = datetime.datetime.utcnow()
        to_remove = []

        for session_id, session in self.active_sessions.items():
            inactive_for = (now - session["last_activity"]).total_seconds() / 60
            if inactive_for > max_inactivity_minutes:
                to_remove.append(session_id)
                # Закрытие WebSocket соединения
                try:
                    await session["websocket"].close()
                except:
                    pass

        for session_id in to_remove:
            del self.active_sessions[session_id]

        print(f"🧹 Очищено {len(to_remove)} неактивных голосовых сессий")


# Пример интеграции в основной обработчик WebSocket
async def websocket_endpoint(websocket: WebSocket, token: str):
    assistant = SecureVoiceAssistant(secret_key=os.environ["SECRET_KEY"])

    # Аутентификация при подключении
    try:
        payload = await assistant.authenticate_websocket(websocket, token)
        await websocket.accept()

        print(f"✅ Пользователь {payload['user_id']} подключён к голосовому ассистенту")

        # Основной цикл обработки сообщений
        while True:
            try:
                data = await websocket.receive_json()
                message_type = data.get("type")

                if message_type == "voice_command":
                    result = await assistant.handle_voice_command(
                        websocket,
                        data["command"],
                        payload["session_id"]
                    )
                    await websocket.send_json(result)

                elif message_type == "voice_sample":
                    # Аутентификация по голосу
                    auth_result = await assistant.voice_biometric_auth(
                        websocket,
                        data["audio"],
                        payload["user_id"]
                    )
                    await websocket.send_json({
                        "status": "success" if auth_result else "failed",
                        "message": "Голос подтверждён" if auth_result else "Голос не распознан"
                    })

                # Обновление времени последней активности
                if payload["session_id"] in assistant.active_sessions:
                    assistant.active_sessions[payload["session_id"]]["last_activity"] = datetime.datetime.utcnow()

            except WebSocketDisconnect:
                print(f"🔌 Пользователь {payload['user_id']} отключился")
                break

            except Exception as e:
                await websocket.send_json({
                    "status": "error",
                    "message": f"Ошибка обработки: {str(e)}"
                })

    except HTTPException as e:
        await websocket.close(code=4001, reason=e.detail)