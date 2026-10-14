from pathlib import Path
from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.enums import ChatAction

from .config import Settings
from .media import MediaError, probe, duration_seconds, make_video_note, make_image_video_note, make_voice
from .utils import new_job_dir, cleanup, remove_file
from .access import AccessManager
from .transcribe import transcribe

router = Router()
settings: Settings | None = None
access: AccessManager | None = None
photo_duration: dict[int, int] = {}
quality: dict[int, str] = {}



def menu(user_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎥 Видео → кружок", callback_data="video_help")],
        [InlineKeyboardButton(text="🖼 Фото → кружок", callback_data="photo_settings")],
        [InlineKeyboardButton(text="🎵 Аудио → голосовое", callback_data="audio_help")],
        [InlineKeyboardButton(text="📁 Файл → конвертация", callback_data="file_help")],
        [InlineKeyboardButton(text="📝 Расшифровка", callback_data="transcribe_info")],
        [InlineKeyboardButton(text="⚙️ Настройки", callback_data="settings_menu")],
    ] + ([ [InlineKeyboardButton(text="👑 Админ-панель", callback_data="admin_panel")] ] if access and access.admin(user_id) else []))

def back_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="back_menu")]
    ])

def photo_settings_menu(current: int):
    values = [10, 20, 30, 40, 50, 60]
    rows = []
    for start in range(0, len(values), 3):
        rows.append([
            InlineKeyboardButton(text=(f"✅ {v} сек" if v == current else f"{v} сек"), callback_data=f"photo_duration:{v}")
            for v in values[start:start + 3]
        ])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def settings_menu(user_id: int):
    d = photo_duration.get(user_id, 10)
    q = {"economy": "Эконом", "standard": "Стандарт", "maximum": "Максимум"}.get(quality.get(user_id, "maximum"), "Максимум")
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🖼 Фото-кружок: {d} сек", callback_data="photo_settings")],
        [InlineKeyboardButton(text=f"🎚 Качество: {q}", callback_data="quality_settings")],
        [InlineKeyboardButton(text="🎥 Видео-кружок: до 60 сек", callback_data="video_settings")],
        [InlineKeyboardButton(text="🧹 Автоудаление: включено", callback_data="cleanup_info")],
        [InlineKeyboardButton(text="ℹ️ Как работает бот", callback_data="settings_info")],
        [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="back_menu")]
    ])

def admin_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Выдать доступ", callback_data="admin_add")],
        [InlineKeyboardButton(text="➖ Забрать доступ", callback_data="admin_remove")],
        [InlineKeyboardButton(text="🚫 Заблокировать", callback_data="admin_block")],
        [InlineKeyboardButton(text="👑 Назначить админа", callback_data="admin_promote")],
        [InlineKeyboardButton(text="📋 Пользователи", callback_data="admin_users")]
    ])

@router.message(Command("text"))
async def text_command(message: Message, bot):
    if not access.allowed(message.from_user.id):
        return await message.answer("🔒 Доступ закрыт.")
    replied = message.reply_to_message
    if not replied:
        return await message.answer("📝 Ответь командой /text на голосовое, кружок или видео.")
    if replied.voice:
        return await _transcribe_message(message, bot, replied.voice.file_id, "voice.ogg")
    if replied.video_note:
        return await _transcribe_message(message, bot, replied.video_note.file_id, "video_note.mp4")
    if replied.video:
        return await _transcribe_message(message, bot, replied.video.file_id, "video.mp4")
    if replied.audio:
        return await _transcribe_message(message, bot, replied.audio.file_id, "audio.mp3")
    return await message.answer("📝 Поддерживаются голосовые, видео-кружки, видео и аудио.")

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

@router.callback_query(F.data.startswith("photo_duration:"))
async def photo_duration_callback(callback: CallbackQuery):
    if not access.allowed(callback.from_user.id):
        return await callback.answer("Доступ закрыт", show_alert=True)
    value = int(callback.data.split(":")[1])
    photo_duration[callback.from_user.id] = value
    await callback.answer(f"Установлено: {value} сек.")
    await callback.message.edit_text(
        "🖼 <b>Длительность фото-кружка</b>\n\nВыбери длительность от 10 секунд до 1 минуты.",
        reply_markup=photo_settings_menu(value)
    )

@router.callback_query(F.data == "photo_settings")
async def photo_settings_callback(callback: CallbackQuery):
    if not access.allowed(callback.from_user.id):
        return await callback.answer("Доступ закрыт", show_alert=True)
    await callback.answer()
    current = photo_duration.get(callback.from_user.id, 10)
    await callback.message.edit_text(
        "🖼 <b>Длительность фото-кружка</b>\n\nСейчас: <b>" + str(current) + " сек</b>",
        reply_markup=photo_settings_menu(current)
    )

