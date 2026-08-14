# 🌊 Depth Estimation API

Một hệ thống Backend API hiệu năng cao được xây dựng bằng **FastAPI** để giải quyết bài toán **Depth Estimation** (Ước lượng chiều sâu) cho cả hình ảnh và video. 

Dự án được thiết kế với kiến trúc chịu tải tốt, sử dụng Background Tasks cho tiến trình AI nặng, tối ưu hóa tốc độ inference bằng **ONNX**, quản lý file qua **MinIO** và thao tác database qua **SQLAlchemy**.

## ✨ Tính năng nổi bật
- 🖼️ **Xử lý Đa phương tiện:** Hỗ trợ dự đoán chiều sâu cho cả Ảnh (Image) và Video.
- 🌐 **Nguồn đầu vào linh hoạt:** Chấp nhận file upload từ máy tính (Local) hoặc tải trực tiếp thông qua URL.
- 📺 **Tích hợp YouTube:** Tự động bắt link và tải video từ YouTube thông qua `yt-dlp`.
- ⚡ **Kiến trúc Bất đồng bộ (Async/Background Tasks):** Các model AI nặng được đẩy xuống luồng ngầm để xử lý, không làm đơ server hay timeout các request HTTP.
- 🚀 **Tối ưu hóa hiệu năng (ONNX):** Ứng dụng chuẩn ONNX và ONNXRuntime giúp tăng tốc độ xử lý model AI lên nhiều lần so với nguyên bản.
- 🎞️ **Tương thích Trình duyệt (Web-safe):** Tự động re-encode video đầu ra bằng **FFmpeg** sang chuẩn `H.264`, giúp video có thể xem trực tiếp (preview) ngay trên MinIO hoặc Web Frontend.
- 🗄️ **Tracking Tiến độ thông minh:** Quản lý trạng thái xử lý AI (`processing`, `completed`, `failed`) chuẩn xác thông qua Database.

## 🛠️ Công nghệ sử dụng
- **Web Framework:** FastAPI, Uvicorn
- **Database:** SQLAlchemy ORM (hỗ trợ PostgreSQL / MySQL)
- **Object Storage:** MinIO / AWS S3 (`boto3`)
- **Media Processing:** OpenCV, FFmpeg, `yt-dlp`
- **AI & Deep Learning:** PyTorch, Transformers (HuggingFace), ONNX, ONNXRuntime
- **Asynchronous:** `httpx`, `asyncio`

## ⚙️ Yêu cầu hệ thống (Prerequisites)
Để chạy dự án này trên môi trường local, máy tính của bạn cần có:
1. **Python 3.9+**
2. **FFmpeg**: Đã được cài đặt và thêm vào biến môi trường hệ thống (`PATH`).
3. **Database**: SQLite/PostgreSQL/MySQL (Tùy cấu hình).
4. **MinIO Server**: Đang chạy hoặc có sẵn bucket trên AWS S3.

## 🚀 Hướng dẫn cài đặt

**Bước 1: Clone kho lưu trữ**
```bash
git clone [https://github.com/hoangphat25092005/Depth-Estimation.git](https://github.com/hoangphat25092005/Depth-Estimation.git)
cd Depth-Estimation
```

**Bước 2: Tạo môi trường và cài đặt thư viện liên quan**
python -m venv .venv

# Kích hoạt môi trường (Mac/Linux)
source .venv/bin/activate  
# Kích hoạt môi trường (Windows PowerShell)
.venv\Scripts\activate     

# Cài đặt các thư viện cần thiết
pip install -r requirements.txt


**Bước 3: Cấu hình biến môi trường**
Tạo một file .env ở thư mục gốc của dự án và điền các thông tin cần thiết (URL Database, MinIO Endpoint, Access Key, Secret Key,...).

**Bước 4: Khởi chạy server**
uvicorn main:app --reload

📚 Tài liệu API (Swagger UI)
Sau khi chạy server, bạn có thể truy cập giao diện test API tương tác tại:
👉 http://localhost:8000/docs

Các Endpoints chính:
- POST /depth/image: Xử lý Depth Estimation cho Ảnh (Hỗ trợ File / URL).

- POST /depth/video: Xử lý Depth Estimation cho Video (Hỗ trợ File / URL / YouTube).

- GET /depth/status/{file_id}: Polling API dùng để kiểm tra liên tục trạng thái tiến trình AI.

📝 License
Dự án được xây dựng cho mục đích học tập và nghiên cứu.