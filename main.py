from fastapi import FastAPI, Request, BackgroundTasks, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import os
import math
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


def _format_size(fmt: dict) -> float | None:
    """Dung lượng ước tính của một format (byte), nếu yt-dlp có cung cấp."""
    for key in ("filesize", "filesize_approx"):
        value = fmt.get(key)
        if isinstance(value, (int, float)) and value > 0:
            return float(value)
    return None


def _iter_media_parts(info):
    """Liệt kê các file yt-dlp sẽ tải: (format_id, dung lượng ước tính)."""
    if not isinstance(info, dict):
        return

    entries = info.get("entries")
    if entries is not None and not isinstance(entries, (list, tuple)):
        # Giữ lại danh sách để lần xử lý tải sau còn dùng được.
        entries = list(entries)
        info["entries"] = entries

    if entries or info.get("_type") in ("playlist", "multi_video"):
        for entry in entries or []:
            if isinstance(entry, (tuple, list)) and len(entry) == 2:
                entry = entry[1]
            yield from _iter_media_parts(entry)
        return

    formats = info.get("requested_formats")
    if formats:
        for fmt in formats:
            yield str(fmt.get("format_id") or ""), _format_size(fmt)
    else:
        yield str(info.get("format_id") or ""), _format_size(info)


def _extract_percent(d: dict) -> float | None:
    value = d.get("_percent")
    if isinstance(value, (int, float)) and math.isfinite(value):
        return float(value)

    raw = str(d.get("_percent_str") or "").strip().replace("%", "").replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        pass

    downloaded = d.get("downloaded_bytes")
    total = d.get("total_bytes") or d.get("total_bytes_estimate")
    try:
        if downloaded is not None and total:
            return 100.0 * float(downloaded) / float(total)
    except (TypeError, ValueError):
        pass
    return None


class ProgressTracker:
    """Gộp tiến trình nhiều file (video + audio) thành một giá trị 0-100.

    Trước đây mỗi luồng tải báo % riêng nên khi chuyển từ video sang audio
    thanh tiến trình bị tụt về 0. Ở đây mỗi file chiếm một phần theo dung
    lượng ước tính, nhờ đó % tổng chỉ tăng dần.
    """

    def __init__(self):
        self.parts: list[dict] = []

    def prepare(self, info: dict) -> None:
        specs = list(_iter_media_parts(info))
        if not specs:
            return

        sizes = [size for _, size in specs]
        # Thiếu dung lượng thì chia đều để một luồng không chiếm hết thanh %.
        if all(size is not None for size in sizes):
            weights = sizes
        else:
            weights = [1.0] * len(specs)

        self.parts = [
            {"format_id": format_id, "weight": weight, "percent": 0.0, "key": None}
            for (format_id, _), weight in zip(specs, weights)
        ]

    def update(self, d: dict) -> float | None:
        if d.get("status") == "finished":
            target = 100.0
        else:
            target = _extract_percent(d)
            if target is None:
                return None

        if not self.parts:
            return min(100.0, max(0.0, target))

        part = self._resolve_part(d)
        if part is None:
            return None

        # Trong cùng một luồng, % có thể tụt khi tổng dung lượng ước tính đổi.
        part["percent"] = max(part["percent"], min(100.0, max(0.0, target)))

        total_weight = sum(p["weight"] for p in self.parts)
        if total_weight <= 0:
            return None
        return sum(p["weight"] * p["percent"] for p in self.parts) / total_weight

    def _resolve_part(self, d: dict):
        info = d.get("info_dict") or {}
        format_id = str(info.get("format_id") or "")
        media_id = str(info.get("id") or info.get("display_id") or "")
        key = (media_id, format_id) if (media_id or format_id) else str(d.get("filename") or "")

        for part in self.parts:
            if part["key"] == key:
                return part
        for part in self.parts:
            if part["key"] is None and part["format_id"] == format_id:
                part["key"] = key
                return part
        for part in self.parts:
            if part["key"] is None:
                part["key"] = key
                return part
        return None


#hàm tải video ngầm
def download_task(url: str, format_id: str, websocket: WebSocket, loop: asyncio.AbstractEventLoop):
    tracker = ProgressTracker()

    def send(payload: dict):
        asyncio.run_coroutine_threadsafe(websocket.send_json(payload), loop)

    def progress_hook(d):
        status = d.get("status")
        if status not in ("downloading", "finished"):
            return

        percent = tracker.update(d)
        if percent is None:
            return

        send({
            "status": "downloading",
            "percent": f"{percent:.1f}%",
            "speed": str(d.get("_speed_str") or "N/A").strip(),
        })

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
            'color': 'no_color'
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
            'color': 'no_color',
        }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Lấy thông tin trước để biết có bao nhiêu file (video + audio)
            # và dung lượng từng file, phục vụ việc gộp tiến trình.
            info = ydl.extract_info(url, download=False)
            if not info:
                raise RuntimeError("Không lấy được thông tin video")
            tracker.prepare(info)
            ydl.process_ie_result(info, download=True)
    except Exception as e:
        send({"status": "error", "message": str(e)})
        return

    # Chỉ báo hoàn tất sau khi tất cả luồng (và bước ghép) đã xong.
    send({"status": "finished"})

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
