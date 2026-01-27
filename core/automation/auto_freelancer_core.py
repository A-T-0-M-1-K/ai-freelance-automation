# AI_FREELANCE_AUTOMATION/core/automation/auto_freelancer_core.py

"""
Autonomous Freelancer Core — центральный исполнительный модуль автоматизации.
Координирует полный жизненный цикл заказа: от поиска до оплаты.
Работает полностью автономно, имитируя поведение опытного фрилансера.
"""

import asyncio
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta

from core.dependency.service_locator import ServiceLocator
from core.config.unified_config_manager import UnifiedConfigManager
from core.monitoring.intelligent_monitoring_system import IntelligentMonitoringSystem
from core.security.audit_logger import AuditLogger
from core.automation.job_analyzer import JobAnalyzer
from core.automation.decision_engine import DecisionEngine
from core.automation.task_orchestrator import TaskOrchestrator
from core.automation.quality_controller import QualityController
from core.communication.empathetic_communicator import EmpatheticCommunicator
from core.payment.enhanced_payment_processor import EnhancedPaymentProcessor
from platforms.platform_factory import PlatformFactory

logger = logging.getLogger("AutoFreelancerCore")
audit_logger = AuditLogger("AUTO_FREELANCER")


class AutoFreelancerCore:
    """
    Основной автономный агент, заменяющий человека-фрилансера.
    Обеспечивает 100% автономность, самовосстановление и непрерывную работу.
    """

    def __init__(self, config: UnifiedConfigManager):
        self.config = config
        self.running = False
        self.active_jobs: Dict[str, Dict[str, Any]] = {}  # job_id -> metadata
        self.paused = False

        # Получаем сервисы через Service Locator для избежания циклических импортов
        self.service_locator = ServiceLocator.get_instance()
        self.monitoring: IntelligentMonitoringSystem = self.service_locator.get_service("monitoring")
        self.platform_factory: PlatformFactory = self.service_locator.get_service("platform_factory")
        self.communicator: EmpatheticCommunicator = self.service_locator.get_service("communicator")
        self.payment_processor: EnhancedPaymentProcessor = self.service_locator.get_service("payment_processor")

        # Инициализируем внутренние компоненты
        self.job_analyzer = JobAnalyzer(config)
        self.decision_engine = DecisionEngine(config)
        self.task_orchestrator = TaskOrchestrator(config)
        self.quality_controller = QualityController(config)

        audit_logger.log("INIT", "AutoFreelancerCore initialized successfully.")

    async def start(self) -> None:
        """Запуск автономной работы."""
        if self.running:
            logger.warning("Автофрилансер уже запущен.")
            return

        self.running = True
        self.paused = False
        logger.info("🟢 Автофрилансер запущен. Начинаю мониторинг заказов...")
        audit_logger.log("START", "Autonomous operation started.")

        # Запускаем основной цикл
        while self.running:
            try:
                if not self.paused:
                    await self._autonomous_cycle()
                await asyncio.sleep(self.config.get("automation.scan_interval_seconds", default=300))
            except asyncio.CancelledError:
                logger.info("🔄 Получен сигнал отмены. Завершаем работу...")
                break
            except Exception as e:
                logger.exception(f"❌ Критическая ошибка в основном цикле: {e}")
                audit_logger.log("ERROR", f"Main cycle error: {str(e)}")
                await self._trigger_recovery(e)

        logger.info("⏹️ Автофрилансер остановлен.")

    async def pause(self) -> None:
        """Приостановить работу (сохраняя контекст)."""
        self.paused = True
        logger.info("⏸️ Работа приостановлена.")
        audit_logger.log("PAUSE", "Operation paused by user or system.")

    async def resume(self) -> None:
        """Возобновить работу."""
        self.paused = False
        logger.info("▶️ Работа возобновлена.")
        audit_logger.log("RESUME", "Operation resumed.")

    async def stop(self) -> None:
        """Грациозно остановить систему."""
        self.running = False
        logger.info("🛑 Запрошена остановка автофрилансера.")
        audit_logger.log("STOP", "Graceful shutdown initiated.")

    async def _autonomous_cycle(self) -> None:
        """Основной цикл автономной работы."""
        logger.debug("🔁 Запуск цикла сканирования заказов...")

        # 1. Сканируем все подключенные платформы
        platforms = self.config.get("platforms.enabled", default=[])
        if not platforms:
            logger.warning("⚠️ Нет активных платформ. Проверьте конфигурацию.")
            return

        all_new_jobs: List[Dict[str, Any]] = []
        for platform_name in platforms:
            try:
                platform_client = self.platform_factory.get_platform(platform_name)
                jobs = await platform_client.fetch_new_jobs()
                logger.info(f"📥 Получено {len(jobs)} новых заказов с {platform_name}")
                all_new_jobs.extend(jobs)
            except Exception as e:
                logger.error(f"💥 Ошибка при получении заказов с {platform_name}: {e}")
                audit_logger.log("PLATFORM_ERROR", f"{platform_name}: {str(e)}")

        if not all_new_jobs:
            logger.debug("📭 Новых заказов не найдено.")
            return

        # 2. Анализируем и фильтруем заказы
        analyzed_jobs = await self.job_analyzer.analyze_jobs(all_new_jobs)
        filtered_jobs = [j for j in analyzed_jobs if j.get("is_relevant", False)]

        if not filtered_jobs:
            logger.info("🧹 Все заказы отфильтрованы как нерелевантные.")
            return

        # 3. Принимаем решения по каждому заказу
        for job in filtered_jobs:
            decision = await self.decision_engine.evaluate_job(job)
            if decision["should_bid"]:
                await self._submit_bid(job, decision)
            else:
                logger.info(f"⏭️ Отказ от участия в заказе {job['id']}: {decision.get('reason')}")

        # 4. Обрабатываем активные заказы (выполнение, коммуникация, сдача)
        await self._process_active_jobs()

        # 5. Обрабатываем завершённые заказы (оплата, пост-обслуживание)
        await self._finalize_completed_jobs()

    async def _submit_bid(self, job: Dict[str, Any], decision: Dict[str, Any]) -> None:
        """Отправить ставку на заказ."""
        try:
            platform = self.platform_factory.get_platform(job["platform"])
            bid_message = await self.communicator.generate_bid_message(job, decision)
            price = decision["recommended_price"]
            success = await platform.submit_bid(job["id"], message=bid_message, price=price)

            if success:
                logger.info(f"✅ Ставка отправлена на заказ {job['id']} ({job['platform']}) за {price}")
                audit_logger.log("BID_SUBMITTED", f"Job {job['id']}, price: {price}")
                # Добавляем в активные, если сразу выигран (некоторые платформы так работают)
                if decision.get("auto_accept", False):
                    self.active_jobs[job["id"]] = {
                        "job": job,
                        "status": "accepted",
                        "start_time": datetime.utcnow(),
                        "last_update": datetime.utcnow()
                    }
            else:
                logger.error(f"❌ Не удалось отправить ставку на заказ {job['id']}")
        except Exception as e:
            logger.exception(f"Ошибка при отправке ставки: {e}")
            audit_logger.log("BID_ERROR", str(e))

    async def _process_active_jobs(self) -> None:
        """Обработать все активные заказы (выполнение + коммуникация)."""
        for job_id, meta in list(self.active_jobs.items()):
            if meta["status"] != "accepted":
                continue

            job = meta["job"]
            try:
                # Выполняем задачу
                result = await self.task_orchestrator.execute_job(job)
                if result["success"]:
                    # Контроль качества
                    quality_result = await self.quality_controller.validate_result(result["output"], job)
                    if quality_result["approved"]:
                        # Отправляем клиенту
                        await self.communicator.deliver_result(job, quality_result["final_output"])
                        self.active_jobs[job_id]["status"] = "delivered"
                        self.active_jobs[job_id]["deliverables"] = quality_result["final_output"]
                        self.active_jobs[job_id]["last_update"] = datetime.utcnow()
                        logger.info(f"📤 Результат отправлен по заказу {job_id}")
                    else:
                        # Требуется доработка
                        logger.warning(f"🛠️ Требуется доработка для заказа {job_id}")
                        # Здесь можно запустить повторное выполнение или запросить уточнение
                else:
                    logger.error(f"💥 Ошибка выполнения заказа {job_id}: {result.get('error')}")
                    # Логика повторной попытки или уведомления
            except Exception as e:
                logger.exception(f"Ошибка при обработке активного заказа {job_id}: {e}")
                audit_logger.log("JOB_EXECUTION_ERROR", f"Job {job_id}: {str(e)}")

    async def _finalize_completed_jobs(self) -> None:
        """Обработать завершённые заказы: оплата, отзывы, аналитика."""
        for job_id, meta in list(self.active_jobs.items()):
            if meta["status"] != "delivered":
                continue

            job = meta["job"]
            try:
                # Проверяем статус оплаты
                payment_status = await self.payment_processor.check_payment_status(job_id)
                if payment_status == "paid":
                    logger.info(f"💰 Оплата получена за заказ {job_id}")
                    # Запрашиваем отзыв
                    await self.communicator.request_review(job)
                    # Обновляем статистику
                    await self._update_success_metrics(job, success=True)
                    # Удаляем из активных
                    self.active_jobs.pop(job_id, None)
                elif payment_status == "pending":
                    # Отправляем напоминание
                    if datetime.utcnow() - meta["last_update"] > timedelta(days=3):
                        await self.communicator.send_payment_reminder(job)
                        self.active_jobs[job_id]["last_update"] = datetime.utcnow()
                # Если не оплачено более 14 дней — закрываем с пометкой
                elif datetime.utcnow() - meta["last_update"] > timedelta(days=14):
                    logger.warning(f"⚠️ Заказ {job_id} не оплачен более 14 дней. Закрываем.")
                    await self._update_success_metrics(job, success=False)
                    self.active_jobs.pop(job_id, None)

            except Exception as e:
                logger.exception(f"Ошибка при финализации заказа {job_id}: {e}")

    async def _update_success_metrics(self, job: Dict[str, Any], success: bool) -> None:
        """Обновить метрики успеха для обучения и аналитики."""
        # В будущем: отправка в continuous_learning_system
        logger.info(f"📈 Метрика: заказ {job['id']} — {'успешен' if success else 'провален'}")

    async def _trigger_recovery(self, error: Exception) -> None:
        """Активировать процедуру восстановления после критической ошибки."""
        logger.info("🛠️ Запуск аварийного восстановления...")
        recovery = self.service_locator.get_service("emergency_recovery")
        if recovery:
            await recovery.handle_critical_failure(error)
        else:
            logger.critical("🆘 Система восстановления недоступна!")

    def get_status(self) -> Dict[str, Any]:
        """Возвращает текущий статус агента (для UI / API)."""
        return {
            "running": self.running,
            "paused": self.paused,
            "active_jobs_count": len(self.active_jobs),
            "active_jobs": list(self.active_jobs.keys()),
            "uptime": str(datetime.utcnow() - getattr(self, "_start_time", datetime.utcnow())),
        }