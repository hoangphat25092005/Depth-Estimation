import os
import shutil
import tempfile
import httpx
import uuid
import boto3
import asyncio
from yt_dlp import YoutubeDL
from fastapi import UploadFile, HTTPException
from sqlalchemy.orm import Session
from models.file import FileModel
from configs.minio_store import S3_bucket_name_original, S3_bucket_name_depth, s3_client
from services.file_validator import validate_file, MAX_SIZE_FILE


# Download youtube videos
def download_youtube_sync(url: str, output_path: str):
    """Sử dụng yt-dlp để tải video YouTube và lưu vào output_path"""
    ydl_opts = {
        'format': 'best[ext=mp4]/bestvideo[ext=mp4]+bestaudio[ext=m4a]/best', # Ưu tiên mp4
        'outtmpl': output_path, 
        'quiet': True,         
        'no_warnings': True,
    }
    with YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
    

# File Downloading (images/videos from Internet)
async def get_image_bytes(file: UploadFile = None, url: str = None) -> tuple[bytes, str, str]:
    # 1. Làm sạch rác từ Swagger UI (nếu có)
    if url:
        url = url.strip()
        # Nếu Swagger tự gửi chữ "string", "null" hoặc rỗng -> coi như không có URL
        if url.lower() in ["string", "null", ""]:
            url = None

    # 2. ƯU TIÊN FILE TỪ MÁY TÍNH
    if file and file.filename:
        return await file.read(), file.filename, file.content_type
        
    # 3. NẾU KHÔNG CÓ FILE, MỚI DÙNG URL
    elif url:
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"

        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            if response.status_code != 200:
                raise HTTPException(status_code=400, detail="Không thể tải ảnh từ url")
            filename =  url.split("/")[-1].split("?")[0] or "downloaded_image.jpg"
            content_type = response.headers.get("content-type", "image/jpeg")
            return response.content, filename, content_type
    else:
        raise HTTPException(status_code=400, detail="Vui lòng cung cấp file hoặc URL.")


# Video Download
async def get_video_bytes(file: UploadFile = None, url: str = None) -> tuple[str, str, str]:
    # 1. Làm sạch rác từ Swagger UI
    if url:
        url = url.strip()
        if url.lower() in ["string", "null", ""]:
            url = None

    fd, temp_input_path = tempfile.mkstemp(suffix=".mp4")
    
    # 2. ƯU TIÊN FILE TỪ MÁY TÍNH
    if file and file.filename:
        with os.fdopen(fd, "wb") as f:
            shutil.copyfileobj(file.file, f)
        return temp_input_path, file.filename, file.content_type

    # 3. NẾU KHÔNG CÓ FILE, MỚI DÙNG URL
    elif url:
        os.close(fd) 
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"
            
        if "youtube.com" in url or "youtu.be" in url:
            try:
                await asyncio.to_thread(download_youtube_sync, url, temp_input_path)
                filename = "youtube_download.mp4"
                return temp_input_path, filename, "video/mp4"
            except Exception as e:
                if os.path.exists(temp_input_path): os.remove(temp_input_path)
                raise HTTPException(status_code=400, detail=f"Lỗi khi tải từ YouTube: {str(e)}")
        else:
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    async with client.stream("GET", url) as response:
                        if response.status_code != 200:
                            raise HTTPException(status_code=400, detail="Không thể tải video từ url")
                        with open(temp_input_path, "wb") as f:
                            async for chunk in response.aiter_bytes():
                                f.write(chunk)
                filename = url.split("/")[-1].split("?")[0] or "downloaded_video.mp4"
                return temp_input_path, filename, "video/mp4"
            except Exception as e:
                if os.path.exists(temp_input_path): os.remove(temp_input_path)
                raise HTTPException(status_code=400, detail=f"Lỗi tải video từ URL: {str(e)}")
    else:
        # Nếu cả 2 đều trống
        os.close(fd)
        if os.path.exists(temp_input_path): os.remove(temp_input_path)
        raise HTTPException(status_code=400, detail="Vui lòng cung cấp file hoặc URL.")
    
# MinIO 
# Upload single file
async def upload_single_file(file: UploadFile, db: Session, auto_commit: bool = True) -> FileModel:
    # 1. Validate file first
    validate_file(file)


    extension = f".{file.filename.split('.')[-1].lower()}" if '.' in file.filename else ""
    stored_filename = f"{uuid.uuid4()}{extension}"

    try:
        # 2. Upload File trực tiếp lên MinIO
        s3_client.upload_fileobj(
            file.file, 
            S3_bucket_name_original, 
            stored_filename, 
            ExtraArgs={
                "ContentType": file.content_type
            }
        )

        # 3. Chuẩn bị dữ liệu để lưu vào DB
        db_file = FileModel(
            original_filename=file.filename, 
            stored_filename=stored_filename, 
            content_type=file.content_type, 
            file_size=file.size, 
            bucket_name=S3_bucket_name_original
        )

        db.add(db_file)

        # 4. Kiểm tra xem có được phép commit luôn không
        if auto_commit:
            db.commit()
            db.refresh(db_file)
        else:
            # flush() đẩy dữ liệu tạm thời vào DB để lấy ID (nếu cần) và kiểm tra lỗi, 
            # nhưng CHƯA lưu vĩnh viễn (chưa commit).
            db.flush() 

        return db_file
    
    except Exception:
        # Xóa file trên MinIO nếu có lỗi (ví dụ lỗi DB)
        try:
            s3_client.delete_object(Bucket=S3_bucket_name_original, Key=stored_filename)
        except Exception:
            pass # Bỏ qua lỗi xóa để raise lỗi chính
        raise


# Upload Multiple Files Logic
async def upload_multiple_files(files: list[UploadFile], db: Session) -> list[FileModel]:
    uploaded_files = []
    
    try:
        for file in files:
            # Gọi hàm single nhưng cấm nó tự động commit
            db_file = await upload_single_file(file=file, db=db, auto_commit=False)
            uploaded_files.append(db_file)

        # Nếu toàn bộ file đều lưu vật lý thành công và add vào session thành công,
        # lúc này ta mới commit toàn bộ vào Database cùng một lúc.
        db.commit()

        # Refresh toàn bộ để cập nhật ID/thông tin mới nhất từ DB
        for db_file in uploaded_files:
            db.refresh(db_file)

        return uploaded_files
    
    except Exception:
        # Nếu có bất kì lỗi ở các file :
        # 1. Rollback toàn bộ dữ liệu database (File 1 và File 2 sẽ không bị lưu vào DB)
        db.rollback()

        # 2. Xóa các file vật lý đã lỡ upload thành công lên MinIO
        for db_file in uploaded_files:
            try:
                s3_client.delete_object(Bucket=db_file.bucket_name, Key=db_file.stored_filename)
            except Exception:
                continue

        raise