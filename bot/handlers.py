from pathlib import Path
from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.enums import ChatAction

from .config import Settings
from .media import MediaError, probe, duration_seconds, make_video_note, make_image_video_note, make_voice
from .utils import new_job_dir, cleanup, remove_file
from .access import AccessManager

router = Router()
settings: Settings | None = None
access: AccessManager | None = None



def menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎥 Видео → кружок", callback_data="video_help")],
        [InlineKeyboardButton(text="🖼 Фото → кружок", callback_data="photo_help")],
        [InlineKeyboardButton(text="🎵 Аудио → голосовое", callback_data="audio_help")],
        [InlineKeyboardButton(text="📁 Файл", callback_data="file_help")],
        [InlineKeyboardButton(text="⚙️ Настройки", callback_data="settings_help")]
    ])

def admin_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Выдать доступ", callback_data="admin_add")],
        [InlineKeyboardButton(text="➖ Забрать доступ", callback_data="admin_remove")],
        [InlineKeyboardButton(text="🚫 Заблокировать", callback_data="admin_block")],
        [InlineKeyboardButton(text="👑 Назначить админа", callback_data="admin_promote")],
        [InlineKeyboardButton(text="📋 Пользователи", callback_data="admin_users")]
    ])

@router.message(Command("admin"))
async def admin_cmd(message: Message):
    if not access.admin(message.from_user.id):
        return await message.answer("🔒 Доступ закрыт.")
    await message.answer("👑 <b>Админ-панель AVYX VS</b>", reply_markup=admin_menu())

@router.callback_query(F.data.startswith("admin_"))
async def admin_callback(callback: CallbackQuery):
    if not access.admin(callback.from_user.id):
        return await callback.answer("Доступ закрыт", show_alert=True)
    await callback.answer()
    if callback.data == "admin_users":
        return await callback.message.answer("📋 Пользователи:\n" + ("\n".join(map(str, access.list_users())) or "Нет пользователей"))
    prompts = {
        "admin_add": "➕ Команда: <code>/add ID</code>",
        "admin_remove": "➖ Команда: <code>/remove ID</code>",
        "admin_block": "🚫 Команда: <code>/block ID</code>",
        "admin_promote": "👑 Команда: <code>/promote ID</code>"
    }
    await callback.message.answer(prompts[callback.data])

@router.message(F.text.regexp(r"^/add\s+\d+$"))
async def add_user(message: Message):
    if access.admin(message.from_user.id):
        access.add(int(message.text.split()[1]))
        await message.answer("✅ Доступ выдан.")

@router.message(F.text.regexp(r"^/remove\s+\d+$"))
async def remove_user(message: Message):
    if access.admin(message.from_user.id):
        access.remove(int(message.text.split()[1]))
        await message.answer("✅ Доступ забран.")

@router.message(F.text.regexp(r"^/block\s+\d+$"))
async def block_user(message: Message):
    if access.admin(message.from_user.id):
        access.block(int(message.text.split()[1]))
        await message.answer("🚫 Пользователь заблокирован.")

@router.message(F.text.regexp(r"^/promote\s+\d+$"))
async def promote_user(message: Message):
    if access.admin(message.from_user.id):
        access.promote(int(message.text.split()[1]))
        await message.answer("👑 Админ назначен.")

@router.callback_query(F.data.endswith("_help"))
async def menu_help(callback: CallbackQuery):
    if not access.allowed(callback.from_user.id):
        return await callback.answer("Доступ закрыт", show_alert=True)
    await callback.answer()
    texts = {
        "video_help": "🎥 Отправь видео — получишь кружок.",
        "photo_help": "🖼 Отправь фото — получишь кружок.",
        "audio_help": "🎵 Отправь аудио — получишь голосовое.",
        "file_help": "📁 Отправь аудио или видео как документ.",
        "settings_help": "⚙️ Максимальное качество включено."
    }
    await callback.message.answer(texts[callback.data])

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
    if not access.allowed(message.from_user.id): return await message.answer('🔒 Доступ закрыт. Обратитесь к администратору AVYX VS.')
    await message.answer(WELCOME, reply_markup=menu())

