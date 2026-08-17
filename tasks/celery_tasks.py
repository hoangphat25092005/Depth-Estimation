import os
import io
import uuid
import logging
import tempfile

import boto3
from botocore.config import Config as BotoConfig
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy.orm import Session

from configs.setting import (
    DATABASE_URL,
    STORAGE_DOMAIN,
    STORAGE_ACCESS_KEY,
    STORAGE_SECRET_KEY,
)
from configs.minio_store import S3_bucket_name_original, S3_bucket_name_depth
from services.depth_service import depth_service
from configs.celery_app import celery_app

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# MinIO client (boto3) — created per-task to avoid cross-process issues
# ---------------------------------------------------------------------------
def _build_s3_client():
    return boto3.client(
        "s3",
        endpoint_url=STORAGE_DOMAIN,
        aws_access_key_id=STORAGE_ACCESS_KEY,
        aws_secret_access_key=STORAGE_SECRET_KEY,
        config=BotoConfig(signature_version="s3v4"),
        region_name="us-east-1",
    )


# ---------------------------------------------------------------------------
# Database session factory (new engine scoped to this process)
# ---------------------------------------------------------------------------
def _build_session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=5, max_overflow=5)
    return sessionmaker(bind=engine)()


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def _upload_bytes_to_minio(s3_client, file_bytes: bytes, bucket: str, key: str, content_type: str):
    s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=io.BytesIO(file_bytes),
        ContentType=content_type,
    )


def _update_file_status(db: Session, file_id: int, status: str, depth_file_id: int | None = None):
    from models.file import FileModel
    record = db.query(FileModel).filter(FileModel.id == file_id).first()
    if record:
        record.status = status
        if depth_file_id is not None:
            record.depth_file_id = depth_file_id
        db.commit()


# ---------------------------------------------------------------------------
# Image Task
# ---------------------------------------------------------------------------
@celery_app.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=5,
    retry_backoff_max=300,
    max_retries=3,
    reject_on_worker_lost=True,
    acks_late=True,
    name="tasks.celery_tasks.process_image_task",
)
def process_image_task(self, original_file_id: int, stored_filename: str, original_filename: str):
    from services.websocket_service import notify_ws_sync

    s3_client = _build_s3_client()
    db = _build_session()
    uploaded_files: list[tuple[str, str]] = []

    try:
        # 1. Download original from MinIO
        notify_ws_sync(
            str(original_file_id),
            "processing",
            "Đã nhận ảnh, bắt đầu Depth Estimation..."
        )

        response = s3_client.get_object(Bucket=S3_bucket_name_original, Key=stored_filename)
        original_bytes = response["Body"].read()

        # 2. Depth estimation
        depth_bytes = depth_service.process_image_bytes(original_bytes)
        depth_filename = f"depth_{original_filename}"

        notify_ws_sync(
            str(original_file_id),
            "processing",
            "Model xử lý xong. Đang lưu ảnh lên hệ thống..."
        )

        # 3. Upload result to depth bucket
        depth_key = f"{uuid.uuid4()}.jpg"
        _upload_bytes_to_minio(
            s3_client,
            depth_bytes,
            S3_bucket_name_depth,
            depth_key,
            "image/jpeg",
        )
        uploaded_files.append((S3_bucket_name_depth, depth_key))

        # 4. Save depth file record
        from models.file import FileModel
        depth_record = FileModel(
            original_filename=depth_filename,
            stored_filename=depth_key,
            content_type="image/jpeg",
            file_size=len(depth_bytes),
            bucket_name=S3_bucket_name_depth,
            status="completed",
        )
        db.add(depth_record)
        db.flush()

        # 5. Update original file status
        _update_file_status(db, original_file_id, "completed", depth_record.id)
        db.commit()

        notify_ws_sync(
            str(original_file_id),
            "completed",
            "Xử lý ảnh thành công!",
            extra_data={"depth_file_id": depth_record.id},
        )

        logger.info("process_image_task completed for original_file_id=%s", original_file_id)

    except SoftTimeLimitExceeded:
        logger.error("process_image_task timed out for original_file_id=%s", original_file_id)
        _on_failure(original_file_id, "Task bị timeout do quá thời gian giới hạn", db, s3_client, uploaded_files)
        raise

    except Exception as exc:
        logger.exception("process_image_task failed for original_file_id=%s: %s", original_file_id, exc)
        db.rollback()
        _on_failure(original_file_id, f"Xử lý ảnh thất bại: {exc}", db, s3_client, uploaded_files)
        raise


