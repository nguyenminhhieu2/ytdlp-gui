# Tải Video Đa Nền Tảng

Ứng dụng web tải video/âm thanh từ YouTube, TikTok, Facebook, Playlist và nhiều nền tảng khác. Backend dùng **FastAPI + yt-dlp**, frontend dùng **HTML + Tailwind CSS + JavaScript**, tiến trình tải được cập nhật theo thời gian thực qua **WebSocket**.

## Tính năng

- Dán liên kết video để tự động lấy tiêu đề và danh sách chất lượng khả dụng.
- Chọn chất lượng video (từ 144p đến độ phân giải cao nhất) hoặc chỉ tải âm thanh MP3 với bitrate **128 / 192 / 320 kbps**.
- **Tải kèm phụ đề** tiếng Việt và tiếng Anh (file `.srt` hoặc `.vtt` đi kèm video).
- **Chọn khoảng mục trong Playlist** cần tải, ví dụ `1-5, 10, 15`; để trống để tải toàn bộ.
- Hiển thị tiến trình tải (phần trăm, tốc độ) theo thời gian thực qua WebSocket.
- Gộp tiến trình các luồng video + audio (và các mục trong Playlist) thành một giá trị 0–100%; thanh % chỉ tăng, không giật lùi khi chuyển luồng.
- Chỉ báo "Hoàn tất" sau khi mọi luồng đã tải và ghép xong; nút tải bị khoá trong suốt quá trình.
- Tự động kết nối lại WebSocket khi mất kết nối (backoff lũy tiến, tối đa 10 giây).
- Hỗ trợ video đơn lẻ và Playlist nhiều mục.

## Công nghệ sử dụng

| Thành phần | Công nghệ |
|---|---|
| Backend | FastAPI, Uvicorn, Python 3.14+ |
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
└── README.md
```

## Yêu cầu hệ thống

- **Python 3.14 trở lên** (khuyến nghị dùng bản mới nhất).
- **FFmpeg — bắt buộc**,cần cài độc lập và đảm bảo lệnh `ffmpeg` có trong `PATH`.

  Hướng dẫn cài:
  - **Windows:** tải tại [ffmpeg.org](https://ffmpeg.org/download.html) (hoặc [gyan.dev](https://www.gyan.dev/ffmpeg/builds/)), giải nén và thêm thư mục `bin` vào `PATH`.
  - **macOS:** `brew install ffmpeg`.
  - **Linux:** `sudo apt install ffmpeg` (Debian/Ubuntu) hoặc `sudo dnf install ffmpeg` (Fedora).
  - Kiểm tra: `ffmpeg -version` (và `ffprobe -version`).

## Cài đặt

> Trước khi cài, đảm bảo máy đã có **Python 3.14+** và **FFmpeg** trong `PATH` (xem [Yêu cầu hệ thống](#yêu-cầu-hệ-thống)). Nếu thiếu FFmpeg, việc ghép video và chuyển MP3 sẽ thất bại.

```bash
# 1. Kiểm tra phiên bản Python (cần 3.14 trở lên)
python --version
# Windows: nếu có nhiều bản Python, dùng: py -3.14 --version

# 2. Tạo và kích hoạt môi trường ảo (khuyến nghị)
python -m venv venv

# Windows (PowerShell)
venv\Scripts\Activate.ps1

# Windows (CMD)
venv\Scripts\activate.bat

# macOS / Linux
source venv/bin/activate

# 3. Cài đặt thư viện Python
pip install -r requirements.txt

# 4. Kiểm tra FFmpeg đã có trong PATH
ffmpeg -version
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
3. Chọn chất lượng mong muốn (hoặc **Chỉ tải Âm thanh (MP3)**; khi chọn MP3 sẽ hiện thêm ô chọn bitrate).
4. (Tùy chọn) Tích **Tải kèm phụ đề** và/hoặc nhập **Khoảng video trong Playlist** (ví dụ `1-5, 10, 15`).
5. Nhấn **Tải Xuống** và theo dõi tiến trình.
6. Khi thanh tiến trình đạt 100%, bấm **Lưu về máy** cạnh từng file để trình duyệt tải file từ server xuống ổ cứng. Sau khi tải xong, file đó được tự động xóa khỏi `downloads/` trên server; các file chưa bấm **Lưu về máy** vẫn còn nguyên.

## Cách hoạt động