@router.message(Command("help"))
async def help_cmd(message: Message):
    if not access.allowed(message.from_user.id): return await message.answer('🔒 Доступ закрыт.')
    await message.answer(WELCOME, reply_markup=menu())

async def _download(bot, file_id: str, dst: Path):
    tg_file = await bot.get_file(file_id)
    if not tg_file.file_path:
        raise MediaError("Telegram не вернул путь к файлу.")
    await bot.download_file(tg_file.file_path, destination=dst)

def _too_large(path: Path) -> bool:
    return path.stat().st_size > settings.max_output_mb * 1024 * 1024


async def _status(message: Message, text: str):
    try:
        return await message.answer(text)
    except Exception:
        return None

async def _status_update(status: Message | None, text: str):
    if status is None:
        return
    try:
        await status.edit_text(text)
    except Exception:
        pass

def _progress_bar(percent: int) -> str:
    percent = max(0, min(100, percent))
    filled = percent // 10
    return "█" * filled + "░" * (10 - filled)

async def _error(message: Message, exc: Exception):
    text = str(exc) or "Не удалось обработать файл."
    if len(text) > 700:
        text = text[-700:]
    await message.answer("❌ Не удалось обработать файл.\n<code>" + text + "</code>")

@router.message(F.photo)
async def photo(message: Message, bot):
    if not access.allowed(message.from_user.id): return await message.answer("🔒 Доступ закрыт.")
    status = await _status(message, "⏳ <b>Подготовка</b>\n" + _progress_bar(5) + " 5%")
    job = new_job_dir(settings.temp_dir)
    try:
        await bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_VIDEO)
        src = job / "input.jpg"
        dst = job / "video_note.mp4"
        await _download(bot, message.photo[-1].file_id, src)
        await _status_update(status, "📥 <b>Файл получен</b>\n" + _progress_bar(25) + " 25%")
        remove_file(src)
        await _status_update(status, "⚙️ <b>Создаю кружок</b>\n" + _progress_bar(50) + " 50%")
        await make_image_video_note(src, dst)
        await _status_update(status, "📤 <b>Отправляю результат</b>\n" + _progress_bar(95) + " 95%")
        if _too_large(dst):
            raise MediaError("Результат больше лимита отправки.")
        await message.answer_video_note(FSInputFile(dst), duration=2, length=1080)
        await _status_update(status, "✅ <b>Готово</b>\n" + _progress_bar(100) + " 100%")
    except Exception as exc:
        await _error(message, exc)
    finally:
        cleanup(job)

@router.message(F.video)
async def video(message: Message, bot):
    if not access.allowed(message.from_user.id): return await message.answer("🔒 Доступ закрыт.")
    if message.video.file_size and message.video.file_size > settings.max_download_mb * 1024 * 1024:
        await message.answer("❌ Файл больше " + str(settings.max_download_mb) + " МБ. Для больших файлов позже подключим Local Bot API.")
        return
    status = await _status(message, "⏳ <b>Подготовка</b>\n" + _progress_bar(5) + " 5%")
    job = new_job_dir(settings.temp_dir)
    try:
        await bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_VIDEO)
        src = job / "input"
        dst = job / "video_note.mp4"
        await _download(bot, message.video.file_id, src)
        await _status_update(status, "📥 <b>Файл получен</b>\n" + _progress_bar(25) + " 25%")
        info = await probe(src)
        duration = duration_seconds(info)
        if duration > 60.5:
            raise MediaError("Видео-кружок ограничен примерно 60 секундами.")
        await _status_update(status, "⚙️ <b>Конвертирую видео</b>\n" + _progress_bar(50) + " 50%")
        await make_video_note(src, dst)
        await _status_update(status, "📦 <b>Обработка завершена</b>\n" + _progress_bar(90) + " 90%")
        if _too_large(dst):
            raise MediaError("Результат больше лимита отправки.")
        await _status_update(status, "📤 <b>Отправляю результат</b>\n" + _progress_bar(95) + " 95%")
        await message.answer_video_note(FSInputFile(dst), duration=max(1, min(60, round(duration))), length=512)
        await _status_update(status, "✅ <b>Готово</b>\n" + _progress_bar(100) + " 100%")
    except Exception as exc:
        await _error(message, exc)
    finally:
        cleanup(job)

