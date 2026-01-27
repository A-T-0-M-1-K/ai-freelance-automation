from typing import Dict, Any
from pathlib import Path
import json
from datetime import datetime


def migrate_convert_old_job_format(batch_size: int = 1000, offset: int = 0) -> Dict[str, Any]:
    """
    Миграция: Конвертация старого формата заказов (v1) в новый (v2).

    Старый формат:
    {
        "id": "job_123",
        "title": "Написать статью",
        "client": "client_456",
        "price": 5000,
        "currency": "RUB",
        "status": "in_progress"
    }

    Новый формат:
    {
        "job_id": "job_123",
        "metadata": {
            "title": "Написать статью",
            "description": "",
            "skills_required": [],
            "complexity_level": "medium"
        },
        "client_id": "client_456",
        "financial": {
            "amount": 5000,
            "currency": "RUB",
            "payment_schedule": [{"milestone": "completion", "percent": 100}],
            "tax_status": "not_calculated"
        },
        "lifecycle": {
            "status": "in_progress",
            "created_at": "2024-01-15T10:30:00Z",
            "updated_at": "2024-01-15T10:30:00Z",
            "stage": "execution"
        }
    }
    """
    jobs_dir = Path("data/jobs")
    if not jobs_dir.exists():
        return {"status": "skipped", "reason": "Директория заказов не существует"}

    # Получение списка всех заказов
    job_files = list(jobs_dir.glob("*/job_details.json"))
    total = len(job_files)

    # Применение пагинации
    batch_files = job_files[offset:offset + batch_size]

    converted = 0
    skipped = 0

    for job_file in batch_files:
        try:
            with open(job_file) as f:
                old_data = json.load(f)

            # Проверка версии — пропуск уже конвертированных
            if old_data.get("version") == "2.0":
                skipped += 1
                continue

            # Конвертация данных
            new_data = {
                "job_id": old_data.get("id") or old_data.get("job_id", f"job_{datetime.utcnow().timestamp()}"),
                "metadata": {
                    "title": old_data.get("title", "Без названия"),
                    "description": old_data.get("description", ""),
                    "skills_required": old_data.get("skills", []),
                    "complexity_level": old_data.get("complexity", "medium"),
                    "tags": old_data.get("tags", [])
                },
                "client_id": old_data.get("client") or old_data.get("client_id", "unknown_client"),
                "financial": {
                    "amount": float(old_data.get("price", 0)),
                    "currency": old_data.get("currency", "RUB"),
                    "payment_schedule": [
                        {
                            "milestone": "completion",
                            "percent": 100,
                            "due_date": None,
                            "status": "pending"
                        }
                    ],
                    "tax_status": "not_calculated",
                    "invoice_generated": False
                },
                "lifecycle": {
                    "status": old_data.get("status", "draft"),
                    "created_at": old_data.get("created_at", datetime.utcnow().isoformat()),
                    "updated_at": datetime.utcnow().isoformat(),
                    "stage": _map_old_status_to_stage(old_data.get("status", "draft")),
                    "history": [
                        {
                            "timestamp": old_data.get("created_at", datetime.utcnow().isoformat()),
                            "event": "job_created",
                            "details": {"source": "migration_v1_to_v2"}
                        }
                    ]
                },
                "version": "2.0",
                "migrated_at": datetime.utcnow().isoformat(),
                "migration_source": "convert_old_job_format"
            }

            # Сохранение сконвертированных данных
            with open(job_file, 'w') as f:
                json.dump(new_data, f, indent=2, ensure_ascii=False)

            converted += 1

        except Exception as e:
            print(f"⚠️  Ошибка конвертации заказа {job_file}: {e}")
            # Продолжаем обработку остальных заказов

    return {
        "status": "partial_success",
        "converted": converted,
        "skipped": skipped,
        "total_in_batch": len(batch_files),
        "offset": offset
    }


def _map_old_status_to_stage(old_status: str) -> str:
    """Маппинг старых статусов на новые этапы жизненного цикла"""
    mapping = {
        "draft": "draft",
        "searching": "bidding",
        "in_progress": "execution",
        "revision": "revision",
        "completed": "delivery",
        "paid": "closed",
        "cancelled": "cancelled"
    }
    return mapping.get(old_status.lower(), "draft")


def get_total_records(migration_name: str) -> int:
    """Получение общего количества записей для миграции"""
    jobs_dir = Path("data/jobs")
    if not jobs_dir.exists():
        return 0
    return len(list(jobs_dir.glob("*/job_details.json")))