from fastapi import FastAPI, Request, BackgroundTasks, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
import os
import re
import math
import asyncio
import yt_dlp

app = FastAPI()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOADS_DIR = os.path.join(BASE_DIR, "downloads")
COOKIES_FILE = os.path.join(BASE_DIR, "cookies.txt")
os.makedirs(DOWNLOADS_DIR, exist_ok=True)
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

AUDIO_BITRATES = {"128", "192", "320"}
PLAYLIST_ITEMS_RE = re.compile(r"\d+(?:-\d+)?(?:,\d+(?:-\d+)?)*")

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


def _cookie_options() -> dict:
    """Chỉ đọc cookies.txt khi file đã tồn tại.

    yt-dlp luôn ghi lại cookiefile khi đóng (kể cả file chưa có), nên nếu
    truyền 'cookiefile' vô điều kiện thì nó sẽ tự tạo cookies.txt.
    """
    if os.path.isfile(COOKIES_FILE):
        return {'cookiefile': COOKIES_FILE}
    return {}


def _normalize_playlist_items(raw) -> str:
    """Chuẩn hoá chuỗi chọn mục playlist, ví dụ "1-5, 10" -> "1-5,10"."""
    items = re.sub(r"\s+", "", str(raw or ""))
    if items and not PLAYLIST_ITEMS_RE.fullmatch(items):
        raise ValueError("Khoảng video không hợp lệ. Ví dụ hợp lệ: 1-5, 10, 15")
    return items


def _snapshot_downloads() -> dict[str, tuple[int, int]]:
    """Chụp trạng thái thư mục downloads để phát hiện file mới sau khi tải."""
    snapshot = {}
    for root, _dirs, files in os.walk(DOWNLOADS_DIR):
        for name in files:
            path = os.path.join(root, name)
            try:
                stat = os.stat(path)
            except OSError:
                continue
            snapshot[path] = (stat.st_mtime_ns, stat.st_size)
    return snapshot


_TEMP_SUFFIXES = (".part", ".ytdl", ".temp", ".tmp")


def _is_download_output(path: str) -> bool:
    name = os.path.basename(path).lower()
    return not name.startswith(".") and not name.endswith(_TEMP_SUFFIXES)


def _iter_info_entries(info):
    """Duyệt đệ quy video đơn hoặc các mục trong playlist."""
    if not isinstance(info, dict):
        return

    entries = info.get("entries")
    if entries:
        for entry in entries:
            if isinstance(entry, (tuple, list)) and len(entry) == 2:
                entry = entry[1]
            yield from _iter_info_entries(entry)
        return

    yield info


def _is_inside_downloads(path: str) -> bool:
    """Chỉ cho phép truy cập file nằm trong thư mục downloads."""
    root = os.path.normcase(os.path.realpath(DOWNLOADS_DIR))
    target = os.path.normcase(os.path.realpath(path))
    try:
        return os.path.commonpath([root, target]) == root
    except ValueError:
        return False


def _remove_downloaded_file(path: str) -> None:
    """Xóa file sau khi trình duyệt đã nhận xong."""
    if not _is_inside_downloads(path):
        return
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    except OSError:
        # File đang bị khóa hoặc đã bị xóa bởi request khác.
        pass


