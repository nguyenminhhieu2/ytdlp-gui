import yt_dlp

def my_hook(d):
    if d['status'] == 'downloading':
        percent = d.get('_percent_str', '0%').strip()
        speed = d.get('_speed_str', 'N/A').strip()
        print(f"Đang tải: {percent} | Tốc độ: {speed}")

url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
ydl_opts = {
    'outtmpl': 'downloads/%(title)s.%(ext)s',
    'progress_hooks': [my_hook],
    # Sửa dòng 'format' ở đây:
    'format': 'bestvideo+bestaudio/best', # Ưu tiên tải video+âm thanh tốt nhất, nếu không có thì lấy 'best'
}

with yt_dlp.YoutubeDL(ydl_opts) as ydl:
    ydl.download([url])