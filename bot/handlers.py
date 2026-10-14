from pathlib import Path
from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton
from aiogram.enums import ChatAction

from .config import Settings
from .media import MediaError, probe, duration_seconds, make_video_note, make_image_video_note, make_voice
from .utils import new_job_dir, cleanup, remove_file
from .access import AccessManager
from .content import BotContent
from .transcribe import transcribe

router = Router()
settings: Settings | None = None
access: AccessManager | None = None
content: BotContent | None = None
admin_edit_state: dict[int, str] = {}
photo_duration: dict[int, int] = {}
quality: dict[int, str] = {}
selected_mode: dict[int, str] = {}



def _allowed(user_id: int) -> bool:
    return access.allowed(user_id, content.public_access if content else False)


def menu(user_id: int):
    rows = [
        [KeyboardButton(text="🎥 Видео → кружок"), KeyboardButton(text="🖼 Фото → кружок")],
        [KeyboardButton(text="🎵 Аудио → голосовое"), KeyboardButton(text="📁 Файл → конвертация")],
        [KeyboardButton(text="📝 Расшифровка"), KeyboardButton(text="👤 Профиль")],
        [KeyboardButton(text="ℹ️ О боте")],
        [KeyboardButton(text="⚙️ Настройки")],
    ]
    if access and access.admin(user_id):
        rows.append([KeyboardButton(text="👑 Админ-панель")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, is_persistent=True, input_field_placeholder="Выберите функцию…")


def mode_menu(current: str | None = None):
    labels = {
        "video": "🎥 Видео → кружок",
        "photo": "🖼 Фото → кружок",
        "audio": "🎵 Аудио → голосовое",
        "file": "📁 Файл → конвертация",
        "transcribe": "📝 Расшифровка",
    }
    rows = []
    for key, label in labels.items():
        rows.append([InlineKeyboardButton(text=("✅ " if current == key else "") + label, callback_data=f"mode:{key}")])
    rows.append([InlineKeyboardButton(text="⚙️ Настройки", callback_data="settings_menu")])
    if current:
        rows.append([InlineKeyboardButton(text="⬅️ Главное меню", callback_data="back_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def mode_prompt(user_id: int):
    current = selected_mode.get(user_id)
    return "🎯 <b>Выбери функцию</b>\n\nПосле выбора бот принимает только соответствующий тип файлов.\n\n" + (f"Сейчас выбрано: <b>{current}</b>" if current else "Сейчас функция не выбрана.")

def _selected(user_id: int, mode: str) -> bool:
    return selected_mode.get(user_id) == mode

async def _admin_input(message: Message, bot=None):
    if not access.admin(message.from_user.id):
        return False
    state = admin_edit_state.get(message.from_user.id)
    if not state:
        return False
    uid = message.from_user.id
    if state in ("ref_text", "bot_info_text"):
        if not message.text:
            await message.answer("✍️ Отправь обычный текст.")
            return True
        if state == "ref_text":
            content.set_referral_text(message.text)
            label = "рефералки"
        else:
            content.set_bot_info_text(message.text)
            label = "информации о боте"
        admin_edit_state.pop(uid, None)
        await message.answer(f"✅ Текст {label} сохранён.", reply_markup=admin_menu())
        return True
    if state in ("ref_image", "bot_info_image"):
        if not message.photo:
            await message.answer("🖼 Отправь изображение именно как фото. Размер должен быть ровно 630×360.")
            return True
        photo = message.photo[-1]
        if photo.width != 630 or photo.height != 360:
            await message.answer(f"❌ Нужен размер 630×360. Сейчас: {photo.width}×{photo.height}.")
            return True
        if state == "ref_image":
            content.set_referral_image(photo.file_id)
            label = "рефералки"
        else:
            content.set_bot_info_image(photo.file_id)
            label = "информации о боте"
        admin_edit_state.pop(uid, None)
        await message.answer(f"✅ Картинка {label} сохранена.", reply_markup=admin_menu())
        return True
    return False


async def _mode_required(message: Message, mode: str) -> bool:
    if _selected(message.from_user.id, mode):
        return True
    current = selected_mode.get(message.from_user.id)
    if current:
        labels = {"video": "🎥 Видео → кружок", "photo": "🖼 Фото → кружок", "audio": "🎵 Аудио → голосовое", "file": "📁 Файл → конвертация", "transcribe": "📝 Расшифровка"}
        await message.answer(f"🎯 Сейчас выбрана функция: <b>{labels.get(current, current)}</b>.\n\nДля другой операции сначала выбери нужную функцию в меню.", reply_markup=mode_menu(current))
    else:
        await message.answer("🎯 <b>Сначала выбери функцию.</b>\n\nБез выбора режима бот ничего не обрабатывает.", reply_markup=menu(message.from_user.id))
    return False

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
    public = content.public_access if content else False
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=("🌐 Закрыть для всех" if public else "🌐 Открыть для всех"), callback_data="admin_public_toggle")],
        [InlineKeyboardButton(text="🤝 Реферальная программа", callback_data="admin_referral")],
        [InlineKeyboardButton(text="ℹ️ Информация о боте", callback_data="admin_bot_info")],
        [InlineKeyboardButton(text="➕ Выдать доступ", callback_data="admin_add")],
        [InlineKeyboardButton(text="➖ Забрать доступ", callback_data="admin_remove")],
        [InlineKeyboardButton(text="🚫 Заблокировать", callback_data="admin_block")],
        [InlineKeyboardButton(text="👑 Назначить админа", callback_data="admin_promote")],
        [InlineKeyboardButton(text="📋 Пользователи", callback_data="admin_users")]
    ])


