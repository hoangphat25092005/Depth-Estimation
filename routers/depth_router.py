import os
from fastapi import APIRouter, UploadFile, Depends, HTTPException, Form, File, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from typing import Optional

from configs.database import get_db
from configs.minio_store import S3_bucket_name_original, s3_client
from models.file import FileModel
from tasks.celery_tasks import celery_app

from services.tasks_service import upload_to_minio_and_db
from services.file_service import get_image_bytes, get_video_bytes
from services.websocket_service import manager

router = APIRouter(prefix="/depth", tags=["Depth Estimation"])


@router.post("/image")
async def estimate_depth_image(
    file: Optional[UploadFile] = File(None),
    url: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    if not file and not url:
        raise HTTPException(status_code=400, detail="Vui lòng cung cấp file hoặc URL")

    original_bytes, filename, content_type = await get_image_bytes(file, url)
    uploaded_files = []

    try:
        db_original = upload_to_minio_and_db(
            file_bytes=original_bytes,
            original_name=filename,
            content_type=content_type,
            db=db,
            target_bucket=S3_bucket_name_original,
            uploaded_files=uploaded_files,
            status="processing"
        )
        db.commit()
        db.refresh(db_original)

        # Dispatch to Celery queue
        task = celery_app.send_task(
            "tasks.celery_tasks.process_image_task",
            args=[db_original.id, db_original.stored_filename, filename],
        )

        return {
            "status": "processing",
            "message": "Ảnh đã được tiếp nhận và đang được AI xử lý.",
            "task_id": str(task.id),
            "original_image": db_original
        }

    except Exception as e:
        db.rollback()
        for bucket, key in uploaded_files:
            try:
                s3_client.delete_object(Bucket=bucket, Key=key)
            except Exception:
                pass
        raise HTTPException(status_code=500, detail=f"Lỗi hệ thống: {str(e)}")


@router.post("/video")
async def estimate_depth_video(
    file: Optional[UploadFile] = File(None),
    url: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    if not file and not url:
        raise HTTPException(status_code=400, detail="Vui lòng cung cấp file hoặc URL")

    temp_path, filename, content_type = await get_video_bytes(file, url)

    with open(temp_path, "rb") as f:
        original_bytes = f.read()

    uploaded_files = []

    try:
        db_original = upload_to_minio_and_db(
            file_bytes=original_bytes,
            original_name=filename,
            content_type=content_type,
            db=db,
            target_bucket=S3_bucket_name_original,
            uploaded_files=uploaded_files,
            status="processing"
        )
        db.commit()
        db.refresh(db_original)

        # Dispatch to Celery queue
        task = celery_app.send_task(
            "tasks.celery_tasks.process_video_task",
            args=[db_original.id, db_original.stored_filename, filename],
        )

        return {
            "status": "processing",
            "message": "Video đã được tiếp nhận và đang được AI xử lý.",
            "task_id": str(task.id),
            "original_video": db_original
        }

    except Exception as e:
        db.rollback()
        if os.path.exists(temp_path):
            os.remove(temp_path)
        for bucket, key in uploaded_files:
            try:
                s3_client.delete_object(Bucket=bucket, Key=key)
            except Exception:
                pass
        raise HTTPException(status_code=500, detail=f"Lỗi hệ thống: {str(e)}")


@router.get("/status/{file_id}")
async def check_task_status(file_id: int, db: Session = Depends(get_db)):
    db_original = db.query(FileModel).filter(FileModel.id == file_id).first()
    if not db_original:
        raise HTTPException(status_code=404, detail="Không tìm thấy file với ID này.")

    current_status = db_original.status.lower()

    if current_status == "processing":
        return {
            "status": "processing",
            "message": "Task Depth vẫn đang được thực thi..."
        }
    elif current_status == "failed":
        return {
            "status": "failed",
            "message": "Quá trình xử lý Depth failed"
        }

    db_depth = db.query(FileModel).filter(FileModel.id == db_original.depth_file_id).first()

    return {
        "status": "completed",
        "message": "Depth Estimation cho ảnh này đã xong",
        "original_file": db_original,
        "depth_file": db_depth
    }


@router.get("/tasks/{task_id}")
async def check_celery_task_status(task_id: str):
    """Kiểm tra trạng thái của một Celery task qua result backend."""
    from celery.result import AsyncResult
    result = AsyncResult(task_id, app=celery_app)

    response = {
        "task_id": task_id,
        "status": result.state,
    }

    if result.ready():
        if result.successful():
            response["message"] = "Task hoàn thành thành công"
            response["result"] = result.result
        elif result.failed():
            response["message"] = "Task thất bại"
            response["error"] = str(result.info)
    else:
        response["message"] = "Task đang được xử lý..."

    return response


@router.websocket("/ws/status/{file_id}")
async def websocket_status_endpoint(websocket: WebSocket, file_id: str, db: Session = Depends(get_db)):
    await manager.connect(websocket, file_id)

    try:
        db_original = db.query(FileModel).filter(FileModel.id == file_id).first()
        if not db_original:
            await websocket.send_json({"status": "error", "message": "File ID không tồn tại"})
            await websocket.close()
            return

        current_status = db_original.status.lower()
        if current_status == "completed":
            await manager.auto_disconnect({"status": "completed", "message": "File đã hoàn thành từ trước"}, file_id)
            return
        elif current_status == "failed":
            await manager.auto_disconnect({"status": "failed", "message": "File đã bị lỗi từ trước"}, file_id)
            return
        else:
            await websocket.send_json({"status": "processing", "message": "Đã kết nối thành công, đang chờ model xử lí..."})

        while True:
            await websocket.receive_text()

    except WebSocketDisconnect:
        manager.disconnect(websocket, file_id)
    except Exception:
        manager.disconnect(websocket, file_id)
