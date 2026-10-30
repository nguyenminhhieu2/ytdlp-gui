import yt_dlp

url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
    info = ydl.extract_info(url, download=False)
    print("Tiêu đề:", info.get('title'))
    print("Thời lượng:", info.get('duration'), "giây")
    
    # In ra các định dạng có sẵn
    for f in info.get('formats', []):
        if f.get('vcodec') != 'none':
            print(f"ID: {f['format_id']} | Chất lượng: {f.get('format_note', 'N/A')}")
            