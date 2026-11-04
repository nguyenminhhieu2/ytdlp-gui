from fastapi import FastAPI, Request, BackgroundTasks, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import os
import asyncio
import yt_dlp

app = FastAPI()
os.makedirs("downloads", exist_ok=True)
templates = Jinja2Templates(directory="templates")

#Quản lý websocket
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

manager = ConnectionManager()

#Hàm tải video
def download_task(url: str, websocket: WebSocket, loop: asyncio.AbstractEventLoop):
    def progress_hook(d):
        if d['status'] == 'downloading':
            msg = {
                "status": "downloading",
                "percent": d.get('_percent_str', '0%').strip(),
                "speed": d.get('_speed_str', 'N/A').strip()
            }
            # Gửi dữ liệu an toàn từ thread sang async
            asyncio.run_coroutine_threadsafe(websocket.send_json(msg), loop)
        elif d['status'] == 'finished':
            asyncio.run_coroutine_threadsafe(websocket.send_json({"status": "finished"}), loop)

    ydl_opts = {
        'outtmpl': 'downloads/%(title)s.%(ext)s',
        'progress_hooks': [progress_hook],
        'format': 'bestvideo+bestaudio/best'
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
    except Exception as e:
        asyncio.run_coroutine_threadsafe(websocket.send_json({"status": "error", "message": str(e)}), loop)



#API route
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.post("/api/download")
async def start_download(request: Request, background_tasks: BackgroundTasks):
    data = await request.json()
    url = data.get("url")
    
    # Lấy event loop hiện tại
    loop = asyncio.get_running_loop()
    # Lấy kết nối WebSocket hiện tại (giả định chỉ có 1 người dùng)
    websocket = manager.active_connections[-1] 
    
    # Đẩy tác vụ vào background, truyền kèm url, websocket và loop
    background_tasks.add_task(asyncio.to_thread, download_task, url, websocket, loop)
    
    return {"message": "Đang tải..."}



#endpoint websocket
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text() 
    except WebSocketDisconnect:
        manager.disconnect(websocket)