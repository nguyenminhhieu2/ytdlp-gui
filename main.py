from fastapi import FastAPI, Request, BackgroundTasks, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import os
import asyncio
import yt_dlp

app = FastAPI()
os.makedirs("downloads", exist_ok=True)
templates = Jinja2Templates(directory="templates")

#quản lý websocket
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

manager = ConnectionManager()

#hàm tải video ngầm
def download_task(url: str, format_id: str, websocket: WebSocket, loop: asyncio.AbstractEventLoop):
    def progress_hook(d):
        if d['status'] == 'downloading':
            msg = {
                "status": "downloading",
                "percent": d.get('_percent_str', '0%').strip(),
                "speed": d.get('_speed_str', 'N/A').strip()
            }
            asyncio.run_coroutine_threadsafe(websocket.send_json(msg), loop)
        elif d['status'] == 'finished':
            asyncio.run_coroutine_threadsafe(websocket.send_json({"status": "finished"}), loop)

    #cấu hình cho mp3 và video ( người dùng chọn )
    if format_id == 'mp3':
        ydl_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'outtmpl': 'downloads/%(title)s.%(ext)s',
            'progress_hooks': [progress_hook],
            'cookiefile': 'cookies.txt',
            'quiet': True,
        }
    else:
        if not format_id or format_id == 'best':
            format_selector = 'bestvideo+bestaudio/best'
        else:
            # Format video-only cần ghép thêm audio; fallback cho format đã có sẵn audio
            format_selector = f"{format_id}+bestaudio/{format_id}/best"
        ydl_opts = {
            'format': format_selector,
            'outtmpl': 'downloads/%(title)s.%(ext)s',
            'progress_hooks': [progress_hook],
            'cookiefile': 'cookies.txt',
            'quiet': True,
        }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
    except Exception as e:
        asyncio.run_coroutine_threadsafe(websocket.send_json({"status": "error", "message": str(e)}), loop)

# api routes 
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(request, "index.html")

def pick_video_formats(info: dict) -> list[dict]:
    """Gom format video theo độ phân giải, ưu tiên fps cao rồi tới MP4/H.264."""
    best_by_height: dict[int, dict] = {}

    def score(f: dict) -> tuple:
        ext = str(f.get("ext") or "").lower()
        vcodec = str(f.get("vcodec") or "")
        return (
            float(f.get("fps") or 0),
            1 if ext == "mp4" else 0,
            1 if vcodec.startswith(("avc1", "h264")) else 0,
            float(f.get("tbr") or f.get("vbr") or 0),
        )

    for f in info.get("formats", []):
        if str(f.get("vcodec") or "none") == "none":
            continue

        try:
            height = int(f.get("height") or 0)
        except (TypeError, ValueError):
            continue

        if height <= 0:
            continue

        current = best_by_height.get(height)
        if current is None or score(f) > score(current):
            best_by_height[height] = f

    formats = [{"id": "best", "label": "Chất lượng tốt nhất (tự động)"}]

    for height in sorted(best_by_height, reverse=True):
        f = best_by_height[height]
        fps = int(round(float(f.get("fps") or 0)))
        ext = str(f.get("ext") or "").upper()
        label = f"Video {height}p{'60' if fps >= 50 else ''}"
        if ext:
            label += f" ({ext})"
        formats.append({"id": str(f["format_id"]), "label": label})

    formats.append({"id": "mp3", "label": "Chỉ tải Âm thanh (MP3)"})
    return formats


@app.post("/api/info")
async def get_video_info(request: Request):
    data = await request.json()
    url = (data.get("url") or "").strip()
    if not url:
        return {"error": "Chưa có URL"}

    def extract_info():
        ydl_opts = {'quiet': True, 'cookiefile': 'cookies.txt'}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(url, download=False)

    try:
        # Chạy yt-dlp trong thread để không chặn event loop / WebSocket
        info = await asyncio.to_thread(extract_info)
        return {"title": info.get("title"), "formats": pick_video_formats(info)}
    except Exception as e:
        return {"error": str(e)}

@app.post("/api/download")
async def start_download(request: Request, background_tasks: BackgroundTasks):
    data = await request.json()
    url = data.get("url")
    format_id = data.get("format_id", "best")
    
    loop = asyncio.get_running_loop()
    websocket = manager.active_connections[-1] if manager.active_connections else None
    
    if websocket:
        background_tasks.add_task(asyncio.to_thread, download_task, url, format_id, websocket, loop)
    
    return {"message": "Đang tải..."}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
