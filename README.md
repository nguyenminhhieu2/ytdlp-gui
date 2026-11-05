# Tải Video Đa Nền Tảng

Ứng dụng web tải video/âm thanh từ YouTube, TikTok, Facebook, Playlist và nhiều nền tảng khác. Backend dùng **FastAPI + yt-dlp**, frontend dùng **HTML + Tailwind CSS + JavaScript**, tiến trình tải được cập nhật theo thời gian thực qua **WebSocket**.

## Tính năng

- Dán liên kết video để tự động lấy tiêu đề và danh sách chất lượng khả dụng.
- Chọn chất lượng video (từ 144p đến độ phân giải cao nhất) hoặc chỉ tải âm thanh MP3 (192 kbps).
- Hiển thị tiến trình tải (phần trăm, tốc độ) theo thời gian thực qua WebSocket.
- Gộp tiến trình các luồng video + audio (và các mục trong Playlist) thành một giá trị 0–100%; thanh % chỉ tăng, không giật lùi khi chuyển luồng.
- Chỉ báo "Hoàn tất" sau khi mọi luồng đã tải và ghép xong; nút tải bị khoá trong suốt quá trình.
- Tự động kết nối lại WebSocket khi mất kết nối (backoff lũy tiến, tối đa 10 giây).
- Thông báo lỗi rõ ràng trên giao diện; tự loại bỏ mã màu ANSI từ yt-dlp.
- Hỗ trợ video đơn lẻ và Playlist nhiều mục.

## Công nghệ sử dụng

| Thành phần | Công nghệ |
|---|---|
| Backend | FastAPI, Uvicorn, Python 3.10+ |
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
- **FFmpeg** — cần thiết để:
  - Ghép luồng video và audio chất lượng cao (`bestvideo+bestaudio`).
  - Chuyển audio sang MP3.

  `requirements.txt` có cài package Python `ffmpeg`, nhưng yt-dlp vẫn cần **lệnh `ffmpeg` có trong `PATH`**:
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

> Frontend đang cấu hình cứng WebSocket tới `ws://127.0.0.1:8000/ws` (biến `WS_URL` trong `templates/index.html`). Nếu đổi host/port, cần cập nhật biến này hoặc chạy đúng cổng `8000`.

## Hướng dẫn sử dụng

1. Dán liên kết video vào ô nhập (YouTube, TikTok, Facebook, Playlist...).
2. Chờ ứng dụng lấy thông tin — danh sách chất lượng sẽ hiện ra.
3. Chọn chất lượng mong muốn (hoặc **Chỉ tải Âm thanh (MP3)**).
4. Nhấn **Tải Xuống** và theo dõi tiến trình.
5. File hoàn tất được lưu trong thư mục `downloads/`.

## Cách hoạt động

1. Khi người dùng dán URL, frontend gọi `POST /api/info` để lấy danh sách chất lượng.
2. Khi nhấn **Tải Xuống**, frontend gọi `POST /api/download`; backend chạy tác vụ tải trong nền và gửi tiến trình/kết quả qua WebSocket.
3. Với chất lượng cao, yt-dlp tải **video-only và audio thành hai file riêng** rồi ghép bằng FFmpeg. Backend dùng `ProgressTracker` để theo dõi từng file, tính trọng số theo dung lượng ước tính và cộng dồn thành một phần trăm tổng duy nhất.
4. yt-dlp được cấu hình tắt màu (`color: no_color`); frontend lọc thêm mã ANSI trước khi hiển thị để tránh ký tự lạ.
5. Bản tin `finished` chỉ được gửi **sau khi** toàn bộ quá trình tải và ghép hoàn tất.

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
Bắt đầu tải trong nền và trả về ngay `{ "message": "Đang tải..." }`.

```json
{
  "url": "https://www.youtube.com/watch?v=...",
  "format_id": "best"
}
```

### `WebSocket /ws`
Client kết nối để nhận tiến trình. Server gửi các bản tin:

```json
{ "status": "downloading", "percent": "42.3%", "speed": "1.25MiB/s" }
{ "status": "finished" }
{ "status": "error", "message": "mô tả lỗi" }
```

- `percent` là tiến trình **tổng** của tất cả file trong lượt tải (video, audio và các mục trong Playlist), không phải % riêng của từng luồng.
- `finished` chỉ được gửi **một lần**, sau khi tải và ghép xong.
- Khi mất kết nối giữa chừng, frontend hiển thị lỗi và tự kết nối lại.

## Cookies (nội dung cần đăng nhập / giới hạn tuổi)

Ứng dụng đọc file `cookies.txt` (định dạng Netscape) nếu tồn tại, dùng để tải video yêu cầu đăng nhập hoặc bị giới hạn độ tuổi.

- `cookies.txt` nằm trong `.gitignore` — **không commit** vì chứa thông tin đăng nhập.
- Cách tạo: dùng extension trình duyệt xuất cookie (ví dụ *Get cookies.txt LOCALLY*), xuất cho đúng domain và lưu thành `cookies.txt` ở thư mục gốc dự án.
- Nếu không cần, có thể bỏ qua; yt-dlp vẫn tải được nội dung công khai. Khi file không tồn tại, yt-dlp có thể cảnh báo nhưng không dừng tải.

## Xử lý sự cố

- **Không có tiến trình / không tải được:** kiểm tra cổng `8000` có đang chạy và frontend đã kết nối WebSocket chưa (chấm trạng thái màu xanh). Server chỉ nhận tác vụ khi có kết nối WebSocket.
- **Lỗi ghép video hoặc chuyển MP3:** kiểm tra `ffmpeg -version` và đảm bảo FFmpeg có trong `PATH`.
- **Video cần đăng nhập / bị giới hạn tuổi:** cập nhật `cookies.txt`.
- **Log / thông báo lỗi có mã màu:** đã được xử lý ở cả backend (`color: no_color`) và frontend (lọc ANSI).

## Lưu ý

- Dự án phục vụ mục đích học tập. Chỉ tải nội dung bạn sở hữu hoặc được phép tải về; tuân thủ điều khoản dịch vụ của từng nền tảng và quy định bản quyền.
- Server chỉ ghi nhận **WebSocket gần nhất** đang kết nối (`manager.active_connections[-1]`), phù hợp cho sử dụng cá nhân một phiên. Nếu triển khai nhiều người dùng đồng thời, cần ánh xạ WebSocket theo từng phiên/tác vụ.
- File tải về nằm trong `downloads/` và không được đẩy lên Git.