@router.message(F.text == "❌ Сбросить функцию")
async def reset_mode(message: Message):
    if not _allowed(message.from_user.id):
        return await message.answer("🔒 Доступ закрыт.")
    selected_mode.pop(message.from_user.id, None)
    admin_edit_state.pop(message.from_user.id, None)
    await message.answer("🏠 <b>Функция сброшена.</b>\n\nТеперь сначала выбери нужную функцию.", reply_markup=menu(message.from_user.id))


@router.message(F.text == "🎥 Видео → кружок")
async def select_video_mode(message: Message):
    if _allowed(message.from_user.id):
        selected_mode[message.from_user.id] = "video"
        await message.answer("🎥 <b>Видео → кружок</b>\n\nТеперь отправь видео. Другие типы файлов не обрабатываются.", reply_markup=menu(message.from_user.id))

@router.message(F.text == "🖼 Фото → кружок")
async def select_photo_mode(message: Message):
    if _allowed(message.from_user.id):
        selected_mode[message.from_user.id] = "photo"
        await message.answer("🖼 <b>Фото → кружок</b>\n\nТеперь отправь изображение. Другие типы файлов не обрабатываются.", reply_markup=menu(message.from_user.id))

@router.message(F.text == "🎵 Аудио → голосовое")
async def select_audio_mode(message: Message):
    if _allowed(message.from_user.id):
        selected_mode[message.from_user.id] = "audio"
        await message.answer("🎵 <b>Аудио → голосовое</b>\n\nТеперь отправь аудио или музыку.", reply_markup=menu(message.from_user.id))

@router.message(F.text == "📁 Файл → конвертация")
async def select_file_mode(message: Message):
    if _allowed(message.from_user.id):
        selected_mode[message.from_user.id] = "file"
        await message.answer("📁 <b>Файл → конвертация</b>\n\nТеперь отправь аудио или видео как файл.", reply_markup=menu(message.from_user.id))

@router.message(F.text == "📝 Расшифровка")
async def select_transcribe_mode(message: Message):
    if _allowed(message.from_user.id):
        selected_mode[message.from_user.id] = "transcribe"
        await message.answer("📝 <b>Расшифровка</b>\n\nТеперь отправь голосовое, кружок, видео или аудио.", reply_markup=menu(message.from_user.id))