1. Khi người dùng dán URL, frontend gọi `POST /api/info` để lấy danh sách chất lượng.
2. Khi nhấn **Tải Xuống**, frontend gọi `POST /api/download`; backend chạy tác vụ tải trong nền và gửi tiến trình/kết quả qua WebSocket.
3. Với chất lượng cao, yt-dlp tải **video-only và audio thành hai file riêng** rồi ghép bằng FFmpeg. Backend dùng `ProgressTracker` để theo dõi từng file, tính trọng số theo dung lượng ước tính và cộng dồn thành một phần trăm tổng duy nhất.
4. yt-dlp được cấu hình tắt màu (`color: no_color`); frontend lọc thêm mã ANSI trước khi hiển thị để tránh ký tự lạ.
5. Bản tin `finished` chỉ được gửi **sau khi** toàn bộ quá trình tải và ghép hoàn tất. Backend đối chiếu thư mục `downloads/` trước và sau khi tải (kết hợp đường dẫn do yt-dlp báo qua hook) để liệt kê cả file video/MP3 lẫn phụ đề.
6. Người dùng bấm **Lưu về máy**; trình duyệt gọi `GET /api/file` và server trả file dưới dạng đính kèm. Khi response đã gửi xong, một `BackgroundTasks` xóa file tương ứng khỏi `downloads/`.

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
  "format_id": "best",
  "subtitles": true,
  "audio_bitrate": "320",
  "playlist_items": "1-5, 10, 15"
}
```

| Trường | Mô tả |
|---|---|
| `format_id` | `best`, mã format video, hoặc `mp3`. |
| `subtitles` | `true` để tải kèm phụ đề `vi`, `en` (`.srt`/`.vtt`). |
| `audio_bitrate` | `128`, `192` hoặc `320` kbps; chỉ dùng khi `format_id = "mp3"`. |
| `playlist_items` | Khoảng mục playlist, ví dụ `1-5, 10, 15`. Để trống để tải toàn bộ. |

Trả về `400` nếu URL trống hoặc khoảng video không hợp lệ.

### `GET /api/file?path=...`
Gửi file đã tải về trình duyệt dưới dạng đính kèm (`Content-Disposition: attachment`), phục vụ nút **Lưu về máy**.

- Chỉ chấp nhận file đầu ra nằm trong thư mục `downloads/`; đường dẫn ngoài thư mục này hoặc file tạm (`.part`, `.ytdl`, `.temp`, `.tmp`) trả về `404`.
- Sau khi response được gửi xong, `BackgroundTasks` tự động xóa file khỏi server. File chỉ bị xóa khi được tải qua endpoint này.

### `WebSocket /ws`
Client kết nối để nhận tiến trình. Server gửi các bản tin:

```json
{ "status": "downloading", "percent": "42.3%", "speed": "1.25MiB/s" }
{
  "status": "finished",
  "files": [
    { "name": "Tên video.mp4", "path": "Tên video.mp4", "size": 123456789 }
  ]
}
{ "status": "error", "message": "mô tả lỗi" }
```

- `percent` là tiến trình **tổng** của tất cả file trong lượt tải (video, audio và các mục trong Playlist), không phải % riêng của từng luồng.
- `finished` chỉ được gửi **một lần**, sau khi tải và ghép xong. `files` liệt kê mọi file đầu ra (video/MP3, phụ đề) để frontend tạo nút **Lưu về máy**.
- Khi mất kết nối giữa chừng, frontend hiển thị lỗi và tự kết nối lại.

## Cookies (nội dung cần đăng nhập / giới hạn tuổi)

Ứng dụng chỉ đọc file `cookies.txt` (định dạng Netscape) khi file này **đã tồn tại**; ứng dụng **không tự tạo** `cookies.txt`. File được dùng khi lấy thông tin video yêu cầu đăng nhập hoặc bị giới hạn độ tuổi.

- `cookies.txt` nằm trong `.gitignore` — **không commit** vì chứa thông tin đăng nhập.
- Cách tạo: dùng extension trình duyệt xuất cookie (ví dụ *Get cookies.txt LOCALLY*), xuất cho đúng domain và lưu thành `cookies.txt` ở thư mục gốc dự án.
- Nếu không cần, có thể bỏ qua; ứng dụng vẫn tải được nội dung công khai và sẽ không sinh ra file `cookies.txt`.

## Xử lý sự cố

- **Không có tiến trình / không tải được:** kiểm tra cổng `8000` có đang chạy và frontend đã kết nối WebSocket chưa (chấm trạng thái màu xanh). Server chỉ nhận tác vụ khi có kết nối WebSocket.
- **Lỗi ghép video hoặc chuyển MP3:** kiểm tra `ffmpeg -version` và đảm bảo FFmpeg có trong `PATH`.
- **Video cần đăng nhập / bị giới hạn tuổi:** cập nhật `cookies.txt`.
- **Log / thông báo lỗi có mã màu:** đã được xử lý ở cả backend (`color: no_color`) và frontend (lọc ANSI).

## Lưu ý

- Dự án phục vụ mục đích học tập. Chỉ tải nội dung bạn sở hữu hoặc được phép tải về; tuân thủ điều khoản dịch vụ của từng nền tảng và quy định bản quyền.
- Server chỉ ghi nhận **WebSocket gần nhất** đang kết nối (`manager.active_connections[-1]`), phù hợp cho sử dụng cá nhân một phiên. Nếu triển khai nhiều người dùng đồng thời, cần ánh xạ WebSocket theo từng phiên/tác vụ.
- File tải về nằm trong `downloads/` và không được đẩy lên Git.
