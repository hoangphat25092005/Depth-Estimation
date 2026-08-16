import os
import shutil
import tempfile
import httpx
import uuid
import asyncio
from yt_dlp import YoutubeDL
from fastapi import UploadFile, HTTPException
from sqlalchemy.orm import Session
from models.file import FileModel
from configs.minio_store import S3_bucket_name_original, s3_client
from services.file_validator import validate_file


def _read_upload_file(file: UploadFile) -> bytes:
    """Đọc toàn bộ UploadFile trong sync context (tránh SpooledTemporaryFile race)."""
    try:
        file.file.seek(0)
    except Exception:
        pass
    return file.file.read()


def _save_upload_to_temp_file(file: UploadFile, suffix: str) -> str:
    """Ghi UploadFile ra temp file (sync, tránh SpooledTemporaryFile race)."""
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    with open(path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    return path


# Download youtube videos
def download_youtube_sync(url: str, output_path: str):
    """Sử dụng yt-dlp để tải video YouTube và lưu vào output_path"""
    ydl_opts = {
        'format': 'best[ext=mp4]/bestvideo[ext=mp4]+bestaudio[ext=m4a]/best',
        'outtmpl': output_path,
        'quiet': True,
        'no_warnings': True,
    }
    with YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])


# File Downloading (images/videos from Internet)
async def get_image_bytes(file: UploadFile = None, url: str = None) -> tuple[bytes, str, str]:
    # Làm sạch rác từ Swagger UI
    if url:
        url = url.strip()
        if url.lower() in ["string", "null", ""]:
            url = None

    # ưu tiên file local trên máy
    if file and file.filename:
        return await file.read(), file.filename, file.content_type

    # Không có file thì mới dùng url
    elif url:
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": url,
            "Accept": "image/*;q=0.9,application/json,*/*;q=0.8"
        }

        async with httpx.AsyncClient(follow_redirects=True) as client:
            response = await client.get(url, headers=headers)
            if response.status_code != 200:
                raise HTTPException(status_code=400, detail=f"Không thể tải ảnh. Server trả về mã: {response.status_code}")

            filename = url.split("/")[-1].split("?")[0] or "downloaded_image.jpg"
            content_type = response.headers.get("content-type", "image/jpeg")
            return response.content, filename, content_type
    else:
        raise HTTPException(status_code=400, detail="Vui lòng cung cấp file hoặc URL.")


async def get_video_bytes_from_url(url: str, temp_path: str) -> tuple[str, str]:
    """Download video từ URL vào temp_path có sẵn."""
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": url,
        "Accept": "video/webm,video/mp4,video/*;q=0.9,application/json,*/*;q=0.8"
    }

    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        async with client.stream("GET", url, headers=headers) as response:
            if response.status_code != 200:
                raise HTTPException(status_code=400, detail=f"Không thể tải video. Server trả về mã: {response.status_code}")

            with open(temp_path, "wb") as f:
                async for chunk in response.aiter_bytes():
                    f.write(chunk)

    filename = url.split("/")[-1].split("?")[0] or "downloaded_video.mp4"
    return filename, "video/mp4"


# Video Download - trả về temp_path để background task đọc
async def get_video_bytes(file: UploadFile = None, url: str = None) -> tuple[str, str, str]:
    # Làm sạch rác từ Swagger UI
    if url:
        url = url.strip()
        if url.lower() in ["string", "null", ""]:
            url = None

    fd_in, temp_input_path = tempfile.mkstemp(suffix=".mp4")
    fd_raw, temp_raw_path = tempfile.mkstemp(suffix="_raw_depth.mp4")
    fd_web, temp_web_path = tempfile.mkstemp(suffix="_web_depth.mp4")
    os.close(fd_in)
    os.close(fd_raw)
    os.close(fd_web)
    os.remove(temp_raw_path)
    os.remove(temp_web_path)

    # ƯU TIÊN FILE TỪ MÁY TÍNH
    if file and file.filename:
        path = await asyncio.to_thread(_save_upload_to_temp_file, file, ".mp4")
        return path, file.filename, file.content_type

    # NẾU KHÔNG CÓ FILE, MỚI DÙNG URL
    elif url:
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"

        if "youtube.com" in url or "youtu.be" in url:
            try:
                await asyncio.to_thread(download_youtube_sync, url, temp_input_path)
                return temp_input_path, "youtube_download.mp4", "video/mp4"
            except Exception as e:
                if os.path.exists(temp_input_path):
                    os.remove(temp_input_path)
                raise HTTPException(status_code=400, detail=f"Lỗi khi tải từ YouTube: {str(e)}")
        else:
            try:
                filename, content_type = await get_video_bytes_from_url(url, temp_input_path)
                return temp_input_path, filename, content_type
            except HTTPException:
                if os.path.exists(temp_input_path):
                    os.remove(temp_input_path)
                raise
            except Exception as e:
                if os.path.exists(temp_input_path):
                    os.remove(temp_input_path)
                raise HTTPException(status_code=400, detail=f"Lỗi mạng khi tải video từ URL: {str(e)}")
    else:
        if os.path.exists(temp_input_path):
            os.remove(temp_input_path)
        raise HTTPException(status_code=400, detail="Vui lòng cung cấp file hoặc URL.")


# MinIO
# Upload single file
async def upload_single_file(file: UploadFile, db: Session, auto_commit: bool = True) -> FileModel:
    validate_file(file)

    extension = f".{file.filename.split('.')[-1].lower()}" if '.' in file.filename else ""
    stored_filename = f"{uuid.uuid4()}{extension}"

    try:
        s3_client.upload_fileobj(
            file.file,
            S3_bucket_name_original,
            stored_filename,
            ExtraArgs={"ContentType": file.content_type}
        )

        db_file = FileModel(
            original_filename=file.filename,
            stored_filename=stored_filename,
            content_type=file.content_type,
            file_size=file.size,
            bucket_name=S3_bucket_name_original
        )

        db.add(db_file)

        if auto_commit:
            db.commit()
            db.refresh(db_file)
        else:
            db.flush()

        return db_file

    except Exception:
        try:
            s3_client.delete_object(Bucket=S3_bucket_name_original, Key=stored_filename)
        except Exception:
            pass
        raise


# Upload Multiple Files Logic
async def upload_multiple_files(files: list[UploadFile], db: Session) -> list[FileModel]:
    uploaded_files = []

    try:
        for file in files:
            db_file = await upload_single_file(file=file, db=db, auto_commit=False)
            uploaded_files.append(db_file)

        db.commit()

        for db_file in uploaded_files:
            db.refresh(db_file)

        return uploaded_files

    except Exception:
        db.rollback()
        for db_file in uploaded_files:
            try:
                s3_client.delete_object(Bucket=db_file.bucket_name, Key=db_file.stored_filename)
            except Exception:
                continue
        raise