@router.callback_query(F.data == "settings_menu")
async def settings_callback(callback: CallbackQuery):
    if not access.allowed(callback.from_user.id):
        return await callback.answer("Доступ закрыт", show_alert=True)
    await callback.answer()
    await callback.message.edit_text(
        "⚙️ <b>Настройки AVYX VS</b>\n\nВыбери нужный параметр:",
        reply_markup=settings_menu(callback.from_user.id)
    )

@router.callback_query(F.data == "quality_settings")
async def quality_settings_callback(callback: CallbackQuery):
    if not access.allowed(callback.from_user.id):
        return await callback.answer("Доступ закрыт", show_alert=True)
    current = quality.get(callback.from_user.id, "maximum")
    await callback.answer()
    await callback.message.edit_text(
        "🎚 <b>Качество</b>\n\n"
        "Эконом — меньший размер.\n"
        "Стандарт — баланс.\n"
        "Максимум — лучшее качество.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=("✅ " if current == "economy" else "") + "Эконом", callback_data="quality:economy")],
            [InlineKeyboardButton(text=("✅ " if current == "standard" else "") + "Стандарт", callback_data="quality:standard")],
            [InlineKeyboardButton(text=("✅ " if current == "maximum" else "") + "Максимум", callback_data="quality:maximum")],
            [InlineKeyboardButton(text="⬅️ Настройки", callback_data="settings_menu")]
        ])
    )

@router.callback_query(F.data.startswith("quality:"))
async def quality_select_callback(callback: CallbackQuery):
    if not access.allowed(callback.from_user.id):
        return await callback.answer("Доступ закрыт", show_alert=True)
    value = callback.data.split(":", 1)[1]
    if value not in ("economy", "standard", "maximum"):
        return await callback.answer("Недопустимое качество", show_alert=True)
    quality[callback.from_user.id] = value
    await callback.answer("Качество сохранено")
    await callback.message.edit_text(
        "⚙️ <b>Настройки AVYX VS</b>\n\nВыбери параметр:",
        reply_markup=settings_menu(callback.from_user.id)
    )

@router.callback_query(F.data == "transcribe_info")
async def transcribe_info(callback: CallbackQuery):
    if not access.allowed(callback.from_user.id):
        return await callback.answer("Доступ закрыт", show_alert=True)
    await callback.answer()
    await callback.message.edit_text(
        "📝 <b>Расшифровка</b>\n\nГолосовые, видео и кружки можно преобразовать в текст. Используется локальное распознавание речи.",
        reply_markup=back_menu()
    )

@router.callback_query(F.data == "video_settings")
async def video_settings_callback(callback: CallbackQuery):
    await callback.answer("Видео-кружок: максимум 60 секунд.", show_alert=True)

@router.callback_query(F.data == "quality_info")
async def quality_callback(callback: CallbackQuery):
    await callback.answer("Максимальное качество обработки включено.", show_alert=True)

@router.callback_query(F.data == "cleanup_info")
async def cleanup_callback(callback: CallbackQuery):
    await callback.answer("Временные файлы удаляются после каждой операции.", show_alert=True)

@router.callback_query(F.data == "back_menu")
async def back_menu_callback(callback: CallbackQuery):
    if not access.allowed(callback.from_user.id):
        return await callback.answer("Доступ закрыт", show_alert=True)
    await callback.answer()
    await callback.message.edit_text(WELCOME, reply_markup=menu(callback.from_user.id))

@router.callback_query(F.data.endswith("_help"))
async def menu_help(callback: CallbackQuery):
    if not access.allowed(callback.from_user.id):
        return await callback.answer("Доступ закрыт", show_alert=True)
    await callback.answer()
    texts = {
        "video_help": "🎥 <b>Видео → кружок</b>\n\nОтправь обычное видео — бот сделает видео-кружок до 60 секунд.",
        "audio_help": "🎵 <b>Аудио → голосовое</b>\n\nОтправь музыку или аудиофайл — бот конвертирует его в голосовое.",
        "file_help": "📁 <b>Файл</b>\n\nОтправь аудио или видео как документ — бот определит формат автоматически."
    }
    await callback.message.edit_text(texts[callback.data], reply_markup=back_menu())

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
    await message.answer(WELCOME, reply_markup=menu(message.from_user.id))

