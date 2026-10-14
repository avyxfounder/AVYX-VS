import asyncio
import re
import shutil
try:
    import av
except ImportError:
    av = None
from pathlib import Path
from typing import Awaitable, Callable
try:
    import imageio_ffmpeg
except ImportError:
    imageio_ffmpeg = None

class MediaError(RuntimeError):
    pass

ProgressCallback = Callable[[float], Awaitable[None]]

def _ffmpeg_bin() -> str:
    # Сначала используем проверенный FFmpeg из imageio-ffmpeg,
    # системный FFmpeg оставляем как запасной вариант.
    if imageio_ffmpeg is not None:
        try:
            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            pass
    path = shutil.which("ffmpeg")
    if path:
        return path
    raise MediaError("FFmpeg не найден на сервере. Установите FFmpeg или пакет imageio-ffmpeg.")

async def run_ffmpeg(*args: str, progress: ProgressCallback | None = None):
    proc = await asyncio.create_subprocess_exec(
        _ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y", *args,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, err = await asyncio.wait_for(proc.communicate(), timeout=180)
    except asyncio.TimeoutError as exc:
        proc.kill()
        await proc.communicate()
        raise MediaError("Обработка заняла слишком много времени и была остановлена.") from exc
    if proc.returncode:
        details = err.decode("utf-8", errors="replace").strip()
        raise MediaError(details or "Не удалось обработать файл.")

async def probe(path: Path) -> dict:
    if av is not None:
        def read_metadata():
            try:
                with av.open(str(path)) as container:
                    duration = 0.0
                    if container.duration:
                        duration = float(container.duration) / float(av.time_base)
                    if duration <= 0:
                        for stream in container.streams:
                            if stream.duration and stream.time_base:
                                duration = max(duration, float(stream.duration * stream.time_base))
                    return duration
            except Exception as exc:
                raise MediaError("Не удалось прочитать видео. Проверьте файл.") from exc
        return {"format": {"duration": await asyncio.to_thread(read_metadata)}}
    proc = await asyncio.create_subprocess_exec(
        _ffmpeg_bin(), "-hide_banner", "-i", str(path),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, err = await proc.communicate()
    text = err.decode("utf-8", errors="replace")
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", text)
    duration = 0.0
    if match:
        h, m, s = match.groups()
        duration = int(h) * 3600 + int(m) * 60 + float(s)
    if duration <= 0:
        raise MediaError("Не удалось прочитать видео. Проверьте файл.")
    return {"format": {"duration": duration}}

def duration_seconds(info: dict) -> float:
    try:
        return float(info.get("format", {}).get("duration", 0))
    except Exception:
        return 0.0

def _crf(quality: str) -> int:
    return {"economy": 28, "standard": 23, "maximum": 18}.get(quality, 18)

async def make_video_note(src: Path, dst: Path, quality: str = "maximum"):
    await run_ffmpeg(
        "-i", str(src), "-t", "60", "-map", "0:v:0", "-map", "0:a:0?",
        "-vf", "scale=640:640:force_original_aspect_ratio=increase,crop=640:640,setsar=1",
        "-c:v", "libx264", "-preset", "veryfast", "-threads", "2",
        "-crf", str(_crf(quality)), "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-ac", "2", "-ar", "48000",
        "-movflags", "+faststart", str(dst),
    )

async def make_image_video_note(src: Path, dst: Path, duration: int = 10, quality: str = "maximum"):
    await run_ffmpeg(
        "-loop", "1", "-i", str(src), "-t", str(max(10, min(60, duration))),
        "-vf", "scale=640:640:force_original_aspect_ratio=increase,crop=640:640,setsar=1",
        "-r", "15", "-an", "-c:v", "libx264", "-preset", "veryfast", "-threads", "2",
        "-crf", str(_crf(quality)), "-pix_fmt", "yuv420p", str(dst),
    )

async def make_voice(src: Path, dst: Path):
    await run_ffmpeg(
        "-i", str(src), "-vn", "-map_metadata", "-1",
        "-c:a", "libopus", "-b:a", "128k", "-vbr", "on",
        "-compression_level", "10", "-threads", "2", "-vn", str(dst),
    )

async def make_mp3(src: Path, dst: Path):
    await run_ffmpeg(
        "-i", str(src), "-vn", "-map", "0:a:0",
        "-c:a", "libmp3lame", "-b:a", "192k", "-ar", "48000", "-threads", "2",
        "-map_metadata", "-1", str(dst),
    )
