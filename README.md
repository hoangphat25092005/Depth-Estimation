# File Upload System - Depth Estimation API

Một hệ thống Backend API hiệu năng cao được xây dựng bằng **FastAPI** để giải quyết bài toán **Depth Estimation** (Ước lượng chiều sâu) cho cả hình ảnh và video.

Dự án được thiết kế với kiến trúc chịu tải tốt, sử dụng Background Tasks cho tiến trình AI nặng, tối ưu hóa tốc độ inference bằng **ONNX**, quản lý file qua **MinIO** và thao tác database qua **SQLAlchemy**.

## Tính năng nổi bật

- **Xử lý Đa phương tiện:** Hỗ trợ dự đoán chiều sâu cho cả Ảnh (Image) và Video.
- **Nguồn đầu vào linh hoạt:** Chấp nhận file upload từ máy tính (Local) hoặc tải trực tiếp thông qua URL.
- **Tích hợp YouTube:** Tự động bắt link và tải video từ YouTube thông qua `yt-dlp`.
- **Kiến trúc Bất đồng bộ (Async/Background Tasks):** Các model AI nặng được đẩy xuống luồng ngầm để xử lý, không làm đơ server hay timeout các request HTTP.
- **Tối ưu hóa hiệu năng (ONNX):** Ứng dụng chuẩn ONNX và ONNXRuntime giúp tăng tốc độ xử lý model AI lên nhiều lần so với nguyên bản.
- **Tương thích Trình duyệt (Web-safe):** Tự động re-encode video đầu ra bằng **FFmpeg** sang chuẩn `H.264`, giúp video có thể xem trực tiếp (preview) ngay trên MinIO hoặc Web Frontend.
- **Tracking Tiến độ thông minh:** Quản lý trạng thái xử lý AI (`processing`, `completed`, `failed`) chuẩn xác thông qua Database.
- **WebSocket Real-time:** Hỗ trợ thông báo tiến độ xử lý theo thời gian thực qua giao thức WebSocket.

## Kiến trúc hệ thống

```
file_upload_system/
├── main.py                    # FastAPI Application Entry Point
├── requirements.txt           # Python Dependencies
├── .env                       # Environment Variables (không commit)
├── checkpoints/               # ONNX Model Files
│   └── depth_anything_v2_vits.onnx
├── configs/
│   ├── __init__.py
│   ├── setting.py             # Load environment variables
│   ├── database.py            # SQLAlchemy database setup
│   ├── minio_store.py        # MinIO/S3 client configuration
│   └── celery_app.py         # Celery worker configuration
├── models/
│   ├── __init__.py
│   └── file.py               # FileModel - Database ORM model
├── schemas/
│   ├── __init__.py
│   └── file.py               # Pydantic schemas (FileResponse, etc.)
├── routers/
│   ├── __init__.py
│   ├── file_router.py        # Endpoints: /files/upload, /files/upload-multiple
│   └── depth_router.py        # Endpoints: /depth/image, /depth/video, /depth/status, /depth/ws/status
└── services/
    ├── __init__.py
    ├── file_service.py        # File upload, download, MinIO operations
    ├── file_validator.py      # File type/size validation
    ├── depth_service.py       # ONNX Depth Anything v2 inference
    ├── tasks_service.py      # Background task processing
    └── websocket_service.py  # WebSocket connection manager
```

## Công nghệ sử dụng

| Category | Technologies |
|----------|-------------|
| Web Framework | FastAPI, Uvicorn |
| Database | SQLAlchemy ORM (MySQL via pymysql) |
| Object Storage | MinIO / AWS S3 (boto3) |
| Media Processing | OpenCV, FFmpeg, yt-dlp |
| AI & Deep Learning | PyTorch, Transformers (HuggingFace), ONNX, ONNXRuntime |
| Asynchronous | httpx, asyncio |
| Task Queue | Celery, Redis |
| Real-time | WebSocket |
| Data Validation | Pydantic |

## API Endpoints

### File Upload Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/files/upload` | Upload một file ảnh lên MinIO |
| POST | `/files/upload-multiple` | Upload nhiều file ảnh cùng lúc |

### Depth Estimation Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/depth/image` | Xử lý Depth Estimation cho ảnh (File / URL) |
| POST | `/depth/video` | Xử lý Depth Estimation cho video (File / URL / YouTube) |
| GET | `/depth/status/{file_id}` | Kiểm tra trạng thái xử lý (polling) |
| WS | `/depth/ws/status/{file_id}` | Nhận thông báo tiến độ theo thời gian thực (WebSocket) |

### Utility Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Health check endpoint |
| GET | `/test-db` | Kiểm tra kết nối Database |

## Yêu cầu hệ thống

1. **Python 3.9+**
2. **FFmpeg**: Đã được cài đặt và thêm vào biến môi trường hệ thống (`PATH`).
3. **MySQL**: Database server đang chạy.
4. **MinIO Server**: Đang chạy với ít nhất 2 buckets: `011` (original files) và `012` (depth results).
5. **Redis**: Server đang chạy (dùng cho Celery worker).

## Cài đặt

### 1. Clone kho lưu trữ

```bash
git clone <repository-url>
cd file_upload_system
```

### 2. Tạo môi trường ảo

```bash
# Windows PowerShell
python -m venv .venv
.venv\Scripts\activate

# Linux/macOS
python -m venv .venv
source .venv/bin/activate
```

### 3. Cài đặt thư viện

```bash
pip install -r requirements.txt
```

### 4. Cấu hình biến môi trường

Tạo file `.env` ở thư mục gốc của dự án:

```env
DATABASE_URL=mysql+pymysql://<username>:<password>@<host>:<port>/<database_name>
STORAGE_DOMAIN=http://localhost:9000
STORAGE_ACCESS_KEY=your_minio_access_key
STORAGE_SECRET_KEY=your_minio_secret_key
DEPTH_MODEL_PATH=./checkpoints/depth_anything_v2_vits.onnx
REDIS_WORKER_URL=redis://localhost:6379/0
REDIS_BACKEND_URL=redis://localhost:6379/0
```

### 5. Khởi chạy

```bash
# Chạy FastAPI Server
uvicorn main:app --reload

# (Tùy chọn) Chạy Celery Worker cho background tasks
celery -A configs.celery_app worker --loglevel=info
```

## API Documentation

Sau khi chạy server, truy cập giao diện Swagger UI tại:

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

## Depth Model

Hệ thống sử dụng **Depth Anything V2** - một model depth estimation state-of-the-art:

- **Input**: Hình ảnh RGB (JPEG, PNG, WebP)
- **Output**: Depth map được mã hóa màu (Colormap INFERNO)
- **Input Size**: 518x518 pixels
- **Format**: ONNX (optimized for inference)

File model cần được đặt tại: `checkpoints/depth_anything_v2_vits.onnx`

## Bucket Structure

| Bucket | Mục đích |
|--------|----------|
| `011` | Lưu trữ file gốc (ảnh/video đầu vào) |
| `012` | Lưu trữ kết quả Depth Estimation |

## Quy trình xử lý Depth Estimation

1. **Upload**: File được upload lên MinIO bucket `011`, thông tin được lưu vào MySQL với status `processing`.
2. **Background Processing**: Task ngầm khởi chạy, load model ONNX, thực hiện inference.
3. **Result Upload**: Kết quả depth map được upload lên bucket `012`.
4. **Status Update**: Database được cập nhật status thành `completed`, liên kết với file gốc qua `depth_file_id`.
5. **Notification**: WebSocket gửi thông báo real-time đến client.

## License

Dự án được xây dựng cho mục đích học tập và nghiên cứu.
