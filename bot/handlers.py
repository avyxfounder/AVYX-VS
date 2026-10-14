from pathlib import Path
from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, FSInputFile
from aiogram.enums import ChatAction

from .config import Settings
from .media import MediaError, probe, duration_seconds, make_video_note, make_image_video_note, make_voice
from .utils import new_job_dir, cleanup

router = Router()
settings: Settings | None = None

WELCOME = (
    "👋 <b>AVYX VS</b>\n\n"
    "Отправь мне:\n"
    "• 🎬 видео → видео-кружок\n"
    "• 🖼 изображение → видео-кружок\n"
    "• 🎵 аудио/музыку → голосовое сообщение\n"
    "• 🎬 видео с аудио → голосовое сообщение\n\n"
    "Файлы после обработки удаляются."
)

@router.message(CommandStart())
async def start(message: Message):
    await message.answer(WELCOME)

@router.message(Command("help"))
async def help_cmd(message: Message):
    await message.answer(WELCOME)

async def _download(bot, file_id: str, dst: Path):
    tg_file = await bot.get_file(file_id)
    if not tg_file.file_path:
        raise MediaError("Telegram не вернул путь к файлу.")
    await bot.download_file(tg_file.file_path, destination=dst)

def _too_large(path: Path) -> bool:
    return path.stat().st_size > settings.max_output_mb * 1024 * 1024

async def _error(message: Message, exc: Exception):
    text = str(exc) or "Не удалось обработать файл."
    if len(text) > 700:
        text = text[-700:]
    await message.answer("❌ Не удалось обработать файл.\n<code>" + text + "</code>")

@router.message(F.photo)
async def photo(message: Message, bot):
    job = new_job_dir(settings.temp_dir)
    try:
        await bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_VIDEO)
        src = job / "input.jpg"
        dst = job / "video_note.mp4"
        await _download(bot, message.photo[-1].file_id, src)
        await make_image_video_note(src, dst)
        if _too_large(dst):
            raise MediaError("Результат больше лимита отправки.")
        await message.answer_video_note(FSInputFile(dst), duration=2, length=512)
    except Exception as exc:
        await _error(message, exc)
    finally:
        cleanup(job)

@router.message(F.video)
async def video(message: Message, bot):
    if message.video.file_size and message.video.file_size > settings.max_download_mb * 1024 * 1024:
        await message.answer("❌ Файл больше " + str(settings.max_download_mb) + " МБ. Для больших файлов позже подключим Local Bot API.")
        return
    job = new_job_dir(settings.temp_dir)
    try:
        await bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_VIDEO)
        src = job / "input"
        dst = job / "video_note.mp4"
        await _download(bot, message.video.file_id, src)
        info = await probe(src)
        duration = duration_seconds(info)
        if duration > 60.5:
            raise MediaError("Видео-кружок ограничен примерно 60 секундами.")
        await make_video_note(src, dst)
        if _too_large(dst):
            raise MediaError("Результат больше лимита отправки.")
        await message.answer_video_note(FSInputFile(dst), duration=max(1, min(60, round(duration))), length=512)
    except Exception as exc:
        await _error(message, exc)
    finally:
        cleanup(job)

@router.message(F.audio)
async def audio(message: Message, bot):
    if message.audio.file_size and message.audio.file_size > settings.max_download_mb * 1024 * 1024:
        await message.answer("❌ Файл больше " + str(settings.max_download_mb) + " МБ.")
        return
    job = new_job_dir(settings.temp_dir)
    try:
        await bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_VOICE)
        src = job / "input"
        dst = job / "voice.ogg"
        await _download(bot, message.audio.file_id, src)
        await make_voice(src, dst)
        if _too_large(dst):
            raise MediaError("Результат больше лимита отправки.")
        await message.answer_voice(FSInputFile(dst))
    except Exception as exc:
        await _error(message, exc)
    finally:
        cleanup(job)

@router.message(F.document)
async def document(message: Message, bot):
    doc = message.document
    if doc.file_size and doc.file_size > settings.max_download_mb * 1024 * 1024:
        await message.answer("❌ Документ больше " + str(settings.max_download_mb) + " МБ.")
        return
    name = (doc.file_name or "").lower()
    audio_ext = (".mp3", ".wav", ".m4a", ".flac", ".aac", ".ogg", ".opus", ".wma")
    video_ext = (".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".mpeg", ".mpg")
    if not name.endswith(audio_ext + video_ext):
        await message.answer("📎 Поддерживаются аудио/видео файлы. Отправь их как документ.")
        return

    job = new_job_dir(settings.temp_dir)
    try:
        src = job / (Path(doc.file_name or "input").name)
        await _download(bot, doc.file_id, src)
        if name.endswith(video_ext):
            dst = job / "video_note.mp4"
            info = await probe(src)
            duration = duration_seconds(info)
            if duration > 60.5:
                raise MediaError("Видео-кружок ограничен примерно 60 секундами.")
            await bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_VIDEO)
            await make_video_note(src, dst)
            if _too_large(dst):
                raise MediaError("Результат больше лимита отправки.")
            await message.answer_video_note(FSInputFile(dst), duration=max(1, min(60, round(duration))), length=512)
        else:
            dst = job / "voice.ogg"
            await bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_VOICE)
            await make_voice(src, dst)
            if _too_large(dst):
                raise MediaError("Результат больше лимита отправки.")
            await message.answer_voice(FSInputFile(dst))
    except Exception as exc:
        await _error(message, exc)
    finally:
        cleanup(job)

@router.message(F.voice)
async def voice(message: Message):
    await message.answer("🎙 Это уже голосовое сообщение. Пришли аудио, музыку или видео.")

@router.message(F.video_note)
async def video_note(message: Message):
    await message.answer("🎬 Это уже видео-кружок. Пришли обычное видео или изображение.")

@router.message()
async def fallback(message: Message):
    await message.answer("📥 Пришли видео, изображение, аудио или аудио/видео как документ. /help")