def _format_size(fmt: dict) -> float | None:
    """Dung lượng ước tính của một format (byte)."""
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
def download_task(
    url: str,
    format_id: str,
    websocket: WebSocket,
    loop: asyncio.AbstractEventLoop,
    subtitles: bool = False,
    audio_bitrate: str = "192",
    playlist_items: str = "",
):
    tracker = ProgressTracker()
    final_paths: set[str] = set()

    def send(payload: dict):
        asyncio.run_coroutine_threadsafe(websocket.send_json(payload), loop)

    def remember(path):
        if path:
            final_paths.add(os.path.abspath(str(path)))

    def progress_hook(d):
        status = d.get("status")
        if status == "finished":
            # File của luồng video/audio hiện tại (trước khi ghép hoặc chuyển MP3).
            remember(d.get("filename"))
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

    def postprocessor_hook(d):
        # Sau khi ghép/chuyển MP3, info_dict["filepath"] là file cuối cùng.
        if d.get("status") != "finished":
            return
        info_dict = d.get("info_dict") or {}
        remember(d.get("filename") or info_dict.get("filepath"))

    common_opts = {
        'outtmpl': os.path.join(DOWNLOADS_DIR, '%(title)s.%(ext)s'),
        'progress_hooks': [progress_hook],
        'postprocessor_hooks': [postprocessor_hook],
        'quiet': True,
        'color': 'no_color'
    }

    if subtitles:
        common_opts.update({
            'writesubtitles': True,
            'writeautomaticsub': True,
            'subtitleslangs': ['vi', 'en'],
            'subtitlesformat': 'srt/vtt/best',
        })

    if playlist_items:
        common_opts['playlist_items'] = playlist_items

    #cấu hình cho mp3 và video ( người dùng chọn )
    if format_id == 'mp3':
        ydl_opts = {
            **common_opts,
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': audio_bitrate,
            }],
        }
    else:
        if not format_id or format_id == 'best':
            format_selector = 'bestvideo+bestaudio/best'
        else:
            # Format video-only cần ghép thêm audio; fallback cho format đã có sẵn audio
            format_selector = f"{format_id}+bestaudio/{format_id}/best"
        ydl_opts = {
            **common_opts,
            'format': format_selector,
        }

    before_download = _snapshot_downloads()

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Lấy thông tin trước để biết có bao nhiêu file (video + audio)
            # và dung lượng từng file, phục vụ việc gộp tiến trình.
            info = ydl.extract_info(url, download=False)
            if not info:
                raise RuntimeError("Không lấy được thông tin video")
            tracker.prepare(info)
            ydl.process_ie_result(info, download=True)

            # Đường dẫn cuối cùng có thể đã được postprocessor cập nhật.
            for entry in _iter_info_entries(info):
                remember(entry.get("filepath"))
                for request in entry.get("requested_downloads") or []:
                    if isinstance(request, dict):
                        remember(request.get("filepath"))

                try:
                    prepared_path = str(ydl.prepare_filename(entry) or "")
                except Exception:
                    prepared_path = ""

                if prepared_path:
                    remember(prepared_path)
                    # File MP3 cuối cùng (kể cả khi yt-dlp bỏ qua vì file đã tồn tại).
                    if format_id == 'mp3':
                        remember(f"{os.path.splitext(prepared_path)[0]}.mp3")

                # Phụ đề được ghi cạnh file media, ví dụ: "Tên video.vi.vtt".
                media_path = entry.get("filepath") or prepared_path
                base_path = os.path.splitext(str(media_path))[0] if media_path else ""
                if base_path:
                    for lang, subtitle in (entry.get("requested_subtitles") or {}).items():
                        if isinstance(subtitle, dict):
                            remember(f"{base_path}.{lang}.{subtitle.get('ext') or 'vtt'}")
    except Exception as e:
        send({"status": "error", "message": str(e)})
        return

    # Phụ đề (và file cũ bị ghi đè) có thể không phát progress hook,
    # nên đối chiếu thư mục trước/sau để bổ sung.
    after_download = _snapshot_downloads()
    for path, stamp in after_download.items():
        if before_download.get(path) != stamp:
            remember(path)

    files = []
    for path in sorted(final_paths):
        if not os.path.isfile(path) or not _is_inside_downloads(path) or not _is_download_output(path):
            continue
        try:
            size = os.path.getsize(path)
        except OSError:
            continue
        files.append({
            "name": os.path.basename(path),
            "path": os.path.relpath(path, DOWNLOADS_DIR).replace(os.sep, "/"),
            "size": size,
        })

    # Chỉ báo hoàn tất sau khi tất cả luồng (và bước ghép) đã xong.
    send({"status": "finished", "files": files})

# api routes 
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(request, "index.html")

def _iter_video_infos(info):
    """Duyệt video đơn hoặc từng video trong playlist."""
    if not isinstance(info, dict):
        return

    entries = info.get("entries")
    if entries:
        for entry in entries:
            if isinstance(entry, (tuple, list)) and len(entry) == 2:
                entry = entry[1]
            yield from _iter_video_infos(entry)
        return

    if info.get("formats"):
        yield info


def pick_video_formats(info: dict) -> list[dict]:
    """Gom format video theo độ phân giải, ưu tiên fps cao rồi tới MP4/H.264.

    Playlist không có "formats" ở cấp cao nhất, nên duyệt các video bên trong
    để gom đủ độ phân giải (hợp của tất cả mục) thay vì chỉ hiện "best"/MP3.
    """
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

    for video in _iter_video_infos(info):
        for f in video.get("formats", []):
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
        ydl_opts = {'quiet': True, **_cookie_options()}
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
    url = (data.get("url") or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="Chưa có URL")

    format_id = data.get("format_id") or "best"

    audio_bitrate = str(data.get("audio_bitrate") or "192")
    if audio_bitrate not in AUDIO_BITRATES:
        audio_bitrate = "192"

    try:
        playlist_items = _normalize_playlist_items(data.get("playlist_items") or "")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    subtitles = bool(data.get("subtitles"))

    loop = asyncio.get_running_loop()
    websocket = manager.active_connections[-1] if manager.active_connections else None

    if websocket:
        background_tasks.add_task(
            asyncio.to_thread,
            download_task, url, format_id, websocket, loop,
            subtitles, audio_bitrate, playlist_items,
        )

    return {"message": "Đang tải..."}


@app.get("/api/file")
async def download_file(path: str, background_tasks: BackgroundTasks):
    """Gửi file đã tải về trình duyệt; chỉ cho phép file trong thư mục downloads.

    Sau khi response được gửi xong, BackgroundTasks sẽ xóa file khỏi server.
    """
    relative = (path or "").replace("\\", "/").lstrip("/")
    candidate = os.path.abspath(os.path.join(DOWNLOADS_DIR, relative))

    if (
        not relative
        or not _is_inside_downloads(candidate)
        or not os.path.isfile(candidate)
        or not _is_download_output(candidate)
    ):
        raise HTTPException(status_code=404, detail="Không tìm thấy file")

    background_tasks.add_task(_remove_downloaded_file, candidate)
    return FileResponse(candidate, filename=os.path.basename(candidate))

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
