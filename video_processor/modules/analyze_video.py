import requests
import time
import subprocess
import uuid
import shutil
from pathlib import Path
import logging
import yt_dlp  # Добавлен для скачивания видео

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# OpenAI API Key (должен быть настроен через переменные окружения)
OPENAI_API_KEY = ""


def download_video(url: str, output_dir: Path) -> Path:
    """Скачивает видео с Instagram через yt-dlp."""
    output_dir.mkdir(parents=True, exist_ok=True)
    video_path = output_dir / "downloaded_video.mp4"
    
    ydl_opts = {
        "outtmpl": str(video_path),
        "format": "best",
        "quiet": True,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        return video_path
    except Exception as e:
        logger.error(f"Ошибка при скачивании видео: {e}")
        raise


def extract_frames(video_path: Path, frames_dir: Path, fps: float):
    """Извлекает кадры из видео."""
    try:
        frames_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run([
            "ffmpeg", "-i", str(video_path), "-vf", f"fps=1/{fps}", f"{frames_dir}/frame_%04d.png"
        ], check=True)
        video_path.unlink()
    except subprocess.CalledProcessError as e:
        logger.error(f"Ошибка при извлечении кадров: {e}")
        raise


def analyze_image(image_path: Path) -> str:
    """Анализирует изображение с помощью OpenAI."""
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": "Детально опиши, что происходит на изображении."},
            {"role": "user", "content": [{"type": "image_url", "image_url": {"url": f"file://{image_path}"}}]}
        ],
        "max_tokens": 300
    }
    try:
        response = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
    except requests.RequestException as e:
        logger.error(f"Ошибка при анализе изображения: {e}")
        return "Ошибка анализа изображения."


def analyze_video(url: str, fps: float):
    """Обрабатывает видео, извлекает кадры и анализирует их."""
    task_id = str(uuid.uuid4())
    video_dir = Path("videos") / task_id
    frames_dir = Path("frames") / task_id
    
    try:
        video_path = download_video(url, video_dir)
        extract_frames(video_path, frames_dir, fps)

        frame_files = sorted(frames_dir.glob("*.png"))
        analysis_results = []
        
        for idx, frame in enumerate(frame_files):
            description = analyze_image(frame)
            analysis_results.append(f"Кадр {idx+1}: {description}")
            time.sleep(1)
        
        summary_payload = {
            "model": "gpt-4o",
            "messages": [
                {"role": "system", "content": "Проанализируй кадры и составь описание видео."},
                {"role": "user", "content": "\n".join(analysis_results)}
            ],
            "max_tokens": 1200
        }

        response = requests.post("https://api.openai.com/v1/chat/completions", headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}, json=summary_payload)
        response.raise_for_status()
        video_summary = response.json()["choices"][0]["message"]["content"]
        
        return {"summary": video_summary, "analysis_results": analysis_results}
    except Exception as e:
        logger.error(f"Ошибка в процессе анализа видео: {e}")
        return {"error": str(e)}


if __name__ == "__main__":
    video_url = input("Введите ссылку на видео: ")
    fps = float(input("Введите частоту кадров (в секундах): "))
    result = analyze_video(video_url, fps)
    print("\nРезультаты анализа:")
    print(result)
