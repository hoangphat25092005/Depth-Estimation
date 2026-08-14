from celery import Celery

celery_app = Celery(
    "Vision_Tasks", 
    broker="redis://localhost:6379/0", 
    backend="redis://localhost:6379/0"
)

# Cấu hình phụ trợ cho Celery
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Ho_Chi_Minh",
    enable_utc=True,
    # Worker chỉ lấy 1 việc làm xong mới lấy tiếp, chống quá tải RAM
    worker_prefetch_multiplier=1 
)