@router.message(F.text == "👤 Профиль")
async def profile(message: Message):
    if not _allowed(message.from_user.id):
        return await message.answer("🔒 Доступ закрыт.")
    uid = message.from_user.id
    mode_labels = {"video":"🎥 Видео → кружок","photo":"🖼 Фото → кружок","audio":"🎵 Аудио → голосовое","file":"📁 Файл → конвертация","transcribe":"📝 Расшифровка"}
    mode = mode_labels.get(selected_mode.get(uid), "Не выбрана")
    q = {"economy":"Эконом","standard":"Стандарт","maximum":"Максимум"}.get(quality.get(uid, "maximum"), "Максимум")
    role = "👑 Администратор" if access.admin(uid) else "👤 Пользователь"
    me = await message.bot.get_me()
    referral_link = f"https://t.me/{me.username}?start=ref_{uid}"
    referrals = access.referral_count(uid)
    await message.answer(
        f"👤 <b>Профиль</b>\n\n🆔 ID: <code>{uid}</code>\n{role}\n\n"
        f"🎯 Функция: <b>{mode}</b>\n🎚 Качество: <b>{q}</b>\n🧹 Автоудаление: <b>включено</b>\n\n"
        f"🤝 <b>Рефералы:</b> {referrals}\n🔗 <code>{referral_link}</code>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🤝 Поделиться реферальной ссылкой", url=f"https://t.me/share/url?url={referral_link}")]
        ])
    )

@router.message(F.text == "ℹ️ О боте")
async def bot_info_button(message: Message):
    if not _allowed(message.from_user.id):
        return await message.answer("🔒 Доступ закрыт.")
    text = content.get("bot_info_text", "ℹ️ <b>AVYX VS</b>")
    image = content.get("bot_info_image")
    if image:
        await message.answer_photo(image, caption=text)
    else:
        await message.answer(text, reply_markup=menu(message.from_user.id))


@router.message(F.text == "⚙️ Настройки")
async def settings_button(message: Message):
    if not _allowed(message.from_user.id):
        return await message.answer("🔒 Доступ закрыт.")
    await message.answer("⚙️ <b>Настройки AVYX VS</b>\n\nВыбери нужный параметр:", reply_markup=settings_menu(message.from_user.id))

@router.message(F.text == "👑 Админ-панель")
async def admin_button(message: Message):
    if not access.admin(message.from_user.id):
        return await message.answer("🔒 Доступ закрыт.")
    await message.answer("👑 <b>Админ-панель AVYX VS</b>", reply_markup=admin_menu())

@router.callback_query(F.data.startswith("mode:"))
async def mode_select_callback(callback: CallbackQuery):
    if not _allowed(callback.from_user.id):
        return await callback.answer("Доступ закрыт", show_alert=True)
    mode = callback.data.split(":", 1)[1]
    selected_mode[callback.from_user.id] = mode
    await callback.answer("Функция выбрана")
    texts = {
        "video": "🎥 <b>Видео → кружок</b>\n\nТеперь отправь видео. Другие типы файлов будут отклонены.",
        "photo": "🖼 <b>Фото → кружок</b>\n\nТеперь отправь изображение. Другие типы файлов будут отклонены.",
        "audio": "🎵 <b>Аудио → голосовое</b>\n\nТеперь отправь аудио или музыку. Другие типы файлов будут отклонены.",
        "file": "📁 <b>Файл → конвертация</b>\n\nТеперь отправь аудио или видео именно как файл.",
        "transcribe": "📝 <b>Расшифровка</b>\n\nТеперь отправь голосовое, кружок, видео или аудио — бот преобразует речь в текст.",
    }
    await callback.message.edit_text(texts[mode] + "\n\n🔒 Пока эта функция выбрана, другие типы файлов не обрабатываются.", reply_markup=mode_menu(mode))

