import asyncio 
from fastapi import WebSocket

class ConnectionManager:
    def __init__(self):
        # Dùng list để lỡ user mở 2 tab web cùng xem 1 file thì cả 2 đều nhận được
        self.active_connections: dict[str, list[WebSocket]] = {}
        self.main_loop = None
    
    async def connect(self, websocket: WebSocket, file_id: str):

        if self.main_loop is None:
            self.main_loop = asyncio.get_running_loop()

        await websocket.accept()

        file_id_str = str(file_id)
        if file_id_str not in self.active_connections:
            self.active_connections[file_id_str] = []

        self.active_connections[file_id_str].append(websocket)


    def disconnect(self, websocket: WebSocket, file_id: str):
        file_id_str = str(file_id)
        if file_id_str in self.active_connections:
            if websocket in self.active_connections[file_id_str]:
                self.active_connections[file_id_str].remove(websocket)
            if not self.active_connections[file_id_str]:
                del self.active_connections[file_id_str]


    async def send_message(self, message: dict, file_id: str):
        file_id_str = str(file_id)
        if file_id_str in self.active_connections:
            for connection in list(self.active_connections[file_id_str]):
                try:
                    await connection.send_json(message)
                except Exception:
                    pass

    async def auto_disconnect(self, message: dict, file_id: str):
        """Gửi message cuối cùng rồi tự động đóng kết nối."""
        file_id_str = str(file_id)
        if file_id_str in self.active_connections:
            for connection in list(self.active_connections[file_id_str]):
                try:
                    await connection.send_json(message)
                    await connection.close(code=1000)
                except Exception:
                    pass
            self.disconnect(connection, file_id_str)



# Called an instance of the websocket connection
manager = ConnectionManager()


# 2. Hàm phụ trợ để truyền thông báo từ background tasks sang luồn websocket chính
def notify_ws_sync(file_id: str, status: str, message: str, extra_data: dict = None):
    """Bắn tin nhắn từ Background Task (luồng phụ) về WebSocket (luồng chính)"""
    data = {"status": status, "message": message}
    if extra_data:
        data.update(extra_data)
    
    try:
        if manager.main_loop and manager.main_loop.is_running():
            asyncio.run_coroutine_threadsafe(manager.send_message(data, str(file_id)), manager.main_loop)
        else:
            print("Chưa có luồng chính hoạt động hoặc chưa có client WebSocket nào kết nối.")
    except Exception as e:
        print(f"Lỗi khi gửi WebSocket: {e}")