import requests
import subprocess
import uuid
import shutil
from pathlib import Path
import logging
import yt_dlp
from dotenv import load_dotenv
import os
import git
import time
import pytesseract
from PIL import Image

# Загрузка переменных окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# OpenAI API Key
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise ValueError("❌ Ошибка: API-ключ OpenAI не найден! Проверьте .env файл.")

# GitHub данные
GITHUB_REPO = "https://github.com/juliakriv0137/video-frames.git"
GITHUB_LOCAL_PATH = Path("video-frames")
GITHUB_RAW_URL = "https://raw.githubusercontent.com/juliakriv0137/video-frames/main/video-frames/frames/"

def check_dependencies():
    """Проверяет, установлены ли yt-dlp, ffmpeg и Tesseract OCR"""
    try:
        subprocess.run(["yt-dlp", "--version"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        subprocess.run(["ffmpeg", "-version"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError:
        raise RuntimeError("❌ Необходимо установить yt-dlp и ffmpeg!")

    if not shutil.which("tesseract"):
        raise RuntimeError("❌ Tesseract OCR не найден! Установите его вручную.")

def download_video(url: str, output_dir: Path) -> Path:
    """Скачивает видео с Instagram через yt-dlp."""
    output_dir.mkdir(parents=True, exist_ok=True)
    video_path = output_dir / "downloaded_video.mp4"

    ydl_opts = {
        "outtmpl": str(video_path),
        "format": "best",
        "quiet": False,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        return video_path
    except Exception as e:
        logger.error(f"Ошибка при скачивании видео: {e}")
        raise

def get_video_duration(video_path: Path):
    """Получает длительность видео."""
    result = subprocess.run([
        "ffmpeg", "-i", str(video_path), "-hide_banner", "-f", "null", "-"
    ], stderr=subprocess.PIPE, text=True)
    
    for line in result.stderr.split("\n"):
        if "Duration" in line:
            time_str = line.split(",")[0].split(" ")[-1]
            minutes, seconds = map(float, time_str.split(":")[1:])
            return int(minutes), round(seconds)
    return None, None

def extract_frames(video_path: Path, frames_dir: Path, fps: float):
    """Извлекает кадры из видео."""
    try:
        frames_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run([
            "ffmpeg", "-i", str(video_path), "-vf", f"fps=1/{fps}", f"{frames_dir}/frame_%04d.png"
        ], check=True)
        video_path.unlink()  # Удаление видео после обработки
    except subprocess.CalledProcessError as e:
        logger.error(f"Ошибка при извлечении кадров: {e}")
        raise

def upload_frames_to_github(frames_dir: Path):
    """Загружает кадры на GitHub и возвращает ссылки."""
    if not GITHUB_LOCAL_PATH.exists():
        git.Repo.clone_from(GITHUB_REPO, GITHUB_LOCAL_PATH)

    repo = git.Repo(GITHUB_LOCAL_PATH)

    # Создаем структуру директорий
    destination = GITHUB_LOCAL_PATH / "video-frames" / "frames" / frames_dir.name
    shutil.copytree(frames_dir, destination, dirs_exist_ok=True)

    repo.git.add(A=True)
    repo.index.commit(f"Добавлены кадры {frames_dir.name}")
    
    try:
        origin = repo.remote(name='origin')
        origin.push()
        time.sleep(3)  # Ждем, чтобы GitHub обработал файлы
    except Exception as e:
        logger.error(f"Ошибка при push в GitHub: {e}")
        return []

    # Формируем ссылки на кадры
    frame_files = sorted(destination.glob("*.png"))
    frame_links = [
        f"{GITHUB_RAW_URL}{frames_dir.name}/{frame.name}" for frame in frame_files
    ]

    return frame_links

def extract_text_from_frames(frames_dir: Path):
    """Извлекает текст с кадров видео с помощью Tesseract OCR."""
    extracted_text = []
    for frame in sorted(frames_dir.glob("*.png")):
        text = pytesseract.image_to_string(Image.open(frame), lang="eng")
        if text.strip():  # Фильтруем пустые результаты
            extracted_text.append(text.strip())
    return "\n".join(extracted_text) if extracted_text else "Текст не обнаружен."

def analyze_video_with_gpt(frame_links):
    """Отправляет ссылки на кадры в GPT и получает анализ видео."""
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
    
    if not frame_links:
        return "Ошибка: не удалось загрузить кадры."

    messages = [{"role": "system", "content": "Проанализируй последовательность кадров и опиши, что происходит в видео."}]
    max_frames_per_request = 10
    all_summaries = []
    
    for i in range(0, len(frame_links), max_frames_per_request):
        batch = frame_links[i:i + max_frames_per_request]
        messages.append({"role": "user", "content": [{"type": "image_url", "image_url": {"url": url}} for url in batch]})
        
        payload = {"model": "gpt-4o", "messages": messages, "max_tokens": 1200}
        try:
            response = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
            response.raise_for_status()
            all_summaries.append(response.json()["choices"][0]["message"]["content"])
            time.sleep(2)  # Избегаем rate limit API OpenAI
        except requests.RequestException as e:
            logger.error(f"Ошибка при анализе видео: {e}")
            all_summaries.append("Ошибка анализа видео.")
    
    return "\n".join(all_summaries)

def analyze_video(url: str, fps: float):
    """Обрабатывает видео, загружает кадры в GitHub и передает их GPT."""
    task_id = str(uuid.uuid4())
    frames_dir = Path("frames") / task_id
    
    try:
        video_path = download_video(url, Path("videos") / task_id)
        minutes, seconds = get_video_duration(video_path)
        extract_frames(video_path, frames_dir, fps)
        frame_links = upload_frames_to_github(frames_dir)

        if not frame_links:
            return {"error": "Не удалось загрузить кадры на GitHub."}
        
        extracted_text = extract_text_from_frames(frames_dir)
        video_summary = analyze_video_with_gpt(frame_links)

        return {
            "video_duration": f"{minutes} минут {seconds} секунд",
            "frame_count": len(frame_links),
            "summary": video_summary,
            "text": extracted_text
        }
    except Exception as e:
        logger.error(f"Ошибка в процессе анализа видео: {e}")
        return {"error": str(e)}

if __name__ == "__main__":
    check_dependencies()
    video_url = input("Введите ссылку на пост Instagram или YouTube: ")
    fps = float(input("Введите частоту кадров (в секундах): "))
    result = analyze_video(video_url, fps)

    print("\n🔍 **Результаты анализа:**")
    if "error" in result:
        print(result["error"])
    else:
        print(f"\n🎬 Длина видео: {result['video_duration']}")
        print(f"🖼 Количество кадров: {result['frame_count']}")
        print(f"📜 Описание видео: {result['summary']}")
        print(f"📝 Текст с видео: {result['text']}")


