import os
from celery import Celery
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent.parent / ".env")

celery_app = Celery(
    "Vision_Tasks",
    broker=os.getenv("REDIS_WORKER_URL", "redis://localhost:6380/0"),
    backend=os.getenv("REDIS_BACKEND_URL", "redis://localhost:6380/0")
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Ho_Chi_Minh",
    enable_utc=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    broker_connection_retry=True,
    broker_connection_max_retries=10,
    task_routes={
        "tasks.celery_tasks.process_image_task": {"queue": "depth"},
        "tasks.celery_tasks.process_video_task": {"queue": "depth"},
    },
)