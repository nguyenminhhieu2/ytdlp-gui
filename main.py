from fastapi import BackgroundTasks
import asyncio

def download_task(url: str):
    # Tạm thời để trống hoặc gọi lại code của Ngày 3
    # Hàm này sẽ chạy ngầm trong 1 thread riêng
    pass

@app.post("/api/download")
async def start_download(request: Request, background_tasks: BackgroundTasks):
    data = await request.json()
    url = data.get("url")
    
    # Đẩy tác vụ vào background, dùng asyncio.to_thread để không block server
    background_tasks.add_task(asyncio.to_thread, download_task, url)
    
    return {"message": "Đã bắt đầu tải ngầm!"}