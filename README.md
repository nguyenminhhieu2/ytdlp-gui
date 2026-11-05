# Tải Video Đa Nền Tảng

Ứng dụng web tải video/âm thanh từ YouTube, TikTok, Facebook, Playlist và nhiều nền tảng khác, được xây dựng bằng **FastAPI + yt-dlp**, hiển thị tiến trình tải theo thời gian thực qua **WebSocket**.

## Tính năng

- Dán liên kết video và tự động lấy danh sách chất lượng khả dụng.
- Chọn chất lượng video (từ 144p đến độ phân giải cao nhất) hoặc chỉ tải âm thanh dạng MP3 (192 kbps).
- Hiển thị tiến trình tải (phần trăm, tốc độ) theo thời gian thực qua WebSocket.
- Tự động kết nối lại WebSocket khi mất kết nối (backoff lũy tiến, tối đa 10 giây).
- Xử lý lỗi rõ ràng trên giao diện: URL không hợp lệ, lỗi máy chủ, lỗi yt-dlp.
- Giao diện tối, responsive, có hỗ trợ `prefers-reduced-motion` và các thuộc tính accessibility (`aria-live`, `aria-busy`...).

## Công nghệ sử dụng

| Thành phần | Công nghệ |
|---|---|
| Backend | FastAPI, Uvicorn, Python 3.10 |
| Tải video | yt-dlp, FFmpeg (ghép video + audio, chuyển sang MP3) |
| Giao tiếp realtime | WebSocket (`/ws`) |
| Frontend | HTML + Tailwind CSS (CDN) + JavaScript thuần |
| Template | Jinja2 |

## Cấu trúc dự án

```
doan-videodownloader/
├── main.py              # FastAPI app: routes, WebSocket, tác vụ tải ngầm
├── requirements.txt     # Danh sách thư viện Python
├── templates/
│   └── index.html       # Giao diện người dùng + logic frontend
├── downloads/           # Nơi lưu file tải về (tự tạo khi chạy)
├── cookies.txt          # Cookie tùy chọn cho nội dung cần đăng nhập
└── README.md
```

## Yêu cầu hệ thống

- **Python 3.10+**
- **FFmpeg** — bắt buộc để:
  - Chuyển audio sang MP3.
  - Ghép luồng video và audio chất lượng cao (`bestvideo+bestaudio`).

  Cài FFmpeg và đảm bảo lệnh `ffmpeg` có trong `PATH`:
  - Windows: tải tại [ffmpeg.org](https://ffmpeg.org/download.html), giải nén và thêm thư mục `bin` vào `PATH`.
  - Kiểm tra: `ffmpeg -version`

## Cài đặt

```bash
# 1. Tạo và kích hoạt môi trường ảo (khuyến nghị)
python -m venv venv

# Windows (PowerShell)
venv\Scripts\Activate.ps1

# Windows (CMD)
venv\Scripts\activate.bat

# macOS / Linux
source venv/bin/activate

# 2. Cài đặt thư viện
pip install -r requirements.txt
```

## Chạy ứng dụng

```bash
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Sau đó mở trình duyệt tại: **http://127.0.0.1:8000**

> Lưu ý: frontend đang cấu hình cứng WebSocket tới `ws://127.0.0.1:8000/ws` (trong `templates/index.html`). Nếu đổi host/port, cần cập nhật biến `WS_URL` hoặc chạy đúng cổng `8000`.

## Hướng dẫn sử dụng

1. Dán liên kết video vào ô nhập (ví dụ YouTube, TikTok, Facebook, Playlist).
2. Chờ ứng dụng lấy thông tin — danh sách chất lượng sẽ hiện ra.
3. Chọn chất lượng mong muốn (hoặc **Chỉ tải Âm thanh (MP3)**).
4. Nhấn **Tải Xuống** và theo dõi tiến trình.
5. File hoàn tất được lưu trong thư mục `downloads/`.

## API

### `GET /`
Trả về giao diện chính (`templates/index.html`).

### `POST /api/info`
Lấy tiêu đề và danh sách chất lượng của video.

```json
// Request
{ "url": "https://www.youtube.com/watch?v=..." }

// Response
{
  "title": "Tên video",
  "formats": [
    { "id": "best", "label": "Chất lượng tốt nhất (tự động)" },
    { "id": "137", "label": "Video 1080p (MP4)" },
    { "id": "mp3", "label": "Chỉ tải Âm thanh (MP3)" }
  ]
}
```

Khi có lỗi, API trả về `{ "error": "mô tả lỗi" }`.

### `POST /api/download`
Bắt đầu tải video trong nền. Kết quả và tiến trình được đẩy về client qua WebSocket.

```json
{
  "url": "https://www.youtube.com/watch?v=...",
  "format_id": "best"
}
```

### `WebSocket /ws`
Client kết nối để nhận tiến trình tải. Các bản tin từ server:

```json
{ "status": "downloading", "percent": "42.3%", "speed": "1.25MiB/s" }
{ "status": "finished" }
{ "status": "error", "message": "mô tả lỗi" }
```

## Cookies (nội dung cần đăng nhập / giới hạn tuổi)

Ứng dụng đọc file `cookies.txt` (định dạng Netscape) nếu tồn tại, dùng để tải các video yêu cầu đăng nhập hoặc bị giới hạn độ tuổi.

- `cookies.txt` đã nằm trong `.gitignore` — **không commit file này** vì chứa thông tin đăng nhập.
- Để tạo cookie: dùng extension trình duyệt xuất cookie (ví dụ *Get cookies.txt LOCALLY*), xuất cho đúng domain và lưu thành `cookies.txt` ở thư mục gốc dự án.
- Nếu không cần, có thể bỏ qua; yt-dlp vẫn tải được nội dung công khai. Khi file không tồn tại, yt-dlp có thể cảnh báo nhưng không dừng tải.

## Lưu ý

- Dự án phục vụ mục đích học tập. Chỉ tải nội dung bạn sở hữu hoặc được phép tải về; tuân thủ điều khoản dịch vụ của từng nền tảng và quy định bản quyền.
- Hiện tại server chỉ ghi nhận **WebSocket gần nhất** đang kết nối (`manager.active_connections[-1]`), phù hợp cho sử dụng cá nhân một phiên. Nếu triển khai nhiều người dùng đồng thời, cần ánh xạ WebSocket theo từng phiên/tác vụ.
- Các file tải về nằm trong `downloads/` và không được đẩy lên Git.
