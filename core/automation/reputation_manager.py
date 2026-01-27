# AI_FREELANCE_AUTOMATION/core/automation/reputation_manager.py

"""
Reputation Manager — отслеживает, анализирует и управляет репутацией автономного фрилансера
на всех подключённых платформах. Обеспечивает адаптацию стратегии работы на основе репутационных метрик.
"""

import logging
import json
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta

from core.config.unified_config_manager import UnifiedConfigManager
from core.monitoring.intelligent_monitoring_system import IntelligentMonitoringSystem
from core.learning.continuous_learning_system import ContinuousLearningSystem
from services.storage.database_service import DatabaseService
from platforms.platform_factory import PlatformFactory


class ReputationManager:
    """
    Управляет репутацией агента на фриланс-платформах.

    Основные задачи:
    - Сбор и агрегация репутационных данных
    - Анализ трендов и аномалий
    - Рекомендации для DecisionEngine
    - Обратная связь в ContinuousLearning
    """

    def __init__(
            self,
            config_manager: UnifiedConfigManager,
            monitoring_system: IntelligentMonitoringSystem,
            learning_system: Optional[ContinuousLearningSystem] = None,
            db_service: Optional[DatabaseService] = None
    ):
        self.config = config_manager.get_section("automation.reputation")
        self.monitoring = monitoring_system
        self.learning = learning_system
        self.db = db_service
        self.logger = logging.getLogger("ReputationManager")
        self.data_dir = Path(self.config.get("data_path", "data/clients"))
        self.history: Dict[str, List[Dict[str, Any]]] = {}
        self._load_history()

    def _load_history(self) -> None:
        """Загружает историю репутации из файловой системы или БД."""
        try:
            if self.db and self.db.is_connected():
                self.history = self.db.get_reputation_history()
            else:
                # Fallback на файловую систему
                index_path = self.data_dir / "clients_index.json"
                if index_path.exists():
                    with open(index_path, "r", encoding="utf-8") as f:
                        clients = json.load(f)
                    for client_id in clients.get("clients", []):
                        profile_path = self.data_dir / str(client_id) / "profile.json"
                        if profile_path.exists():
                            with open(profile_path, "r", encoding="utf-8") as f:
                                profile = json.load(f)
                            rep_log = profile.get("reputation_log", [])
                            self.history[str(client_id)] = rep_log
            self.logger.info(f"✅ Загружена история репутации для {len(self.history)} клиентов.")
        except Exception as e:
            self.logger.error(f"⚠️ Ошибка при загрузке истории репутации: {e}", exc_info=True)
            self.history = {}

    def update_reputation(
            self,
            platform: str,
            job_id: str,
            client_id: str,
            rating: float,
            feedback: str = "",
            completed_successfully: bool = True
    ) -> None:
        """
        Обновляет репутацию после завершения заказа.

        Args:
            platform (str): Название платформы (например, 'upwork')
            job_id (str): Идентификатор заказа
            client_id (str): Идентификатор клиента
            rating (float): Оценка от 1.0 до 5.0
            feedback (str): Текст отзыва
            completed_successfully (bool): Успешно ли завершён заказ
        """
        if not (1.0 <= rating <= 5.0):
            self.logger.warning(f"Некорректный рейтинг: {rating} для клиента {client_id}")
            rating = max(1.0, min(5.0, rating))

        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "platform": platform,
            "job_id": job_id,
            "rating": rating,
            "feedback": feedback.strip(),
            "success": completed_successfully,
            "metrics": self._extract_sentiment_and_quality(feedback)
        }

        client_key = str(client_id)
        if client_key not in self.history:
            self.history[client_key] = []
        self.history[client_key].append(entry)

        # Сохраняем в файл
        self._save_client_profile(client_key, entry)

        # Отправляем в мониторинг
        self.monitoring.log_metric("reputation.rating", rating, tags={"client": client_key, "platform": platform})
        self.monitoring.log_metric("reputation.success_rate", int(completed_successfully), tags={"client": client_key})

        # Обучение на основе обратной связи
        if self.learning:
            self.learning.process_feedback({
                "type": "reputation",
                "client_id": client_id,
                "job_id": job_id,
                "rating": rating,
                "feedback": feedback,
                "success": completed_successfully
            })

        self.logger.info(f"📈 Репутация обновлена для клиента {client_id} на платформе {platform}: {rating}/5.0")

    def _extract_sentiment_and_quality(self, feedback: str) -> Dict[str, Any]:
        """Извлекает метрики тональности и качества из отзыва (заглушка для интеграции с NLP)."""
        # В реальной системе здесь будет вызов sentiment_analyzer из communication/
        # Пока используем простую эвристику
        positive_words = {"great", "excellent", "perfect", "amazing", "professional", "fast", "quality"}
        negative_words = {"bad", "terrible", "slow", "poor", "disappointed", "wrong", "error"}

        words = set(feedback.lower().split())
        pos_score = len(words & positive_words)
        neg_score = len(words & negative_words)

        sentiment = "positive" if pos_score > neg_score else "negative" if neg_score > pos_score else "neutral"
        quality_score = min(1.0, pos_score / max(1, pos_score + neg_score))

        return {
            "sentiment": sentiment,
            "quality_score": round(quality_score, 2),
            "word_count": len(feedback.split())
        }

    def _save_client_profile(self, client_id: str, latest_entry: Dict[str, Any]) -> None:
        """Сохраняет профиль клиента с обновлённой репутацией."""
        client_dir = self.data_dir / client_id
        client_dir.mkdir(parents=True, exist_ok=True)
        profile_path = client_dir / "profile.json"

        # Загружаем существующий профиль или создаём новый
        if profile_path.exists():
            with open(profile_path, "r", encoding="utf-8") as f:
                profile = json.load(f)
        else:
            profile = {
                "client_id": client_id,
                "first_contact": datetime.utcnow().isoformat(),
                "total_jobs": 0,
                "average_rating": 0.0,
                "reputation_log": []
            }

        # Обновляем статистику
        log = profile.get("reputation_log", [])
        log.append(latest_entry)
        profile["reputation_log"] = log
        profile["total_jobs"] = len(log)
        profile["average_rating"] = round(sum(e["rating"] for e in log) / len(log), 2)

        # Сохраняем
        with open(profile_path, "w", encoding="utf-8") as f:
            json.dump(profile, f, indent=2, ensure_ascii=False)

    def get_client_risk_score(self, client_id: str) -> float:
        """
        Возвращает оценку риска (0.0–1.0) для клиента на основе его репутации.
        Чем выше — тем рискованнее работать.
        """
        client_key = str(client_id)
        if client_key not in self.history or not self.history[client_key]:
            return 0.3  # нейтральный риск для новых клиентов

        log = self.history[client_key]
        recent = [e for e in log if datetime.fromisoformat(e["timestamp"]) > datetime.utcnow() - timedelta(days=90)]
        if not recent:
            recent = log[-3:]  # последние 3 заказа

        avg_rating = sum(e["rating"] for e in recent) / len(recent)
        success_rate = sum(1 for e in recent if e["success"]) / len(recent)
        negative_feedbacks = sum(1 for e in recent if e["metrics"]["sentiment"] == "negative")

        # Простая формула риска
        risk = (5.0 - avg_rating) / 5.0 * 0.4 + (1 - success_rate) * 0.4 + (negative_feedbacks / len(recent)) * 0.2
        return min(1.0, max(0.0, risk))

    def get_platform_reputation_summary(self, platform: str) -> Dict[str, Any]:
        """Возвращает сводку по репутации на конкретной платформе."""
        all_entries = []
        for client_log in self.history.values():
            all_entries.extend([e for e in client_log if e["platform"] == platform])

        if not all_entries:
            return {"platform": platform, "jobs": 0, "avg_rating": 0.0, "success_rate": 0.0}

        total = len(all_entries)
        avg_rating = sum(e["rating"] for e in all_entries) / total
        success_rate = sum(1 for e in all_entries if e["success"]) / total

        return {
            "platform": platform,
            "jobs": total,
            "avg_rating": round(avg_rating, 2),
            "success_rate": round(success_rate, 2),
            "last_updated": datetime.utcnow().isoformat()
        }

    def should_avoid_client(self, client_id: str, threshold: float = 0.7) -> bool:
        """Определяет, стоит ли избегать клиента на основе порога риска."""
        risk = self.get_client_risk_score(client_id)
        return risk >= threshold

    def export_reputation_report(self, output_path: str) -> None:
        """Экспортирует полный отчёт по репутации (для аналитики или UI)."""
        report = {
            "generated_at": datetime.utcnow().isoformat(),
            "clients": {},
            "platforms": {}
        }

        # По клиентам
        for cid, log in self.history.items():
            if log:
                avg = sum(e["rating"] for e in log) / len(log)
                success = sum(1 for e in log if e["success"]) / len(log)
                report["clients"][cid] = {
                    "total_jobs": len(log),
                    "avg_rating": round(avg, 2),
                    "success_rate": round(success, 2),
                    "risk_score": self.get_client_risk_score(cid)
                }

        # По платформам
        platforms = set(e["platform"] for log in self.history.values() for e in log)
        for p in platforms:
            report["platforms"][p] = self.get_platform_reputation_summary(p)

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        self.logger.info(f"📊 Отчёт по репутации сохранён: {output_path}")


# === Инициализация модуля ===
def create_reputation_manager(
        config_manager: UnifiedConfigManager,
        monitoring_system: IntelligentMonitoringSystem,
        learning_system: Optional[ContinuousLearningSystem] = None,
        db_service: Optional[DatabaseService] = None
) -> ReputationManager:
    """Фабричная функция для DI-совместимой инициализации."""
    return ReputationManager(
        config_manager=config_manager,
        monitoring_system=monitoring_system,
        learning_system=learning_system,
        db_service=db_service
    )