@router.message(Command("text"))
async def text_command(message: Message, bot):
    if not _allowed(message.from_user.id):
        return await message.answer("🔒 Доступ закрыт.")
    if not await _mode_required(message, "transcribe"):
        return
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
    uid = callback.from_user.id
    data = callback.data
    if data == "admin_users":
        return await callback.message.answer("📋 Пользователи:\n" + ("\n".join(map(str, access.list_users())) or "Нет пользователей"), reply_markup=admin_menu())
    if data == "admin_public_toggle":
        content.set_public_access(not content.public_access)
        state = "открыт для всех" if content.public_access else "закрыт, доступ только по приглашению"
        return await callback.message.edit_text(f"🌐 <b>Доступ изменён</b>\n\nСейчас бот <b>{state}</b>.", reply_markup=admin_menu())
    if data == "admin_referral":
        img = "установлена" if content.get("referral_image") else "не установлена"
        return await callback.message.edit_text(
            f"🤝 <b>Реферальная программа</b>\n\n📝 Текст: установлен\n🖼 Картинка 630×360: {img}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✏️ Изменить текст", callback_data="admin_ref_text")],
                [InlineKeyboardButton(text="🖼 Изменить картинку", callback_data="admin_ref_image")],
                [InlineKeyboardButton(text="🗑 Удалить картинку", callback_data="admin_ref_image_clear")],
                [InlineKeyboardButton(text="⬅️ Админка", callback_data="admin_back")]
            ])
        )
    if data == "admin_bot_info":
        img = "установлена" if content.get("bot_info_image") else "не установлена"
        return await callback.message.edit_text(
            f"ℹ️ <b>Информация о боте</b>\n\n📝 Текст: установлен\n🖼 Картинка 630×360: {img}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✏️ Изменить текст", callback_data="admin_info_text")],
                [InlineKeyboardButton(text="🖼 Изменить картинку", callback_data="admin_info_image")],
                [InlineKeyboardButton(text="🗑 Удалить картинку", callback_data="admin_info_image_clear")],
                [InlineKeyboardButton(text="⬅️ Админка", callback_data="admin_back")]
            ])
        )
    if data == "admin_ref_text":
        admin_edit_state[uid] = "ref_text"
        return await callback.message.answer("✍️ Отправь новый текст рефералки одним сообщением.")
    if data == "admin_ref_image":
        admin_edit_state[uid] = "ref_image"
        return await callback.message.answer("🖼 Отправь картинку рефералки как фото ровно 630×360.")
    if data == "admin_ref_image_clear":
        content.set_referral_image(None)
        return await callback.message.answer("✅ Картинка рефералки удалена.", reply_markup=admin_menu())
    if data == "admin_info_text":
        admin_edit_state[uid] = "bot_info_text"
        return await callback.message.answer("✍️ Отправь новый текст информации о боте одним сообщением.")
    if data == "admin_info_image":
        admin_edit_state[uid] = "bot_info_image"
        return await callback.message.answer("🖼 Отправь картинку информации о боте как фото ровно 630×360.")
    if data == "admin_info_image_clear":
        content.set_bot_info_image(None)
        return await callback.message.answer("✅ Картинка информации о боте удалена.", reply_markup=admin_menu())
    if data == "admin_back":
        return await callback.message.edit_text("👑 <b>Админ-панель AVYX VS</b>", reply_markup=admin_menu())
    prompts = {
        "admin_add": "➕ Команда: <code>/add ID</code>",
        "admin_remove": "➖ Команда: <code>/remove ID</code>",
        "admin_block": "🚫 Команда: <code>/block ID</code>",
        "admin_promote": "👑 Команда: <code>/promote ID</code>"
    }
    await callback.message.answer(prompts.get(data, "Неизвестная команда."))


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
    if not _allowed(callback.from_user.id):
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
    if not _allowed(callback.from_user.id):
        return await callback.answer("Доступ закрыт", show_alert=True)
    await callback.answer()
    current = photo_duration.get(callback.from_user.id, 10)
    await callback.message.edit_text(
        "🖼 <b>Длительность фото-кружка</b>\n\nСейчас: <b>" + str(current) + " сек</b>",
        reply_markup=photo_settings_menu(current)
    )

