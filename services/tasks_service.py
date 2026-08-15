import os
import uuid
import io
import subprocess
from sqlalchemy.orm import Session

from configs.database import SessionLocal
from configs.minio_store import S3_bucket_name_depth, s3_client
from models.file import FileModel
from services.depth_service import depth_service
from services.websocket_service import notify_ws_sync


def upload_to_minio_and_db(
    file_bytes: bytes, 
    original_name: str, 
    content_type: str, 
    db: Session,
    target_bucket: str,
    uploaded_files: list[tuple[str, str]], 
    status: str = "processing"
) -> FileModel:
    """Hàm phụ trợ để lưu file vào MinIO và Database"""
    extension = f".{original_name.split('.')[-1].lower()}" if '.' in original_name else ".jpg"
    stored_name = f"{uuid.uuid4()}{extension}"
    
    file_stream = io.BytesIO(file_bytes)
    s3_client.upload_fileobj(
        file_stream, 
        target_bucket,
        stored_name,
        ExtraArgs={"ContentType": content_type}
    )
    
    uploaded_files.append((target_bucket, stored_name))

    db_file = FileModel(
        original_filename=original_name,
        stored_filename=stored_name,
        content_type=content_type,
        file_size=len(file_bytes),
        bucket_name=target_bucket, 
        status=status
    )
    db.add(db_file)
    db.flush() 
    return db_file


def background_process_image(original_bytes: bytes, original_filename: str, original_file_id: str):
    """Task ngầm xử lý Ảnh"""
    db = SessionLocal()
    uploaded_files: list[tuple[str, str]] = []

    # Thong bao tiep nhan anh de xu ly depth 
    notify_ws_sync(original_file_id, "processing", "Đã nhận ảnh, qua trình Depth Estimation bắt đầu...")
    
    try:
        depth_bytes = depth_service.process_image_bytes(original_bytes)
        depth_filename = f"depth_{original_filename}"

        # Model dang xu ly
        notify_ws_sync(original_file_id, "processing", "Depth model xử lý xong. Đang lưu ảnh lên hệ thống...")

        db_depth = upload_to_minio_and_db(
            file_bytes=depth_bytes,
            original_name=depth_filename,
            content_type="image/jpeg",
            db=db,
            target_bucket=S3_bucket_name_depth,
            uploaded_files=uploaded_files, 
            status="completed"
        )

        db_original = db.query(FileModel).filter(FileModel.id == original_file_id).first()
        if db_original:
            db_original.status = "completed"
            db_original.depth_file_id = db_depth.id

        db.commit()

        # Hoàn thành qua trinh xu ly depth
        notify_ws_sync(original_file_id, "completed", "Xử lý ảnh thành công!", extra_data={
            "depth_file_id": db_depth.id
        })


    except Exception as e:
        db.rollback()
        print(f"Lỗi xử lý ảnh ngầm: {str(e)}")

        notify_ws_sync(original_file_id, "failed", f"Xử lý ảnh thất bại: {str(e)}")

        try:
            db_original = db.query(FileModel).filter(FileModel.id == original_file_id).first()
            if db_original:
                db_original.status = "failed"
                db.commit()
        except Exception as db_err:
            print(f"Lỗi khi cập nhật trạng thái failed cho ảnh: {str(db_err)}")
            db.rollback()

        # Dọn rác MinIO nếu upload thất bại giữa chừng
        for bucket, key in uploaded_files:
            try:
                s3_client.delete_object(Bucket=bucket, Key=key)
            except Exception:
                pass
    finally:
        db.close()


def background_process_video(input_file_path: str, original_filename: str, original_file_id: str):
    """Task ngầm xử lý Video"""
    raw_output_path = input_file_path.replace(".mp4", "_raw_depth.mp4")
    web_output_path = input_file_path.replace(".mp4", "_web_depth.mp4") # File chuẩn H.264
    
    db = SessionLocal()
    uploaded_files: list[tuple[str, str]] = []

    # Cập nhật trạng thái
    db_original = db.query(FileModel).filter(FileModel.id == original_file_id).first()
    if db_original:
        db_original.status = "processing"
        db.commit()

    notify_ws_sync(original_file_id, "processing", "Đã nhận video, mô hình Depth Estimation đang chạy...")


    try:
        # 1. AI xử lý video (lưu ra file raw)
        depth_service.process_video_file(input_file_path, raw_output_path)

        notify_ws_sync(original_file_id, "processing", "AI chạy xong. Đang tối ưu hóa video cho Web (H.264)...")
        
        # 2. Convert sang H.264 bằng FFmpeg
        # Lệnh này tương đương: ffmpeg -i raw_output.mp4 -vcodec libx264 -acodec aac web_output.mp4
        command = [
            "ffmpeg", "-y", # -y để ghi đè nếu file đã tồn tại
            "-i", raw_output_path, 
            "-vcodec", "libx264", # Ép chuẩn H.264
            "-pix_fmt", "yuv420p", # Chuẩn màu an toàn nhất cho web
            "-acodec", "aac", 
            web_output_path
        ]
        
        # Chạy lệnh FFmpeg (chặn cho đến khi convert xong)
        subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

        notify_ws_sync(original_file_id, "processing", "Đang lưu video lên server...")

        # 3. Đọc byte từ file H.264 chuẩn web để upload lên MinIO
        with open(web_output_path, "rb") as f:
            depth_bytes = f.read()

        depth_filename = f"depth_{original_filename}"
        db_depth = upload_to_minio_and_db(
            file_bytes=depth_bytes,
            original_name=depth_filename,
            content_type="video/mp4",
            db=db,
            target_bucket=S3_bucket_name_depth,
            uploaded_files=uploaded_files,
            status="completed"
        )
        
        # 4. Cập nhật Database
        db_original = db.query(FileModel).filter(FileModel.id == original_file_id).first()
        if db_original:
            db_original.status = "completed"
            db_original.depth_file_id = db_depth.id
        db.commit()

        notify_ws_sync(original_file_id, "completed", "Xử lý video thành công toàn bộ!", extra_data={
            "depth_file_id": db_depth.id
        })

    except Exception as e:
        db.rollback()
        print(f"Lỗi xử lý video ở background: {str(e)}")

        notify_ws_sync(original_file_id, "failed", f"Xử lý video thất bại: {str(e)}")

        try:
            db_original = db.query(FileModel).filter(FileModel.id == original_file_id).first()
            if db_original:
                db_original.status = "failed" 
                db.commit()
        except Exception as db_err:
            print(f"Lỗi khi cập nhật trạng thái failed: {str(db_err)}")
            db.rollback()

        for bucket, key in uploaded_files:
            try:
                s3_client.delete_object(Bucket=bucket, Key=key)
            except Exception:
                pass
    finally:
        db.close()
        # Dọn dẹp cả 3 file: input, raw output, web output
        for path in [input_file_path, raw_output_path, web_output_path]:
            if os.path.exists(path): 
                os.remove(path)