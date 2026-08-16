import cv2
import numpy as np
import onnxruntime as ort
from configs.setting import DEPTH_MODEL_PATH

class DepthONNXService:
    def __init__(self, model_path="depth_anything_v2_small.onnx"):
        print("Đang tải model ONNX vào bộ nhớ...")
        # Sử dụng CPU để chạy Inference
        self.session = ort.InferenceSession(model_path, providers=['CPUExecutionProvider'])
        self.input_name = self.session.get_inputs()[0].name
        self.input_size = (518, 518)
        print("AI Model đã sẵn sàng!")
        

    def _preprocess(self, image: np.ndarray) -> np.ndarray:
        img_resized = cv2.resize(image, self.input_size, interpolation=cv2.INTER_CUBIC)
        img_rgb = cv2.cvtColor(img_resized, cv2.COLOR_BGR2RGB)
        img_norm = img_rgb.astype(np.float32) / 255.0
        
        mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
        std = np.array([0.229, 0.224, 0.225], dtype=np.float32)
        img_norm = (img_norm - mean) / std
        
        img_transposed = np.transpose(img_norm, (2, 0, 1))
        return np.expand_dims(img_transposed, axis=0)
    

    def process_single_frame(self, frame_bgr: np.ndarray) -> np.ndarray:
        orig_h, orig_w = frame_bgr.shape[:2]
        input_tensor = self._preprocess(frame_bgr)
        outputs = self.session.run(None, {self.input_name: input_tensor})
        depth_map = np.squeeze(outputs[0])

        depth_resized = cv2.resize(depth_map, (orig_w, orig_h), interpolation=cv2.INTER_CUBIC)
        depth_min, depth_max = depth_resized.min(), depth_resized.max()
        depth_normalized = (depth_resized - depth_min) / (depth_max - depth_min) * 255.0
        depth_uint8 = depth_normalized.astype(np.uint8)

        return cv2.applyColorMap(depth_uint8, cv2.COLORMAP_INFERNO)
    

    def process_image_bytes(self, image_bytes: bytes) -> bytes:
        nparr = np.frombuffer(image_bytes, np.uint8)
        original_img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if original_img is None:
            raise ValueError("Không thể đọc image input")
        depth_color = self.process_single_frame(original_img)
        success, encoded_image = cv2.imencode('.jpg', depth_color)
        return encoded_image.tobytes()
    
    
    def process_video_file(self, input_path: str, output_path: str):
        video_cap = cv2.VideoCapture(input_path)
        if not video_cap.isOpened():
            raise ValueError("Không thể đọc video input")
        
        fps = video_cap.get(cv2.CAP_PROP_FPS)
        width = int(video_cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(video_cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total_frames = int(video_cap.get(cv2.CAP_PROP_FRAME_COUNT))

        # VIdeoWriter 
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))

        frame_count = 0
        while True:
            ret, frame = video_cap.read()
            if not ret:
                break # Hết video
            
            # Xử lý frame bằng AI
            depth_frame = self.process_single_frame(frame)
            out.write(depth_frame) # Ghi vào video đầu ra
            
            frame_count += 1
            if frame_count % 10 == 0:
                print(f"Đang xử lý Video: {frame_count}/{total_frames} frames...")


        
        # Dọn dẹp bộ nhớ 
        video_cap.release()
        out.release()

# Khởi tạo instance (Chỉ chạy 1 lần khi server start)
depth_service = DepthONNXService(DEPTH_MODEL_PATH)