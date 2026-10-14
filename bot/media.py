import asyncio
import re
import shutil
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
    if imageio_ffmpeg is not None:
        return imageio_ffmpeg.get_ffmpeg_exe()
    path = shutil.which("ffmpeg")
    if path:
        return path
    raise MediaError("FFmpeg не найден на сервере.")


async def run_ffmpeg(*args: str, progress: ProgressCallback | None = None):
    proc = await asyncio.create_subprocess_exec(
        _ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y", *args,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, err = await proc.communicate()
    if proc.returncode:
        details = err.decode("utf-8", errors="replace").strip()
        raise MediaError(details or "Не удалось обработать файл.")


async def probe(path: Path) -> dict:
    proc = await asyncio.create_subprocess_exec(
        _ffmpeg_bin(), "-hide_banner", "-i", str(path), "-f", "null", "-",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, err = await proc.communicate()
    text = err.decode("utf-8", errors="replace")
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", text)
    duration = 0.0
    if match:
        h, m, s = match.groups()
        duration = int(h) * 3600 + int(m) * 60 + float(s)
    if proc.returncode and duration <= 0:
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
        "-i", str(src), "-t", "60",
        "-vf", "scale=640:640:force_original_aspect_ratio=increase,crop=640:640,setsar=1",
        "-an", "-c:v", "libx264", "-preset", "medium",
        "-crf", str(_crf(quality)), "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", str(dst),
    )


async def make_image_video_note(src: Path, dst: Path, duration: int = 10, quality: str = "maximum"):
    await run_ffmpeg(
        "-loop", "1", "-i", str(src), "-t", str(max(10, min(60, duration))),
        "-vf", "scale=640:640:force_original_aspect_ratio=increase,crop=640:640,setsar=1",
        "-an", "-c:v", "libx264", "-preset", "medium",
        "-crf", str(_crf(quality)), "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", str(dst),
    )


async def make_voice(src: Path, dst: Path):
    await run_ffmpeg(
        "-i", str(src), "-vn", "-map_metadata", "-1",
        "-c:a", "libopus", "-b:a", "128k", "-vbr", "on",
        "-compression_level", "10", str(dst),
    )