@router.message(Command("help"))
async def help_cmd(message: Message):
    if not access.allowed(message.from_user.id): return await message.answer('🔒 Доступ закрыт.')
    await message.answer(WELCOME, reply_markup=menu(message.from_user.id))

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
    duration = photo_duration.get(message.from_user.id, 10)
    q = quality.get(message.from_user.id, "maximum")
    status = await _status(message, "⏳ <b>Подготовка</b>\n" + _progress_bar(5) + " 5%")
    job = new_job_dir(settings.temp_dir)
    try:
        await bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_VIDEO)
        src = job / "input.jpg"
        dst = job / "video_note.mp4"
        await _download(bot, message.photo[-1].file_id, src)
        await _status_update(status, "📥 <b>Файл получен</b>\n" + _progress_bar(25) + " 25%")
        await _status_update(status, "⚙️ <b>Создаю кружок</b>\n" + _progress_bar(50) + " 50%")
        await make_image_video_note(src, dst, duration=duration, quality=q)
        src.unlink(missing_ok=True)
        await _status_update(status, "📤 <b>Отправляю результат</b>\n" + _progress_bar(95) + " 95%")
        if _too_large(dst):
            raise MediaError("Результат больше лимита отправки.")
        await message.answer_video_note(FSInputFile(dst), duration=duration, length=640)
        dst.unlink(missing_ok=True)
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
        await make_video_note(src, dst, quality=quality.get(message.from_user.id, "maximum"))
        src.unlink(missing_ok=True)
        await _status_update(status, "📦 <b>Обработка завершена</b>\n" + _progress_bar(90) + " 90%")
        if _too_large(dst):
            raise MediaError("Результат больше лимита отправки.")
        await _status_update(status, "📤 <b>Отправляю результат</b>\n" + _progress_bar(95) + " 95%")
        await message.answer_video_note(FSInputFile(dst), duration=max(1, min(60, round(duration))), length=640)
        dst.unlink(missing_ok=True)
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
        src.unlink(missing_ok=True)
        await _status_update(status, "📤 <b>Отправляю результат</b>\n" + _progress_bar(95) + " 95%")
        if _too_large(dst):
            raise MediaError("Результат больше лимита отправки.")
        await message.answer_voice(FSInputFile(dst))
        dst.unlink(missing_ok=True)
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
    if not name.endswith(audio_ext) and not name.endswith(video_ext):
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
            await make_video_note(src, dst, quality=quality.get(message.from_user.id, "maximum"))
            src.unlink(missing_ok=True)
            await _status_update(status, "📤 <b>Отправляю результат</b>\n" + _progress_bar(95) + " 95%")
            if _too_large(dst):
                raise MediaError("Результат больше лимита отправки.")
            await message.answer_video_note(FSInputFile(dst), duration=max(1, min(60, round(duration))), length=640)
            dst.unlink(missing_ok=True)
            await _status_update(status, "✅ <b>Готово</b>\n" + _progress_bar(100) + " 100%")
        else:
            dst = job / "voice.ogg"
            await bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_VOICE)
            await _status_update(status, "🎵 <b>Создаю голосовое</b>\n" + _progress_bar(50) + " 50%")
            await make_voice(src, dst)
            src.unlink(missing_ok=True)
            await _status_update(status, "📤 <b>Отправляю результат</b>\n" + _progress_bar(95) + " 95%")
            if _too_large(dst):
                raise MediaError("Результат больше лимита отправки.")
            await message.answer_voice(FSInputFile(dst))
            dst.unlink(missing_ok=True)
            await _status_update(status, "✅ <b>Готово</b>\n" + _progress_bar(100) + " 100%")
    except Exception as exc:
        await _error(message, exc)
    finally:
        cleanup(job)

async def _transcribe_message(message: Message, bot, file_id: str, filename: str):
    if not access.allowed(message.from_user.id):
        return await message.answer("🔒 Доступ закрыт.")
    if getattr(message, "voice", None) and message.voice.file_size and message.voice.file_size > settings.max_download_mb * 1024 * 1024:
        return await message.answer(f"❌ Файл больше {settings.max_download_mb} МБ.")
    status = await _status(message, "📝 <b>Подготовка расшифровки</b>\n" + _progress_bar(10) + " 10%")
    job = new_job_dir(settings.temp_dir)
    try:
        src = job / filename
        await _download(bot, file_id, src)
        await _status_update(status, "📥 <b>Файл получен</b>\n" + _progress_bar(25) + " 25%")
        await _status_update(status, "🧠 <b>Распознаю речь</b>\n" + _progress_bar(60) + " 60%")
        text = await transcribe(src)
        await _status_update(status, "📤 <b>Формирую результат</b>\n" + _progress_bar(90) + " 90%")
        if len(text) > 3800:
            for i in range(0, len(text), 3800):
                await message.answer("📝 " + text[i:i + 3800])
        else:
            await message.answer("📝 <b>Расшифровка</b>\n\n" + text)
        await _status_update(status, "✅ <b>Готово</b>\n" + _progress_bar(100) + " 100%")
    except Exception as exc:
        await _error(message, exc)
    finally:
        cleanup(job)


@router.message(F.voice)
async def voice(message: Message, bot):
    return await _transcribe_message(message, bot, message.voice.file_id, "voice.ogg")


@router.message(F.video_note)
async def video_note(message: Message, bot):
    return await _transcribe_message(message, bot, message.video_note.file_id, "video_note.mp4")


@router.message()
async def fallback(message: Message):
    if not access.allowed(message.from_user.id):
        return await message.answer("🔒 Доступ закрыт.")
    await message.answer("📥 Выбери действие в меню или отправь видео, фото, аудио или файл.", reply_markup=menu(message.from_user.id))
