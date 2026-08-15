import os
import shutil
import tempfile
from fastapi import APIRouter, UploadFile, Depends, HTTPException, BackgroundTasks, Form, File, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from typing import Optional

from configs.database import get_db
from configs.minio_store import S3_bucket_name_original, s3_client
from models.file import FileModel # Import FileModel để truy vấn DB

# Import toàn bộ logic từ Service mới tạo
from services.tasks_service import upload_to_minio_and_db, background_process_image, background_process_video
from services.file_service import get_image_bytes, get_video_bytes
from services.websocket_service import manager


router = APIRouter(prefix="/depth", tags=["Depth Estimation"])

@router.post("/image")
async def estimate_depth_image(
    background_tasks: BackgroundTasks, 
    file: Optional[UploadFile] = File(None), 
    url: Optional[str] = Form(None), 
    db: Session = Depends(get_db)
):
    if not file and not url:
        raise HTTPException(status_code=400, detail="Vui lòng cung cấp file hoặc URL")
    
    original_bytes, filename, content_type = await get_image_bytes(file, url)

    uploaded_files = []
    
    try:
        # 1. Upload ảnh gốc
        db_original = upload_to_minio_and_db(
            file_bytes=original_bytes,
            original_name=filename,
            content_type=content_type,
            db=db,
            target_bucket=S3_bucket_name_original,
            uploaded_files=uploaded_files
        )
        db.commit()
        db.refresh(db_original)

        # 2. Đẩy việc xuống Background Task
        background_tasks.add_task(
            background_process_image,
            original_bytes,
            filename,
            db_original.id  # luôn cho Background Task biết ID của file gốc
        )

        # 3. Phản hồi ngay lập tức
        return {
            "status": "processing",
            "message": "Ảnh đã được tiếp nhận và đang được AI xử lý ngầm.",
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
    background_tasks: BackgroundTasks,
    file: Optional[UploadFile] = File(None),
    url: Optional[str] = Form(None), 
    db: Session = Depends(get_db)
):
    if not file and not url:
        raise HTTPException(status_code=400, detail="Vui lòng cung cấp file hoặc URL")
    
    temp_path, filename, content_type = await get_video_bytes(file, url)
    
    # Đọc byte để upload (hoặc bạn có thể cho Background Task làm việc này)
    with open(temp_path, "rb") as f:
        original_bytes = f.read()

    uploaded_files: list[tuple[str, str]] = []
    try:
        db_original = upload_to_minio_and_db(
            file_bytes=original_bytes,
            original_name=filename,
            content_type=content_type,
            db=db,
            target_bucket=S3_bucket_name_original,
            uploaded_files=uploaded_files
        )
        db.commit()
        db.refresh(db_original)
        
        background_tasks.add_task(
            background_process_video, 
            temp_path, 
            filename,
            db_original.id  # THÊM MỚI: Truyền ID để Task cập nhật trạng thái
        )

        return {
            "status": "processing",
            "message": "Video đã được tiếp nhận và đang được AI xử lý ngầm.",
            "original_video": db_original
        }
        
    except Exception as e:
        db.rollback()
        if os.path.exists(temp_path): os.remove(temp_path)
        for bucket, key in uploaded_files:
            try:
                s3_client.delete_object(Bucket=bucket, Key=key)
            except Exception:
                pass
        raise HTTPException(status_code=500, detail=f"Lỗi hệ thống: {str(e)}")


# check tiến độ liên tục thông qua file_id
@router.get("/status/{file_id}")
async def check_task_status(file_id: int, db: Session = Depends(get_db)):
    """
    Frontend sẽ gọi API này liên tục (ví dụ: mỗi 3 giây) 
    để kiểm tra xem file đã được xử lý xong chưa.
    """
    # 1. Tìm file gốc trong Database
    db_original = db.query(FileModel).filter(FileModel.id == file_id).first()
    if not db_original:
        raise HTTPException(status_code=404, detail="Không tìm thấy file với ID này.")
    
    current_status = db_original.status.lower()

    # 2. Kiểm tra trạng thái
    if current_status == "processing":
        return {
            "status": "processing", 
            "message": "Task Depth vẫn đang được thực thi ..."
        }
    elif current_status == "failed":
        return {
            "status": "failed", 
            "message": "Quá trình xử lý Depth failed"
        }
        
    # 3. Nếu trạng thái là "completed", truy vấn lấy luôn file kết quả AI
    db_depth = db.query(FileModel).filter(FileModel.id == db_original.depth_file_id).first()
    
    return {
        "status": "completed",
        "message": "Depth Estimation cho ảnh này đã xong",
        "original_file": db_original,
        "depth_file": db_depth
    }

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
            await websocket.send_json({"status": "completed", "message": "File đã hoàn thành từ trước"})
            await websocket.close()
            return
        elif current_status == "failed":
            await websocket.send_json({"status": "failed", "message": "File đã bị lỗi từ trước"})
            await websocket.close()
            return
        else:
            await websocket.send_json({"status": "processing", "message": "Đã kết nối thành công, đang chờ AI..."})

        # 2. Giữ đường dây điện thoại mở liên tục
        while True:
            # Lệnh này dùng để giữ connection không bị ngắt. 
            # Dù Frontend không gửi gì, loop vẫn phải đứng ở đây để chờ
            data = await websocket.receive_text()
            
    except WebSocketDisconnect:
        manager.disconnect(websocket, file_id)
    except Exception:
        manager.disconnect(websocket, file_id)