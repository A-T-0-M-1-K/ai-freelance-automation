#!/usr/bin/env python3
"""
Автоматическое определение оптимального профиля конфигурации
для текущего устройства пользователя
"""
import sys
import os
from pathlib import Path

# Добавление пути к проекту
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.ai_management.adaptive_model_loader import AdaptiveModelLoader


def main():
    print("=" * 70)
    print("🔍 АВТОМАТИЧЕСКОЕ ОПРЕДЕЛЕНИЕ ПРОФИЛЯ УСТРОЙСТВА")
    print("=" * 70)

    # Создание загрузчика для анализа устройства
    loader = AdaptiveModelLoader()

    # Получение рекомендаций
    recommendations = loader.get_performance_recommendations()
    profile = recommendations["device_profile"]

    print("\n📊 ХАРАКТЕРИСТИКИ УСТРОЙСТВА:")
    print(f"   Тип устройства: {profile['capability']}")
    print(f"   Общая оперативная память: {profile['ram_total_gb']} ГБ")
    print(f"   Доступная оперативная память: {profile['ram_available_gb']} ГБ")
    print(f"   Наличие GPU: {'Да' if profile['has_gpu'] else 'Нет'}")
    if profile['gpu_vram_gb']:
        print(f"   Объем видеопамяти GPU: {profile['gpu_vram_gb']} ГБ")

    print("\n⚡ РЕКОМЕНДУЕМЫЙ ПРОФИЛЬ КОНФИГУРАЦИИ:")
    print(f"   Основной профиль: {recommendations['recommended_variant']}")

    if recommendations['recommendations']:
        print("\n💡 РЕКОМЕНДАЦИИ ПО ОПТИМИЗАЦИИ:")
        for i, rec in enumerate(recommendations['recommendations'], 1):
            print(f"   {i}. {rec}")

    print("\n⏱️  ОЖИДАЕМАЯ ПРОИЗВОДИТЕЛЬНОСТЬ:")
    for task, time in recommendations['estimated_performance'].items():
        print(f"   • {task.replace('_', ' ').title()}: {time}")

    # Автоматическое применение профиля
    profile_map = {
        "high_end_gpu": "production",
        "mid_range_gpu": "staging",
        "integrated_gpu": "development",
        "cpu_only": "low_resource"
    }

    recommended_profile = profile_map.get(profile['capability'], "low_resource")

    print(f"\n🔧 АВТОМАТИЧЕСКИ ВЫБРАН ПРОФИЛЬ: {recommended_profile}")

    # Создание симлинка на рекомендуемый профиль
    config_dir = Path("config/profiles")
    current_profile_link = config_dir / "current.json"

    if current_profile_link.exists() or current_profile_link.is_symlink():
        current_profile_link.unlink()

    target_profile = config_dir / f"{recommended_profile}.json"
    if target_profile.exists():
        os.symlink(target_profile.name, current_profile_link)
        print(f"✅ Профиль {recommended_profile} установлен как текущий")
    else:
        print(f"⚠️  Профиль {recommended_profile} не найден, используется профиль по умолчанию")

    print("\n" + "=" * 70)
    print("✅ Готово! Система автоматически адаптирована под ваше устройство.")
    print("=" * 70)


if __name__ == "__main__":
    main()