"""
Менеджер для управления всеми платформами через универсальный адаптер
"""
import json
import logging
from typing import Dict, Any, Optional, List, Type
from pathlib import Path

from platforms.universal_platform_adapter import UniversalPlatformAdapter, Job, Bid
from platforms.fiverr.fiverr_adapter import FiverrAdapter
from platforms.toptal.toptal_adapter import ToptalAdapter
from platforms.linkedin_profider.linkedin_profider_adapter import LinkedInProFinderAdapter
from platforms.habr_freelance.habr_freelance_adapter import HabrFreelanceAdapter
from platforms.profi_ru.profi_ru_adapter import ProfiRuAdapter

logger = logging.getLogger(__name__)


class PlatformManager:
    """
    Централизованный менеджер для управления всеми платформами
    """

    def __init__(self):
        self.platforms: Dict[str, UniversalPlatformAdapter] = {}
        self.platform_configs: Dict[str, Dict[str, Any]] = {}
        self._load_platform_configs()

        logger.info("Инициализирован менеджер платформ")

    def _load_platform_configs(self):
        """Загрузка конфигураций всех платформ"""
        config_dirs = [
            "platforms/fiverr",
            "platforms/toptal",
            "platforms/linkedin_profider",
            "platforms/habr_freelance",
            "platforms/profi_ru"
        ]

        for config_dir in config_dirs:
            config_path = Path(config_dir) / f"{Path(config_dir).name}_config.json"
            if config_path.exists():
                try:
                    with open(config_path, 'r', encoding='utf-8') as f:
                        config_data = json.load(f)
                        platform_name = config_data.get("name", Path(config_dir).name)
                        self.platform_configs[platform_name] = config_data
                        logger.info(f"Загружена конфигурация платформы: {platform_name}")
                except Exception as e:
                    logger.error(f"Ошибка загрузки конфигурации {config_path}: {str(e)}")

    async def initialize_all_platforms(self):
        """Инициализация всех доступных платформ"""
        platform_adapters = {
            "Fiverr": FiverrAdapter,
            "Toptal": ToptalAdapter,
            "LinkedIn ProFinder": LinkedInProFinderAdapter,
            "Хабр Фриланс": HabrFreelanceAdapter,
            "Профи.ру": ProfiRuAdapter
        }

        for platform_name, adapter_class in platform_adapters.items():
            try:
                adapter = adapter_class()
                await adapter.initialize()
                self.platforms[platform_name] = adapter
                logger.info(f"Платформа '{platform_name}' инициализирована успешно")
            except Exception as e:
                logger.error(f"Ошибка инициализации платформы '{platform_name}': {str(e)}")

    async def search_jobs_global(self,
                                 keywords: Optional[List[str]] = None,
                                 skills: Optional[List[str]] = None,
                                 budget_min: Optional[float] = None,
                                 budget_max: Optional[float] = None,
                                 platforms: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        Глобальный поиск заказов по всем платформам
        """
        if platforms is None:
            platforms = list(self.platforms.keys())

        all_jobs = []

        for platform_name in platforms:
            if platform_name not in self.platforms:
                logger.warning(f"Платформа '{platform_name}' не инициализирована")
                continue

            try:
                adapter = self.platforms[platform_name]
                jobs = await adapter.search_jobs(
                    keywords=keywords,
                    skills=skills,
                    budget_min=budget_min,
                    budget_max=budget_max
                )

                for job in jobs:
                    all_jobs.append({
                        "job": job,
                        "platform": platform_name,
                        "search_timestamp": datetime.now().isoformat()
                    })

                logger.info(f"Найдено {len(jobs)} заказов на платформе '{platform_name}'")

            except Exception as e:
                logger.error(f"Ошибка поиска на платформе '{platform_name}': {str(e)}")

        # Сортировка по бюджету (убывание)
        all_jobs.sort(key=lambda x: x["job"].budget or 0, reverse=True)

        return all_jobs

    async def place_bid_global(self, job: Job, bid: Bid) -> Dict[str, Any]:
        """
        Размещение предложения на заказ через соответствующую платформу
        """
        platform_name = job.platform

        if platform_name not in self.platforms:
            return {
                "success": False,
                "error": f"Платформа '{platform_name}' не найдена",
                "job_id": job.id
            }

        try:
            adapter = self.platforms[platform_name]
            result = await adapter.place_bid(bid)

            return {
                "success": True,
                "platform": platform_name,
                "job_id": job.id,
                "bid_id": result.get("bid_id"),
                "timestamp": datetime.now().isoformat()
            }

        except Exception as e:
            logger.error(f"Ошибка размещения предложения на платформе '{platform_name}': {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "platform": platform_name,
                "job_id": job.id
            }

    async def get_platform_statistics(self) -> Dict[str, Any]:
        """Получение статистики по всем платформам"""
        stats = {}

        for platform_name, adapter in self.platforms.items():
            try:
                # Подсчет заказов на платформе
                jobs = await adapter.search_jobs(page=1, per_page=1)

                stats[platform_name] = {
                    "status": "active",
                    "jobs_available": len(jobs),
                    "adapter_type": adapter.__class__.__name__,
                    "last_updated": datetime.now().isoformat()
                }
            except Exception as e:
                stats[platform_name] = {
                    "status": "error",
                    "error": str(e),
                    "last_updated": datetime.now().isoformat()
                }

        return stats

    async def close_all_platforms(self):
        """Закрытие соединений со всеми платформами"""
        for platform_name, adapter in self.platforms.items():
            try:
                await adapter.close()
                logger.info(f"Соединение с платформой '{platform_name}' закрыто")
            except Exception as e:
                logger.error(f"Ошибка закрытия платформы '{platform_name}': {str(e)}")

        self.platforms = {}