# ---------------------------------------------------------------------------
# Video Task
# ---------------------------------------------------------------------------
@celery_app.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=10,
    retry_backoff_max=600,
    max_retries=2,
    reject_on_worker_lost=True,
    acks_late=True,
    name="tasks.celery_tasks.process_video_task",
)
def process_video_task(self, original_file_id: int, stored_filename: str, original_filename: str):
    from services.websocket_service import notify_ws_sync
    import subprocess

    s3_client = _build_s3_client()
    db = _build_session()
    uploaded_files: list[tuple[str, str]] = []

    # Use /tmp inside the container for temp files
    temp_dir = tempfile.gettempdir()
    input_path = os.path.join(temp_dir, f"video_in_{uuid.uuid4().hex}.mp4")
    raw_output_path = input_path.replace(".mp4", "_raw_depth.mp4")
    web_output_path = input_path.replace(".mp4", "_web_depth.mp4")
    temp_files = [input_path, raw_output_path, web_output_path]

    try:
        # 1. Download original video from MinIO
        notify_ws_sync(
            str(original_file_id),
            "processing",
            "Đã nhận video, mô hình Depth Estimation đang chạy..."
        )

        response = s3_client.get_object(Bucket=S3_bucket_name_original, Key=stored_filename)
        with open(input_path, "wb") as f:
            for chunk in response["Body"].iter_chunks():
                f.write(chunk)

        # 2. AI depth estimation → raw output
        depth_service.process_video_file(input_path, raw_output_path)

        notify_ws_sync(
            str(original_file_id),
            "processing",
            "Model Depth chạy xong. Đang tối ưu hóa video cho Web (H.264)..."
        )

        # 3. Convert to H.264
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", raw_output_path,
                "-vcodec", "libx264",
                "-pix_fmt", "yuv420p",
                "-acodec", "aac",
                web_output_path,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )

        notify_ws_sync(
            str(original_file_id),
            "processing",
            "Đang lưu video lên server..."
        )

        # 4. Upload result to depth bucket
        with open(web_output_path, "rb") as f:
            depth_bytes = f.read()

        depth_key = f"{uuid.uuid4()}.mp4"
        _upload_bytes_to_minio(
            s3_client,
            depth_bytes,
            S3_bucket_name_depth,
            depth_key,
            "video/mp4",
        )
        uploaded_files.append((S3_bucket_name_depth, depth_key))

        depth_filename = f"depth_{original_filename}"

        # 5. Save depth file record
        from models.file import FileModel
        depth_record = FileModel(
            original_filename=depth_filename,
            stored_filename=depth_key,
            content_type="video/mp4",
            file_size=len(depth_bytes),
            bucket_name=S3_bucket_name_depth,
            status="completed",
        )
        db.add(depth_record)
        db.flush()

        # 6. Update original file status
        _update_file_status(db, original_file_id, "completed", depth_record.id)
        db.commit()

        notify_ws_sync(
            str(original_file_id),
            "completed",
            "Xử lý video thành công!",
            extra_data={"depth_file_id": depth_record.id},
        )

        logger.info("process_video_task completed for original_file_id=%s", original_file_id)

    except SoftTimeLimitExceeded:
        logger.error("process_video_task timed out for original_file_id=%s", original_file_id)
        _on_failure(original_file_id, "Task bị timeout do quá thời gian giới hạn", db, s3_client, uploaded_files)
        raise

    except Exception as exc:
        logger.exception("process_video_task failed for original_file_id=%s: %s", original_file_id, exc)
        db.rollback()
        _on_failure(original_file_id, f"Xử lý video thất bại: {exc}", db, s3_client, uploaded_files)
        raise

    finally:
        # Always clean up temp files
        for path in temp_files:
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass
        db.close()


# ---------------------------------------------------------------------------
# Failure handler (shared)
# ---------------------------------------------------------------------------
def _on_failure(
    file_id: int,
    message: str,
    db: Session,
    s3_client,
    uploaded_files: list[tuple[str, str]],
):
    from services.websocket_service import notify_ws_sync

    try:
        _update_file_status(db, file_id, "failed")
    except Exception:
        db.rollback()

    # Cleanup partial MinIO uploads
    for bucket, key in uploaded_files:
        try:
            s3_client.delete_object(Bucket=bucket, Key=key)
        except Exception:
            pass

    notify_ws_sync(str(file_id), "failed", message)