@router.message(F.audio)
async def audio(message: Message, bot):
    if not access.allowed(message.from_user.id): return await message.answer("🔒 Доступ закрыт.")
    if message.audio.file_size and message.audio.file_size > settings.max_download_mb * 1024 * 1024:
        await message.answer("❌ Файл больше " + str(settings.max_download_mb) + " МБ.")
        return
    status = await _status(message, "⏳ <b>Подготовка</b>\n" + _progress_bar(5) + " 5%")
    job = new_job_dir(settings.temp_dir)
    try:
        await bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_VOICE)
        src = job / "input"
        dst = job / "voice.ogg"
        await _download(bot, message.audio.file_id, src)
        await _status_update(status, "📥 <b>Файл получен</b>\n" + _progress_bar(25) + " 25%")
        await _status_update(status, "🎵 <b>Создаю голосовое</b>\n" + _progress_bar(50) + " 50%")
        await make_voice(src, dst)
        await _status_update(status, "📤 <b>Отправляю результат</b>\n" + _progress_bar(95) + " 95%")
        if _too_large(dst):
            raise MediaError("Результат больше лимита отправки.")
        await message.answer_voice(FSInputFile(dst))
        await _status_update(status, "✅ <b>Готово</b>\n" + _progress_bar(100) + " 100%")
    except Exception as exc:
        await _error(message, exc)
    finally:
        cleanup(job)

@router.message(F.document)
async def document(message: Message, bot):
    if not access.allowed(message.from_user.id): return await message.answer("🔒 Доступ закрыт.")
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

    status = await _status(message, "⏳ <b>Подготовка</b>\n" + _progress_bar(5) + " 5%")
    job = new_job_dir(settings.temp_dir)
    try:
        src = job / (Path(doc.file_name or "input").name)
        await _download(bot, doc.file_id, src)
        await _status_update(status, "📥 <b>Файл получен</b>\n" + _progress_bar(25) + " 25%")
        if name.endswith(video_ext):
            dst = job / "video_note.mp4"
            info = await probe(src)
            duration = duration_seconds(info)
            if duration > 60.5:
                raise MediaError("Видео-кружок ограничен примерно 60 секундами.")
            await bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_VIDEO)
            await _status_update(status, "⚙️ <b>Конвертирую видео</b>\n" + _progress_bar(50) + " 50%")
            await make_video_note(src, dst)
            await _status_update(status, "📤 <b>Отправляю результат</b>\n" + _progress_bar(95) + " 95%")
            if _too_large(dst):
                raise MediaError("Результат больше лимита отправки.")
            await message.answer_video_note(FSInputFile(dst), duration=max(1, min(60, round(duration))), length=512)
            await _status_update(status, "✅ <b>Готово</b>\n" + _progress_bar(100) + " 100%")
        else:
            dst = job / "voice.ogg"
            await bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_VOICE)
            await _status_update(status, "🎵 <b>Создаю голосовое</b>\n" + _progress_bar(50) + " 50%")
            await make_voice(src, dst)
            await _status_update(status, "📤 <b>Отправляю результат</b>\n" + _progress_bar(95) + " 95%")
            if _too_large(dst):
                raise MediaError("Результат больше лимита отправки.")
            await message.answer_voice(FSInputFile(dst))
            await _status_update(status, "✅ <b>Готово</b>\n" + _progress_bar(100) + " 100%")
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