@router.callback_query(F.data == "settings_menu")
async def settings_callback(callback: CallbackQuery):
    if not _allowed(callback.from_user.id):
        return await callback.answer("Доступ закрыт", show_alert=True)
    await callback.answer()
    await callback.message.edit_text(
        "⚙️ <b>Настройки AVYX VS</b>\n\nВыбери нужный параметр:",
        reply_markup=settings_menu(callback.from_user.id)
    )

@router.callback_query(F.data == "quality_settings")
async def quality_settings_callback(callback: CallbackQuery):
    if not _allowed(callback.from_user.id):
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
    if not _allowed(callback.from_user.id):
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
    if not _allowed(callback.from_user.id):
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
    if not _allowed(callback.from_user.id):
        return await callback.answer("Доступ закрыт", show_alert=True)
    await callback.answer()
    await callback.message.edit_text(WELCOME, reply_markup=menu(callback.from_user.id))

@router.callback_query(F.data.endswith("_help"))
async def menu_help(callback: CallbackQuery):
    if not _allowed(callback.from_user.id):
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
    "Сначала выбери функцию в меню ниже, затем отправь соответствующий файл.\n\n"
    "🔒 Без выбора функции файлы не обрабатываются.\n"
    "🧹 Временные файлы после обработки удаляются."
)

@router.message(CommandStart())
async def start(message: Message):
    uid = message.from_user.id
    args = (message.text or "").split(maxsplit=1)
    referrer = None
    if len(args) > 1 and args[1].startswith("ref_"):
        try:
            referrer = int(args[1][4:])
        except ValueError:
            referrer = None
    if content.public_access:
        access.register_user(uid)
    if referrer and referrer != uid and _allowed(uid):
        if access.add_referral(referrer, uid):
            ref_text = content.get("referral_text", "")
            ref_image = content.get("referral_image")
            if ref_image:
                await message.answer_photo(ref_image, caption=ref_text)
            elif ref_text:
                await message.answer(ref_text)
    if not _allowed(uid):
        return await message.answer("🔒 Доступ закрыт. Обратитесь к администратору AVYX VS.")
    await message.answer(WELCOME, reply_markup=menu(uid))

@router.message(Command("help"))
async def help_cmd(message: Message):
    if not _allowed(message.from_user.id): return await message.answer('🔒 Доступ закрыт.')
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
    if await _admin_input(message, bot):
        return
    if not _allowed(message.from_user.id): return await message.answer("🔒 Доступ закрыт.")
    if not await _mode_required(message, "photo"):
        return
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
    if not _allowed(message.from_user.id): return await message.answer("🔒 Доступ закрыт.")
    if not await _mode_required(message, "video"):
        return
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
    if not _allowed(message.from_user.id): return await message.answer("🔒 Доступ закрыт.")
    if not await _mode_required(message, "audio"):
        return
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
    if not _allowed(message.from_user.id): return await message.answer("🔒 Доступ закрыт.")
    if not await _mode_required(message, "file"):
        return
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
    if not _allowed(message.from_user.id):
        return await message.answer("🔒 Доступ закрыт.")
    if not await _mode_required(message, "transcribe"):
        return
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
    if await _admin_input(message):
        return
    if not _allowed(message.from_user.id):
        return await message.answer("🔒 Доступ закрыт.")
    await message.answer("🎯 <b>Сначала выбери функцию в меню.</b>\n\nПока функция не выбрана, файлы не обрабатываются.", reply_markup=menu(message.from_user.id))
