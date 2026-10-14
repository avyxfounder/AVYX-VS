from pathlib import Path
from datetime import datetime, timezone
import asyncio
import time

from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message, FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton,
    CallbackQuery, ReplyKeyboardMarkup, ReplyKeyboardRemove, KeyboardButton,
    LabeledPrice, PreCheckoutQuery
)
from aiogram.enums import ChatAction

from .config import Settings
from .media import MediaError, probe, duration_seconds, make_video_note, make_image_video_note, make_voice, make_mp3
from .utils import new_job_dir, cleanup
from .access import AccessManager
from .content import BotContent, DEFAULT_WELCOME
from .transcribe import transcribe
from .usage import UsageManager, REFERRAL_BONUS_USES, SUPPORT_DAILY_LIMIT
from .billing import BillingManager, MONTH_SECONDS
from .publications import PublicationManager
from .support import SupportManager

router = Router()
settings: Settings | None = None
access: AccessManager | None = None
content: BotContent | None = None
usage: UsageManager | None = None
billing: BillingManager | None = None
publications: PublicationManager | None = None
support: SupportManager | None = None

selected_mode: dict[int, str] = {}
photo_duration: dict[int, int] = {}
quality: dict[int, str] = {}
admin_state: dict[int, str] = {}
user_state: dict[int, str] = {}
drafts: dict[int, dict] = {}

WELCOME = DEFAULT_WELCOME

MODES = {
    "video": "🎥 Видео → кружок",
    "photo": "🖼 Фото → кружок",
    "audio": "🎵 Аудио → голосовое",
    "video_mp3": "🎬 Видео → MP3",
    "circle_mp3": "⭕ Кружок → MP3",
    "circle_voice": "⭕ Кружок → голосовое",
    "voice_mp3": "🎙 Голос → MP3",
    "transcribe": "📝 Расшифровка",
}

def _allowed(user_id: int) -> bool:
    return bool(access and access.allowed(user_id, content.public_access if content else True))

def _is_admin(user_id: int) -> bool:
    return bool(access and access.admin(user_id))

def menu(user_id: int):
    rows = [
        [KeyboardButton(text="🎥 Видео → кружок"), KeyboardButton(text="🖼 Фото → кружок")],
        [KeyboardButton(text="🎵 Аудио → голосовое"), KeyboardButton(text="🎬 Видео → MP3")],
        [KeyboardButton(text="⭕ Кружок → MP3"), KeyboardButton(text="⭕ Кружок → голосовое")],
        [KeyboardButton(text="🎙 Голос → MP3"), KeyboardButton(text="📝 Расшифровка")],
        [KeyboardButton(text="👤 Профиль"), KeyboardButton(text="📰 Новости")],
        [KeyboardButton(text="🆘 Поддержка"), KeyboardButton(text="📢 Заказать рекламу")],
        [KeyboardButton(text="⭐ Подписка"), KeyboardButton(text="ℹ️ О боте")],
        [KeyboardButton(text="⚙️ Настройки")],
    ]
    if _is_admin(user_id):
        rows.append([KeyboardButton(text="👑 Админ-панель")])
    return ReplyKeyboardMarkup(
        keyboard=rows, resize_keyboard=True, is_persistent=True,
        input_field_placeholder="Выберите функцию…"
    )

def inline_back():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="back_menu")]
    ])

def mode_menu(current: str | None = None):
    rows = []
    for key, label in MODES.items():
        rows.append([
            InlineKeyboardButton(
                text=("✅ " if current == key else "") + label,
                callback_data=f"mode:{key}"
            )
        ])
    rows.append([InlineKeyboardButton(text="⚙️ Настройки", callback_data="settings_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def settings_menu(user_id: int):
    d = photo_duration.get(user_id, 10)
    q = {"economy": "Эконом", "standard": "Стандарт", "maximum": "Максимум"}.get(
        quality.get(user_id, "maximum"), "Максимум"
    )
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🖼 Фото-кружок: {d} сек", callback_data="photo_settings")],
        [InlineKeyboardButton(text=f"🎚 Качество: {q}", callback_data="quality_settings")],
        [InlineKeyboardButton(text="🎥 Видео-кружок: до 60 сек", callback_data="video_settings")],
        [InlineKeyboardButton(text="🧹 Временные файлы: автоудаление", callback_data="cleanup_info")],
        [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="back_menu")]
    ])

def admin_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📰 Новости", callback_data="admin_news")],
        [InlineKeyboardButton(text="📌 Чат для закрепов", callback_data="admin_set_pub_chat")],
        [InlineKeyboardButton(text="📢 Реклама", callback_data="admin_ads")],
        [InlineKeyboardButton(text="💳 Stars и подписка", callback_data="admin_billing")],
        [InlineKeyboardButton(text="🔐 Внешние реквизиты", callback_data="admin_external")],
        [InlineKeyboardButton(text="🖼 Приветствие", callback_data="admin_welcome")],
        [InlineKeyboardButton(text="🤝 Рефералка", callback_data="admin_referral")],
        [InlineKeyboardButton(text="ℹ️ Информация о боте", callback_data="admin_bot_info")],
        [InlineKeyboardButton(text="🌐 Доступ", callback_data="admin_access")],
        [InlineKeyboardButton(text="👥 Пользователи", callback_data="admin_users")],
    ])

def admin_billing_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"⭐ Подписка: {billing.subscription_price} Stars", callback_data="admin_set_sub_price")],
        [InlineKeyboardButton(text=f"🕐 Реклама 1 час: {billing.ad_price(3600)} ⭐", callback_data="admin_set_ad_3600")],
        [InlineKeyboardButton(text=f"🕕 Реклама 6 часов: {billing.ad_price(21600)} ⭐", callback_data="admin_set_ad_21600")],
        [InlineKeyboardButton(text=f"📅 Реклама 24 часа: {billing.ad_price(86400)} ⭐", callback_data="admin_set_ad_86400")],
        [InlineKeyboardButton(text=f"📅 Реклама 3 дня: {billing.ad_price(259200)} ⭐", callback_data="admin_set_ad_259200")],
        [InlineKeyboardButton(text=f"📅 Реклама 7 дней: {billing.ad_price(604800)} ⭐", callback_data="admin_set_ad_604800")],
        [InlineKeyboardButton(text="💰 Баланс Stars", callback_data="admin_stars_balance")],
        [InlineKeyboardButton(text="⬅️ Админка", callback_data="admin_back")],
    ])

def referral_admin_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Текст", callback_data="admin_ref_text")],
        [InlineKeyboardButton(text="🖼/🎬 Медиа", callback_data="admin_ref_media")],
        [InlineKeyboardButton(text="🗑 Удалить медиа", callback_data="admin_ref_media_clear")],
        [InlineKeyboardButton(text="⬅️ Админка", callback_data="admin_back")],
    ])

def welcome_admin_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Текст приветствия", callback_data="admin_welcome_text")],
        [InlineKeyboardButton(text="🖼/🎬 Медиа", callback_data="admin_welcome_media")],
        [InlineKeyboardButton(text="🗑 Удалить медиа", callback_data="admin_welcome_media_clear")],
        [InlineKeyboardButton(text="⬅️ Админка", callback_data="admin_back")],
    ])

async def _send_custom_media(bot, chat_id: int, text: str, media_type: str | None, file_id: str | None):
    if not file_id:
        return await bot.send_message(chat_id=chat_id, text=text or WELCOME)
    caption = (text or "")[:1024]
    if media_type == "photo":
        return await bot.send_photo(chat_id, file_id, caption=caption)
    if media_type == "video":
        return await bot.send_video(chat_id, file_id, caption=caption)
    if media_type == "animation":
        return await bot.send_animation(chat_id, file_id, caption=caption)
    return await bot.send_message(chat_id=chat_id, text=text or "")

async def _send_main_menu(message: Message, text: str | None = None):
    if not _allowed(message.from_user.id):
        return await message.answer("🔒 Доступ закрыт.")
    if text is None:
        text = content.get("welcome_text", WELCOME)
    await message.answer("⌨️ Меню обновлено.", reply_markup=ReplyKeyboardRemove())
    return await _send_custom_media(
        message.bot, message.chat.id, text,
        content.get("welcome_media_type"), content.get("welcome_media")
    )

def _mode_required(user_id: int, mode: str) -> bool:
    return selected_mode.get(user_id) == mode

async def _require_mode(message: Message, mode: str):
    if _mode_required(message.from_user.id, mode):
        return True
    current = selected_mode.get(message.from_user.id)
    if current:
        await message.answer(
            f"🎯 Сейчас выбрано: <b>{MODES.get(current, current)}</b>.\n"
            "Сначала выбери другую функцию.",
            reply_markup=mode_menu(current)
        )
    else:
        await message.answer("🎯 Сначала выбери функцию в меню.", reply_markup=menu(message.from_user.id))
    return False

async def _reserve(message: Message) -> bool:
    uid = message.from_user.id
    if _is_admin(uid):
        return True
    if not usage.can_use(uid):
        await message.answer(
            "⛔ Бесплатное использование закончилось.\n\n"
            f"🤝 За одного реферала вы получите +{REFERRAL_BONUS_USES} использований.\n"
            "⭐ Или подключите подписку без лимита."
        )
        return False
    if not usage.consume(uid):
        return False
    return True

async def _refund_if_needed(user_id: int, reserved: bool):
    if reserved and not _is_admin(user_id):
        usage.refund(user_id)

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
    if status:
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

def _admin_reply_ticket(message: Message):
    return bool(
        _is_admin(message.from_user.id)
        and message.reply_to_message
        and support.by_admin_message(message.reply_to_message.message_id)
    )

async def _handle_admin_ticket_reply(message: Message, bot):
    ticket = support.by_admin_message(message.reply_to_message.message_id)
    if not ticket or ticket.get("status") != "open":
        return False
    try:
        await bot.copy_message(
            chat_id=int(ticket["user_id"]),
            from_chat_id=message.chat.id,
            message_id=message.message_id
        )
        await message.answer(f"✅ Ответ по обращению {ticket['id']} отправлен пользователю.")
    except Exception as exc:
        await message.answer(f"❌ Не удалось отправить ответ: {exc}")
    return True

def _extract_media(message: Message):
    if message.photo:
        return "photo", message.photo[-1].file_id, message.caption or ""
    if message.video:
        return "video", message.video.file_id, message.caption or ""
    if message.animation:
        return "animation", message.animation.file_id, message.caption or ""
    return None, None, message.text or ""

async def _handle_user_state(message: Message, bot):
    uid = message.from_user.id
    state = user_state.get(uid)
    if not state:
        return False
    if state == "support":
        if not usage.register_support(uid):
            user_state.pop(uid, None)
            await message.answer(
                f"⛔ Лимит поддержки — {SUPPORT_DAILY_LIMIT} обращения в день. Попробуйте завтра.",
                reply_markup=menu(uid)
            )
            return True
        ticket_id = support.create(uid)
        caption = message.caption or message.text or "Без текста"
        media_type, file_id, _ = _extract_media(message)
        admin_text = (
            f"🆘 <b>Новое обращение {ticket_id}</b>\n\n"
            f"👤 Пользователь: <code>{uid}</code>\n"
            f"🕒 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n\n"
            f"{caption[:3000]}"
        )
        for admin_id in access.data.get("admins", []):
            sent = await _send_custom_media(
                bot, int(admin_id), admin_text if media_type else admin_text,
                media_type if media_type else None, file_id if media_type else None
            )
            support.set_admin_message(ticket_id, sent.message_id)
        user_state.pop(uid, None)
        await message.answer("✅ Обращение отправлено в поддержку.", reply_markup=menu(uid))
        return True
    if state == "ad_message":
        media_type, file_id, text = _extract_media(message)
        if media_type not in ("photo", "video", "animation"):
            await message.answer("📢 Отправь одним сообщением фото/видео/GIF с текстом в подписи.")
            return True
        drafts[uid] = {"media_type": media_type, "file_id": file_id, "text": text}
        user_state[uid] = "ad_duration"
        await message.answer(
            "⏱ Выберите срок размещения:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"1 час — {billing.ad_price(3600)} ⭐", callback_data="ad_duration:3600")],
                [InlineKeyboardButton(text=f"6 часов — {billing.ad_price(21600)} ⭐", callback_data="ad_duration:21600")],
                [InlineKeyboardButton(text=f"24 часа — {billing.ad_price(86400)} ⭐", callback_data="ad_duration:86400")],
                [InlineKeyboardButton(text=f"3 дня — {billing.ad_price(259200)} ⭐", callback_data="ad_duration:259200")],
                [InlineKeyboardButton(text=f"7 дней — {billing.ad_price(604800)} ⭐", callback_data="ad_duration:604800")],
            ])
        )
        return True
    if state == "news_message" and _is_admin(uid):
        media_type, file_id, text = _extract_media(message)
        item = publications.create_news(text, media_type, file_id)
        admin_state[uid] = f"news_pin:{item['id']}"
        await message.answer(
            "📰 Новость создана. Закрепить в указанном канале/группе публикаций?",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📌 С закрепом", callback_data=f"news_pin:{item['id']}:yes")],
                [InlineKeyboardButton(text="Без закрепа", callback_data=f"news_pin:{item['id']}:no")],
            ])
        )
        return True
    return False

async def _broadcast(bot, user_ids, text, media_type=None, file_id=None):
    sent = []
    for uid in user_ids:
        try:
            msg = await _send_custom_media(bot, int(uid), text, media_type, file_id)
            sent.append({"chat_id": int(uid), "message_id": msg.message_id})
        except Exception:
            pass
        await asyncio.sleep(0.03)
    return sent

async def _publish_news(bot, item, pin_requested: bool):
    sent = await _broadcast(
        bot, access.list_users(), item.get("text", ""),
        item.get("media_type"), item.get("file_id")
    )
    item["messages"] = sent
    pub_chat = content.get("publication_chat_id")
    if pub_chat:
        try:
            msg = await _send_custom_media(bot, int(pub_chat), item.get("text", ""), item.get("media_type"), item.get("file_id"))
            item["publication_message_id"] = msg.message_id
            item["publication_chat_id"] = int(pub_chat)
            if pin_requested:
                try:
                    await bot.pin_chat_message(chat_id=int(pub_chat), message_id=msg.message_id, disable_notification=True)
                    item["pinned"] = True
                except Exception:
                    pass
        except Exception:
            pass
    publications.save()

async def _publish_ad(bot, item):
    sent = await _broadcast(
        bot, access.list_users(), item.get("text", ""),
        item.get("media_type"), item.get("file_id")
    )
    item["messages"] = sent
    item["status"] = "active"
    item["approved_at"] = int(time.time())
    item["expires_at"] = int(time.time()) + int(item["duration_seconds"])
    pub_chat = content.get("publication_chat_id")
    if pub_chat:
        try:
            msg = await _send_custom_media(bot, int(pub_chat), item.get("text", ""), item.get("media_type"), item.get("file_id"))
            item["publication_message_id"] = msg.message_id
            item["publication_chat_id"] = int(pub_chat)
            if item.get("pin_requested"):
                try:
                    await bot.pin_chat_message(chat_id=int(pub_chat), message_id=msg.message_id, disable_notification=True)
                except Exception:
                    pass
        except Exception:
            pass
    publications.save()

@router.message(CommandStart())
async def start(message: Message):
    uid = message.from_user.id
    usage.ensure_user(uid)
    if content.public_access:
        access.register_user(uid)
    args = (message.text or "").split(maxsplit=1)
    referrer = None
    if len(args) > 1 and args[1].startswith("ref_"):
        try:
            referrer = int(args[1][4:])
        except ValueError:
            pass
    if referrer and referrer != uid and access.add_referral(referrer, uid):
        usage.add_uses(referrer, REFERRAL_BONUS_USES)
        try:
            await message.bot.send_message(
                referrer,
                f"🤝 Новый реферал! Вам начислено +{REFERRAL_BONUS_USES} использований."
            )
        except Exception:
            pass
        await _send_custom_media(
            message.bot, uid, content.get("referral_text", ""),
            content.get("referral_media_type"), content.get("referral_media")
        )
    if not _allowed(uid):
        return await message.answer("🔒 Доступ закрыт. Обратитесь к администратору AVYX VS.")
    await _send_main_menu(message)

@router.message(Command("menu"))
async def menu_cmd(message: Message):
    selected_mode.pop(message.from_user.id, None)
    user_state.pop(message.from_user.id, None)
    admin_state.pop(message.from_user.id, None)
    drafts.pop(message.from_user.id, None)
    await _send_main_menu(message)

@router.message(Command("help"))
async def help_cmd(message: Message):
    if not _allowed(message.from_user.id):
        return await message.answer("🔒 Доступ закрыт.")
    await message.answer(
        "🆘 <b>Помощь</b>\n\n"
        "🎁 Первый запуск даёт 1 бесплатное использование.\n"
        f"🤝 Реферал даёт +{REFERRAL_BONUS_USES}.\n"
        "⭐ Подписка снимает лимит на время действия.",
        reply_markup=menu(message.from_user.id)
    )

@router.message(Command("paysupport"))
async def paysupport(message: Message):
    await message.answer("💳 По вопросам оплаты напишите через раздел «🆘 Поддержка».")

@router.message(Command("admin"))
async def admin_cmd(message: Message):
    if not _is_admin(message.from_user.id):
        return await message.answer("🔒 Доступ закрыт.")
    await message.answer("👑 <b>Админ-панель AVYX VS</b>", reply_markup=admin_menu())

@router.message(F.text == "👑 Админ-панель")
async def admin_button(message: Message):
    return await admin_cmd(message)

@router.message(F.text == "🎥 Видео → кружок")
async def select_video(message: Message):
    selected_mode[message.from_user.id] = "video"
    await message.answer("🎥 Отправь видео до 60 секунд.", reply_markup=menu(message.from_user.id))

@router.message(F.text == "🖼 Фото → кружок")
async def select_photo(message: Message):
    selected_mode[message.from_user.id] = "photo"
    await message.answer("🖼 Отправь фото. Длительность задаётся в настройках.", reply_markup=menu(message.from_user.id))

@router.message(F.text == "🎵 Аудио → голосовое")
async def select_audio(message: Message):
    selected_mode[message.from_user.id] = "audio"
    await message.answer("🎵 Отправь аудио/музыку.", reply_markup=menu(message.from_user.id))

@router.message(F.text == "🎬 Видео → MP3")
async def select_video_mp3(message: Message):
    selected_mode[message.from_user.id] = "video_mp3"
    await message.answer("🎬 Отправь видео — получишь MP3.", reply_markup=menu(message.from_user.id))

@router.message(F.text == "⭕ Кружок → MP3")
async def select_circle_mp3(message: Message):
    selected_mode[message.from_user.id] = "circle_mp3"
    await message.answer("⭕ Отправь видео-кружок — получишь MP3.", reply_markup=menu(message.from_user.id))

@router.message(F.text == "⭕ Кружок → голосовое")
async def select_circle_voice(message: Message):
    selected_mode[message.from_user.id] = "circle_voice"
    await message.answer("⭕ Отправь видео-кружок — получишь голосовое.", reply_markup=menu(message.from_user.id))

@router.message(F.text == "🎙 Голос → MP3")
async def select_voice_mp3(message: Message):
    selected_mode[message.from_user.id] = "voice_mp3"
    await message.answer("🎙 Отправь голосовое — получишь MP3.", reply_markup=menu(message.from_user.id))

@router.message(F.text == "📝 Расшифровка")
async def select_transcribe(message: Message):
    selected_mode[message.from_user.id] = "transcribe"
    await message.answer("📝 Отправь голосовое, кружок, видео или аудио.", reply_markup=menu(message.from_user.id))

@router.message(F.text == "❌ Сбросить функцию")
async def reset_mode(message: Message):
    selected_mode.pop(message.from_user.id, None)
    user_state.pop(message.from_user.id, None)
    await message.answer("🏠 Функция сброшена.", reply_markup=menu(message.from_user.id))

@router.message(F.text == "👤 Профиль")
async def profile(message: Message):
    if not _allowed(message.from_user.id):
        return await message.answer("🔒 Доступ закрыт.")
    uid = message.from_user.id
    usage_profile = usage.profile(uid)
    referrals = access.referral_count(uid)
    me = await message.bot.get_me()
    referral_link = f"https://t.me/{me.username}?start=ref_{uid}"
    until = usage_profile["subscription_until"]
    sub_text = "не активна" if not until or until <= int(time.time()) else datetime.fromtimestamp(until, tz=timezone.utc).strftime("%d.%m.%Y %H:%M UTC")
    await message.answer(
        f"👤 <b>Профиль</b>\n\n🆔 <code>{uid}</code>\n"
        f"🎁 Осталось использований: <b>{usage_profile['uses']}</b>\n"
        f"📊 Всего использовано: <b>{usage_profile['total_used']}</b>\n"
        f"⭐ Подписка до: <b>{sub_text}</b>\n"
        f"🤝 Рефералов: <b>{referrals}</b>\n\n"
        f"🔗 <code>{referral_link}</code>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🤝 Поделиться ссылкой", url=f"https://t.me/share/url?url={referral_link}")]
        ])
    )

@router.message(F.text == "⭐ Подписка")
async def subscription(message: Message):
    if not _allowed(message.from_user.id):
        return await message.answer("🔒 Доступ закрыт.")
    uid = message.from_user.id
    usage.ensure_user(uid)
    payment_id = billing.create_payment("subscription", uid, billing.subscription_price)
    try:
        link = await message.bot.create_invoice_link(
            title="AVYX VS PRO",
            description="30 дней расширенного доступа без лимита обработок.",
            payload=f"sub:{payment_id}",
            currency="XTR",
            prices=[LabeledPrice(label="AVYX VS PRO", amount=billing.subscription_price)],
            subscription_period=MONTH_SECONDS,
        )
        await message.answer(
            f"⭐ <b>AVYX VS PRO</b>\n\nЦена: <b>{billing.subscription_price} Stars</b>.\n"
            "Подписка рассчитана на 30 дней.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"⭐ Оплатить {billing.subscription_price} Stars", url=link)]
            ])
        )
    except Exception:
        payment_id = billing.create_payment("subscription_once", uid, billing.subscription_price)
        await message.bot.send_invoice(
            chat_id=message.chat.id,
            title="AVYX VS PRO",
            description="30 дней расширенного доступа без лимита обработок.",
            payload=f"sub:{payment_id}",
            currency="XTR",
            prices=[LabeledPrice(label="AVYX VS PRO", amount=billing.subscription_price)],
            provider_token=""
        )

@router.message(F.text == "ℹ️ О боте")
async def bot_info(message: Message):
    if not _allowed(message.from_user.id):
        return await message.answer("🔒 Доступ закрыт.")
    await _send_custom_media(
        message.bot, message.chat.id,
        content.get("bot_info_text", ""),
        "photo" if content.get("bot_info_image") else None,
        content.get("bot_info_image")
    )

@router.message(F.text == "⚙️ Настройки")
async def settings_button(message: Message):
    await message.answer("⚙️ <b>Настройки</b>", reply_markup=settings_menu(message.from_user.id))

@router.message(F.text == "📰 Новости")
async def news_button(message: Message):
    items = publications.news(10)
    if not items:
        return await message.answer("📰 Пока новостей нет.", reply_markup=menu(message.from_user.id))
    for item in items:
        await _send_custom_media(
            message.bot, message.chat.id, item.get("text", ""),
            item.get("media_type"), item.get("file_id")
        )

@router.message(F.text == "🆘 Поддержка")
async def support_button(message: Message):
    uid = message.from_user.id
    left = max(0, SUPPORT_DAILY_LIMIT - usage.support_count_today(uid))
    if left <= 0:
        return await message.answer("⛔ Сегодня лимит поддержки уже исчерпан.")
    user_state[uid] = "support"
    await message.answer(
        f"🆘 Опишите проблему одним сообщением. Осталось обращений сегодня: <b>{left}</b>."
    )

@router.message(F.text == "📢 Заказать рекламу")
async def advertising_button(message: Message):
    if not _allowed(message.from_user.id):
        return await message.answer("🔒 Доступ закрыт.")
    user_state[message.from_user.id] = "ad_message"
    drafts.pop(message.from_user.id, None)
    await message.answer(
        "📢 <b>Заказ рекламы</b>\n\n"
        "Отправьте одним сообщением фото, видео или GIF с текстом в подписи. "
        "После этого выберите срок и оплату Stars."
    )

@router.callback_query(F.data.startswith("mode:"))
async def mode_callback(callback: CallbackQuery):
    mode = callback.data.split(":", 1)[1]
    if mode not in MODES:
        return await callback.answer("Недоступно", show_alert=True)
    selected_mode[callback.from_user.id] = mode
    await callback.answer("Функция выбрана")
    await callback.message.edit_text(f"✅ <b>{MODES[mode]}</b>\n\nОтправь нужный файл.", reply_markup=inline_back())

@router.callback_query(F.data == "settings_menu")
async def settings_callback(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text("⚙️ <b>Настройки</b>", reply_markup=settings_menu(callback.from_user.id))

@router.callback_query(F.data == "photo_settings")
async def photo_settings_callback(callback: CallbackQuery):
    current = photo_duration.get(callback.from_user.id, 10)
    values = [10, 20, 30, 40, 50, 60]
    rows = []
    for i in range(0, 6, 3):
        rows.append([
            InlineKeyboardButton(text=("✅ " if v == current else "") + f"{v} сек", callback_data=f"photo_duration:{v}")
            for v in values[i:i+3]
        ])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="settings_menu")])
    await callback.answer()
    await callback.message.edit_text("🖼 Длительность фото-кружка:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

@router.callback_query(F.data.startswith("photo_duration:"))
async def photo_duration_callback(callback: CallbackQuery):
    value = int(callback.data.split(":")[1])
    photo_duration[callback.from_user.id] = value
    await callback.answer(f"{value} сек")
    await callback.message.edit_text("⚙️ Настройки", reply_markup=settings_menu(callback.from_user.id))

@router.callback_query(F.data == "quality_settings")
async def quality_settings_callback(callback: CallbackQuery):
    current = quality.get(callback.from_user.id, "maximum")
    await callback.answer()
    await callback.message.edit_text(
        "🎚 <b>Качество</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=("✅ " if current == "economy" else "") + "Эконом", callback_data="quality:economy")],
            [InlineKeyboardButton(text=("✅ " if current == "standard" else "") + "Стандарт", callback_data="quality:standard")],
            [InlineKeyboardButton(text=("✅ " if current == "maximum" else "") + "Максимум", callback_data="quality:maximum")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="settings_menu")]
        ])
    )

@router.callback_query(F.data.startswith("quality:"))
async def quality_select(callback: CallbackQuery):
    value = callback.data.split(":", 1)[1]
    if value not in ("economy", "standard", "maximum"):
        return await callback.answer("Недопустимо", show_alert=True)
    quality[callback.from_user.id] = value
    await callback.answer("Сохранено")
    await callback.message.edit_text("⚙️ Настройки", reply_markup=settings_menu(callback.from_user.id))

@router.callback_query(F.data == "video_settings")
async def video_settings_callback(callback: CallbackQuery):
    await callback.answer("Видео-кружок: до 60 секунд.", show_alert=True)

@router.callback_query(F.data == "cleanup_info")
async def cleanup_info(callback: CallbackQuery):
    await callback.answer("Временные файлы удаляются после обработки.", show_alert=True)

@router.callback_query(F.data == "back_menu")
async def back_menu(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer(
        content.get("welcome_text", WELCOME),
        reply_markup=menu(callback.from_user.id)
    )

@router.callback_query(F.data.startswith("ad_duration:"))
async def ad_duration_callback(callback: CallbackQuery):
    uid = callback.from_user.id
    if user_state.get(uid) != "ad_duration" or uid not in drafts:
        return await callback.answer("Заявка устарела.", show_alert=True)
    seconds = int(callback.data.split(":")[1])
    user_state[uid] = f"ad_pin:{seconds}"
    await callback.answer()
    await callback.message.edit_text(
        "📌 Разместить с закрепом в канале/группе публикаций?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📌 Да", callback_data=f"ad_pin:{seconds}:yes")],
            [InlineKeyboardButton(text="Без закрепа", callback_data=f"ad_pin:{seconds}:no")],
        ])
    )

@router.callback_query(F.data.startswith("ad_pin:"))
async def ad_pin_callback(callback: CallbackQuery):
    uid = callback.from_user.id
    parts = callback.data.split(":")
    seconds = int(parts[1])
    pin = parts[2] == "yes"
    draft = drafts.get(uid)
    if not draft:
        return await callback.answer("Заявка устарела.", show_alert=True)
    order = publications.create_ad(uid, draft["text"], draft["media_type"], draft["file_id"], seconds, pin, billing.ad_price(seconds))
    payment_id = billing.create_payment("ad", uid, order["price"], {"order_id": order["id"]})
    publications.update_ad(order["id"], payment_id=payment_id)
    user_state.pop(uid, None)
    drafts.pop(uid, None)
    await callback.answer()
    await callback.message.edit_text(
        f"📢 Заказ <code>{order['id']}</code> готов к оплате.\n\n"
        f"Срок: <b>{seconds // 3600 if seconds % 3600 == 0 else seconds / 3600:g} ч.</b>\n"
        f"Цена: <b>{order['price']} Stars</b>.",
    )
    await callback.message.answer_invoice(
        title="Реклама AVYX VS",
        description=f"Размещение рекламы на выбранный срок: {order['price']} Stars.",
        payload=f"ad:{order['id']}",
        currency="XTR",
        prices=[LabeledPrice(label="Реклама", amount=order["price"])],
        provider_token=""
    )

@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery):
    await query.answer(ok=True)

@router.message(F.successful_payment)
async def successful_payment(message: Message):
    payment = message.successful_payment
    payload = payment.invoice_payload
    if payload.startswith("sub:"):
        payment_id = payload.split(":", 1)[1]
        billing.mark_paid(payment_id, payment.telegram_payment_charge_id)
        expiration = getattr(payment, "subscription_expiration_date", None)
        until = int(expiration) if expiration else int(time.time()) + MONTH_SECONDS
        usage.activate_subscription(message.from_user.id, until)
        await message.answer("✅ Оплата получена. ⭐ PRO активирован на 30 дней.")
        return
    if payload.startswith("ad:"):
        order_id = payload.split(":", 1)[1]
        order = publications.get_ad(order_id)
        if not order:
            return await message.answer("⚠️ Заказ не найден. Обратитесь в поддержку.")
        billing.mark_paid(order.get("payment_id", ""), payment.telegram_payment_charge_id)
        publications.update_ad(order_id, status="paid", paid_at=int(time.time()), charge_id=payment.telegram_payment_charge_id)
        await message.answer("✅ Оплата получена. Заказ передан на модерацию.")
        for admin_id in access.data.get("admins", []):
            await message.bot.send_message(
                int(admin_id),
                f"📢 <b>Оплаченная реклама</b> <code>{order_id}</code>\n"
                f"👤 <code>{order['user_id']}</code>\n"
                f"💰 {order['price']} Stars",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="✅ Разместить", callback_data=f"ad_approve:{order_id}")],
                    [InlineKeyboardButton(text="❌ Отклонить + возврат", callback_data=f"ad_reject:{order_id}")],
                ])
            )

@router.callback_query(F.data.startswith("ad_approve:"))
async def ad_approve(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        return await callback.answer("Доступ закрыт", show_alert=True)
    order_id = callback.data.split(":", 1)[1]
    order = publications.get_ad(order_id)
    if not order or order.get("status") != "paid":
        return await callback.answer("Заказ уже обработан.", show_alert=True)
    await _publish_ad(callback.bot, order)
    try:
        await callback.bot.send_message(order["user_id"], "✅ Реклама размещена.")
    except Exception:
        pass
    await callback.answer("Реклама размещена")
    await callback.message.edit_text(f"✅ Реклама <code>{order_id}</code> размещена.")

@router.callback_query(F.data.startswith("ad_reject:"))
async def ad_reject(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        return await callback.answer("Доступ закрыт", show_alert=True)
    order_id = callback.data.split(":", 1)[1]
    order = publications.get_ad(order_id)
    if not order or order.get("status") != "paid":
        return await callback.answer("Заказ уже обработан.", show_alert=True)
    refunded = False
    charge_id = order.get("charge_id")
    if charge_id:
        try:
            refunded = await callback.bot.refund_star_payment(
                user_id=int(order["user_id"]),
                telegram_payment_charge_id=charge_id
            )
        except Exception:
            refunded = False
    publications.update_ad(order_id, status="rejected", refunded=refunded)
    try:
        await callback.bot.send_message(order["user_id"], "❌ Реклама отклонена." + (" Stars возвращены." if refunded else " Для возврата обратитесь в поддержку."))
    except Exception:
        pass
    await callback.answer("Заказ отклонён")
    await callback.message.edit_text(f"❌ Реклама <code>{order_id}</code> отклонена.")

@router.callback_query(F.data.startswith("news_pin:"))
async def news_pin_callback(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        return await callback.answer("Доступ закрыт", show_alert=True)
    parts = callback.data.split(":")
    news_id = int(parts[1])
    pin_requested = len(parts) > 2 and parts[2] == "yes"
    item = publications.get_news(news_id)
    if not item:
        return await callback.answer("Новость не найдена.", show_alert=True)
    await _publish_news(callback.bot, item, pin_requested)
    await callback.answer("Опубликовано")
    await callback.message.edit_text(
        f"✅ Новость #{news_id} опубликована." + (" Закреп запрошен." if pin_requested else "")
    )
    admin_state.pop(callback.from_user.id, None)

@router.callback_query(F.data.startswith("admin_"))
async def admin_callback(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        return await callback.answer("Доступ закрыт", show_alert=True)
    await callback.answer()
    data = callback.data
    uid = callback.from_user.id
    if data == "admin_back":
        return await callback.message.edit_text("👑 <b>Админ-панель</b>", reply_markup=admin_menu())
    if data == "admin_users":
        users = access.list_users()
        return await callback.message.edit_text(
            "👥 <b>Пользователи</b>\n\n" + ("\n".join(map(str, users)) or "Нет"),
            reply_markup=admin_menu()
        )
    if data == "admin_access":
        return await callback.message.edit_text(
            f"🌐 Публичный доступ: <b>{'включён' if content.public_access else 'выключен'}</b>\n\n"
            "Команды: /add ID, /remove ID, /block ID, /promote ID",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🌐 Переключить", callback_data="admin_public_toggle")],
                [InlineKeyboardButton(text="⬅️ Админка", callback_data="admin_back")]
            ])
        )
    if data == "admin_public_toggle":
        content.set_public_access(not content.public_access)
        return await callback.message.edit_text("🌐 Доступ изменён.", reply_markup=admin_menu())
    if data == "admin_billing":
        return await callback.message.edit_text("💳 <b>Stars и цены</b>", reply_markup=admin_billing_menu())
    if data == "admin_set_sub_price":
        admin_state[uid] = "set_sub_price"
        return await callback.message.answer("Введите новую цену подписки в Stars:")
    if data.startswith("admin_set_ad_"):
        seconds = int(data.rsplit("_", 1)[1])
        admin_state[uid] = f"set_ad_price:{seconds}"
        return await callback.message.answer(f"Введите цену рекламы на {seconds // 3600} ч. в Stars:")
    if data == "admin_stars_balance":
        try:
            balance = await callback.bot.get_my_star_balance()
            return await callback.message.edit_text(f"💰 Баланс бота: <b>{balance.amount} Stars</b>", reply_markup=admin_billing_menu())
        except Exception as exc:
            return await callback.message.edit_text(f"⚠️ Не удалось получить баланс: {exc}", reply_markup=admin_billing_menu())
    if data == "admin_external":
        return await callback.message.edit_text(
            "🔐 <b>Внешние реквизиты</b>\n\n"
            "TON wallet: <code>" + (billing.data.get("ton_wallet") or "не задан") + "</code>\n"
            "TON Center key: <code>" + ("установлен" if billing.data.get("ton_api_key") else "не задан") + "</code>\n"
            "CryptoBot token: <code>" + ("установлен" if billing.data.get("cryptobot_token") else "не задан") + "</code>\n\n"
            "Для цифровых услуг внутри Telegram основной способ оплаты — Stars.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="👛 TON wallet", callback_data="admin_set_ton_wallet")],
                [InlineKeyboardButton(text="🔑 TON Center key", callback_data="admin_set_ton_key")],
                [InlineKeyboardButton(text="🤖 CryptoBot token", callback_data="admin_set_cryptobot")],
                [InlineKeyboardButton(text="⬅️ Админка", callback_data="admin_back")]
            ])
        )
    if data in ("admin_set_ton_wallet", "admin_set_ton_key", "admin_set_cryptobot"):
        admin_state[uid] = {
            "admin_set_ton_wallet": "set_ton_wallet",
            "admin_set_ton_key": "set_ton_key",
            "admin_set_cryptobot": "set_cryptobot",
        }[data]
        return await callback.message.answer("Отправьте значение одним сообщением.")
    if data == "admin_welcome":
        media = "не задано" if not content.get("welcome_media") else content.get("welcome_media_type")
        return await callback.message.edit_text(f"👋 <b>Приветствие</b>\nМедиа: {media}", reply_markup=welcome_admin_menu())
    if data == "admin_welcome_text":
        admin_state[uid] = "welcome_text"
        return await callback.message.answer("Отправьте новый текст приветствия.")
    if data == "admin_welcome_media":
        admin_state[uid] = "welcome_media"
        return await callback.message.answer("Отправьте фото, видео или GIF. Для фото нужен размер 640×360.")
    if data == "admin_welcome_media_clear":
        content.set_welcome_media(None, None)
        return await callback.message.answer("✅ Медиа приветствия удалено.", reply_markup=admin_menu())
    if data == "admin_referral":
        media = "не задано" if not content.get("referral_media") else content.get("referral_media_type")
        return await callback.message.edit_text(f"🤝 <b>Рефералка</b>\nМедиа: {media}", reply_markup=referral_admin_menu())
    if data == "admin_ref_text":
        admin_state[uid] = "referral_text"
        return await callback.message.answer("Отправьте новый текст рефералки.")
    if data == "admin_ref_media":
        admin_state[uid] = "referral_media"
        return await callback.message.answer("Отправьте фото, видео или GIF. Для фото нужен размер 640×360.")
    if data == "admin_ref_media_clear":
        content.set_referral_media(None, None)
        return await callback.message.answer("✅ Медиа рефералки удалено.", reply_markup=admin_menu())
    if data == "admin_bot_info":
        return await callback.message.edit_text(
            "ℹ️ <b>Информация о боте</b>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✏️ Текст", callback_data="admin_info_text")],
                [InlineKeyboardButton(text="🖼 Картинка 640×360", callback_data="admin_info_image")],
                [InlineKeyboardButton(text="🗑 Удалить картинку", callback_data="admin_info_image_clear")],
                [InlineKeyboardButton(text="⬅️ Админка", callback_data="admin_back")]
            ])
        )
    if data == "admin_info_text":
        admin_state[uid] = "bot_info_text"
        return await callback.message.answer("Отправьте новый текст.")
    if data == "admin_info_image":
        admin_state[uid] = "bot_info_image"
        return await callback.message.answer("Отправьте фото ровно 640×360.")
    if data == "admin_info_image_clear":
        content.set_bot_info_image(None)
        return await callback.message.answer("✅ Картинка удалена.", reply_markup=admin_menu())
    if data == "admin_set_pub_chat":
        admin_state[uid] = "set_pub_chat"
        return await callback.message.answer("Отправьте ID группы/канала для публикаций (например, -1001234567890). Бот должен быть администратором для закрепа.")
    if data == "admin_news":
        admin_state.pop(uid, None)
        buttons = [[InlineKeyboardButton(text="➕ Опубликовать новость", callback_data="admin_news_create")]]
        for item in publications.news(8):
            buttons.append([InlineKeyboardButton(text=f"🗑 Удалить #{item['id']}", callback_data=f"news_delete:{item['id']}")])
        buttons.append([InlineKeyboardButton(text="⬅️ Админка", callback_data="admin_back")])
        return await callback.message.edit_text("📰 <b>Новости</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    if data == "admin_news_create":
        admin_state[uid] = "news_message"
        return await callback.message.answer("Отправьте новость одним сообщением: текст или фото/видео/GIF с подписью.")
    if data == "admin_ads":
        pending = publications.pending_ads()
        rows = []
        for item in pending:
            rows.append([InlineKeyboardButton(text=f"✅ #{item['id']} {item['price']}⭐", callback_data=f"ad_approve:{item['id']}")])
            rows.append([InlineKeyboardButton(text=f"❌ Отклонить #{item['id']}", callback_data=f"ad_reject:{item['id']}")])
        rows.append([InlineKeyboardButton(text="⬅️ Админка", callback_data="admin_back")])
        return await callback.message.edit_text(
            "📢 <b>Реклама</b>\n\n" + ("Есть оплаченные заявки:" if pending else "Новых оплаченных заявок нет."),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)
        )
    if data in ("admin_ref_text","admin_ref_media","admin_ref_media_clear","admin_welcome"):
        return
    return await callback.message.edit_text("👑 <b>Админ-панель</b>", reply_markup=admin_menu())

@router.callback_query(F.data.startswith("news_delete:"))
async def news_delete(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        return await callback.answer("Доступ закрыт", show_alert=True)
    news_id = int(callback.data.split(":")[1])
    item = publications.get_news(news_id)
    if not item:
        return await callback.answer("Не найдено.", show_alert=True)
    for sent in item.get("messages", []):
        try:
            await callback.bot.delete_message(int(sent["chat_id"]), int(sent["message_id"]))
        except Exception:
            pass
    if item.get("publication_message_id") and item.get("publication_chat_id"):
        try:
            await callback.bot.unpin_chat_message(int(item["publication_chat_id"]), int(item["publication_message_id"]))
        except Exception:
            pass
        try:
            await callback.bot.delete_message(int(item["publication_chat_id"]), int(item["publication_message_id"]))
        except Exception:
            pass
    publications.delete_news_record(news_id)
    await callback.answer("Удалено")
    await callback.message.edit_text("📰 Новость удалена.", reply_markup=admin_menu())

@router.message(F.text.regexp(r"^/add\s+\d+$"))
async def add_user(message: Message):
    if _is_admin(message.from_user.id):
        access.add(int(message.text.split()[1]))
        usage.ensure_user(int(message.text.split()[1]))
        await message.answer("✅ Доступ выдан.")

@router.message(F.text.regexp(r"^/remove\s+\d+$"))
async def remove_user(message: Message):
    if _is_admin(message.from_user.id):
        access.remove(int(message.text.split()[1]))
        await message.answer("✅ Доступ забран.")

@router.message(F.text.regexp(r"^/block\s+\d+$"))
async def block_user(message: Message):
    if _is_admin(message.from_user.id):
        access.block(int(message.text.split()[1]))
        await message.answer("🚫 Пользователь заблокирован.")

@router.message(F.text.regexp(r"^/promote\s+\d+$"))
async def promote_user(message: Message):
    if _is_admin(message.from_user.id):
        access.promote(int(message.text.split()[1]))
        await message.answer("👑 Админ назначен.")

@router.message(F.photo)
async def photo_handler(message: Message, bot):
    if _admin_reply_ticket(message):
        return await _handle_admin_ticket_reply(message, bot)
    if await _handle_user_state(message, bot):
        return
    if _is_admin(message.from_user.id) and await _handle_admin_input(message):
        return
    if not _allowed(message.from_user.id):
        return await message.answer("🔒 Доступ закрыт.")
    if not await _require_mode(message, "photo"):
        return
    if not await _reserve(message):
        return
    reserved = not _is_admin(message.from_user.id)
    job = new_job_dir(settings.temp_dir)
    status = await _status(message, "⏳ " + _progress_bar(5) + " 5%")
    try:
        src, dst = job / "input.jpg", job / "video_note.mp4"
        await bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_VIDEO)
        await _download(bot, message.photo[-1].file_id, src)
        duration = photo_duration.get(message.from_user.id, 10)
        await _status_update(status, "⚙️ Создаю кружок " + _progress_bar(55))
        await make_image_video_note(src, dst, duration, quality.get(message.from_user.id, "maximum"))
        if _too_large(dst):
            raise MediaError("Результат больше лимита отправки.")
        await message.answer_video_note(FSInputFile(dst), duration=duration, length=640)
        await _status_update(status, "✅ Готово " + _progress_bar(100))
    except Exception as exc:
        await _refund_if_needed(message.from_user.id, reserved)
        await _error(message, exc)
    finally:
        cleanup(job)

@router.message(F.video)
async def video_handler(message: Message, bot):
    if await _handle_admin_ticket_reply(message, bot):
        return
    if await _handle_user_state(message, bot):
        return
    if _is_admin(message.from_user.id) and await _handle_admin_input(message):
        return
    if not _allowed(message.from_user.id):
        return await message.answer("🔒 Доступ закрыт.")
    mode = selected_mode.get(message.from_user.id)
    if mode == "transcribe":
        return await _transcribe_message(message, bot, message.video.file_id, "video.mp4")
    if mode == "video":
        return await _video_to_circle(message, bot, message.video.file_id)
    if mode == "video_mp3":
        return await _media_to_mp3(message, bot, message.video.file_id, "video.mp4")
    return await message.answer("🎯 Выберите «Видео → кружок», «Видео → MP3» или «Расшифровка».")

async def _video_to_circle(message: Message, bot, file_id: str):
    if not await _reserve(message):
        return
    reserved = not _is_admin(message.from_user.id)
    job = new_job_dir(settings.temp_dir)
    status = await _status(message, "⏳ " + _progress_bar(5) + " 5%")
    try:
        src, dst = job / "input", job / "video_note.mp4"
        await bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_VIDEO)
        await _download(bot, file_id, src)
        info = await probe(src)
        duration = duration_seconds(info)
        if duration > 60.5:
            raise MediaError("Видео-кружок ограничен 60 секундами.")
        await _status_update(status, "⚙️ Конвертирую " + _progress_bar(60))
        await make_video_note(src, dst, quality.get(message.from_user.id, "maximum"))
        if _too_large(dst):
            raise MediaError("Результат больше лимита отправки.")
        await message.answer_video_note(FSInputFile(dst), duration=max(1, min(60, round(duration))), length=640)
        await _status_update(status, "✅ Готово " + _progress_bar(100))
    except Exception as exc:
        await _refund_if_needed(message.from_user.id, reserved)
        await _error(message, exc)
    finally:
        cleanup(job)

async def _media_to_mp3(message: Message, bot, file_id: str, filename: str):
    if not await _reserve(message):
        return
    reserved = not _is_admin(message.from_user.id)
    job = new_job_dir(settings.temp_dir)
    status = await _status(message, "⏳ " + _progress_bar(5) + " 5%")
    try:
        src, dst = job / filename, job / "result.mp3"
        await bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_DOCUMENT)
        await _download(bot, file_id, src)
        await _status_update(status, "🎵 Извлекаю аудио " + _progress_bar(65))
        await make_mp3(src, dst)
        if _too_large(dst):
            raise MediaError("Результат больше лимита отправки.")
        await message.answer_document(FSInputFile(dst), caption="🎵 MP3 готов.")
        await _status_update(status, "✅ Готово " + _progress_bar(100))
    except Exception as exc:
        await _refund_if_needed(message.from_user.id, reserved)
        await _error(message, exc)
    finally:
        cleanup(job)

async def _circle_to_voice(message: Message, bot):
    if not await _reserve(message):
        return
    reserved = not _is_admin(message.from_user.id)
    job = new_job_dir(settings.temp_dir)
    status = await _status(message, "⏳ " + _progress_bar(5) + " 5%")
    try:
        src, dst = job / "circle.mp4", job / "voice.ogg"
        await _download(bot, message.video_note.file_id, src)
        await _status_update(status, "🎙 Создаю голосовое " + _progress_bar(65))
        await make_voice(src, dst)
        if _too_large(dst):
            raise MediaError("Результат больше лимита отправки.")
        await message.answer_voice(FSInputFile(dst))
        await _status_update(status, "✅ Готово " + _progress_bar(100))
    except Exception as exc:
        await _refund_if_needed(message.from_user.id, reserved)
        await _error(message, exc)
    finally:
        cleanup(job)

@router.message(F.audio)
async def audio_handler(message: Message, bot):
    if await _handle_user_state(message, bot):
        return
    if _is_admin(message.from_user.id) and await _handle_admin_input(message):
        return
    if not _allowed(message.from_user.id):
        return await message.answer("🔒 Доступ закрыт.")
    mode = selected_mode.get(message.from_user.id)
    if mode == "transcribe":
        return await _transcribe_message(message, bot, message.audio.file_id, "audio.mp3")
    if mode == "audio":
        if not await _reserve(message):
            return
        reserved = not _is_admin(message.from_user.id)
        job = new_job_dir(settings.temp_dir)
        status = await _status(message, "⏳ " + _progress_bar(5) + " 5%")
        try:
            src, dst = job / "input", job / "voice.ogg"
            await _download(bot, message.audio.file_id, src)
            await _status_update(status, "🎵 Создаю голосовое " + _progress_bar(65))
            await make_voice(src, dst)
            await message.answer_voice(FSInputFile(dst))
            await _status_update(status, "✅ Готово " + _progress_bar(100))
        except Exception as exc:
            await _refund_if_needed(message.from_user.id, reserved)
            await _error(message, exc)
        finally:
            cleanup(job)
        return
    await message.answer("🎯 Выберите «Аудио → голосовое» или «Расшифровка».")

@router.message(F.voice)
async def voice_handler(message: Message, bot):
    if await _handle_user_state(message, bot):
        return
    if _is_admin(message.from_user.id) and await _handle_admin_input(message):
        return
    if not _allowed(message.from_user.id):
        return await message.answer("🔒 Доступ закрыт.")
    if selected_mode.get(message.from_user.id) == "transcribe":
        return await _transcribe_message(message, bot, message.voice.file_id, "voice.ogg")
    if selected_mode.get(message.from_user.id) == "voice_mp3":
        return await _media_to_mp3(message, bot, message.voice.file_id, "voice.ogg")
    await message.answer("🎯 Выберите «Голос → MP3» или «Расшифровка».")

@router.message(F.video_note)
async def video_note_handler(message: Message, bot):
    if await _handle_user_state(message, bot):
        return
    if _is_admin(message.from_user.id) and await _handle_admin_input(message):
        return
    if not _allowed(message.from_user.id):
        return await message.answer("🔒 Доступ закрыт.")
    mode = selected_mode.get(message.from_user.id)
    if mode == "transcribe":
        return await _transcribe_message(message, bot, message.video_note.file_id, "video_note.mp4")
    if mode == "circle_mp3":
        return await _media_to_mp3(message, bot, message.video_note.file_id, "circle.mp4")
    if mode == "circle_voice":
        return await _circle_to_voice(message, bot)
    await message.answer("🎯 Выберите функцию для видео-кружка.")

async def _transcribe_message(message: Message, bot, file_id: str, filename: str):
    if not await _reserve(message):
        return
    reserved = not _is_admin(message.from_user.id)
    job = new_job_dir(settings.temp_dir)
    status = await _status(message, "📝 " + _progress_bar(10) + " 10%")
    try:
        src = job / filename
        await _download(bot, file_id, src)
        await _status_update(status, "🧠 Распознаю речь " + _progress_bar(70))
        text = await transcribe(src)
        if len(text) > 3800:
            for i in range(0, len(text), 3800):
                await message.answer("📝 " + text[i:i+3800])
        else:
            await message.answer("📝 <b>Расшифровка</b>\n\n" + text)
        await _status_update(status, "✅ Готово " + _progress_bar(100))
    except Exception as exc:
        await _refund_if_needed(message.from_user.id, reserved)
        await _error(message, exc)
    finally:
        cleanup(job)

async def _handle_admin_input(message: Message):
    uid = message.from_user.id
    state = admin_state.get(uid)
    if not state:
        return False
    if state == "news_message":
        if not _is_admin(uid):
            return False
        media_type, file_id, text = _extract_media(message)
        item = publications.create_news(text, media_type, file_id)
        admin_state[uid] = f"news_pin:{item['id']}"
        await message.answer(
            "📰 Новость создана. Закрепить её в чате публикаций?",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📌 С закрепом", callback_data=f"news_pin:{item['id']}:yes")],
                [InlineKeyboardButton(text="Без закрепа", callback_data=f"news_pin:{item['id']}:no")],
            ])
        )
        return True
    if state == "welcome_text":
        if not message.text:
            await message.answer("Нужен текст.")
            return True
        content.set_welcome_text(message.text)
        admin_state.pop(uid, None)
        await message.answer("✅ Приветствие сохранено.", reply_markup=admin_menu())
        return True
    if state in ("welcome_media", "referral_media", "bot_info_image"):
        media_type, file_id, _ = _extract_media(message)
        if media_type != "photo":
            if state in ("welcome_media", "referral_media") and media_type in ("video", "animation"):
                if state == "welcome_media":
                    content.set_welcome_media(media_type, file_id)
                else:
                    content.set_referral_media(media_type, file_id)
                admin_state.pop(uid, None)
                await message.answer("✅ Медиа сохранено.", reply_markup=admin_menu())
                return True
            await message.answer("Нужно фото, видео или GIF.")
            return True
        photo = message.photo[-1]
        if photo.width != 640 or photo.height != 360:
            await message.answer(f"❌ Размер фото должен быть 640×360. Сейчас {photo.width}×{photo.height}.")
            return True
        if state == "welcome_media":
            content.set_welcome_media("photo", file_id)
        elif state == "referral_media":
            content.set_referral_media("photo", file_id)
        else:
            content.set_bot_info_image(file_id)
        admin_state.pop(uid, None)
        await message.answer("✅ Медиа сохранено.", reply_markup=admin_menu())
        return True
    if state == "welcome_media":
        return False
    if state == "referral_text":
        if not message.text:
            await message.answer("Нужен текст.")
            return True
        content.set_referral_text(message.text)
        admin_state.pop(uid, None)
        await message.answer("✅ Текст рефералки сохранён.", reply_markup=admin_menu())
        return True
    if state == "bot_info_text":
        if not message.text:
            await message.answer("Нужен текст.")
            return True
        content.set_bot_info_text(message.text)
        admin_state.pop(uid, None)
        await message.answer("✅ Информация сохранена.", reply_markup=admin_menu())
        return True
    if state == "set_sub_price" or state.startswith("set_ad_price:"):
        try:
            value = int((message.text or "").strip())
            if value < 1 or value > 10000:
                raise ValueError
        except ValueError:
            await message.answer("Введите целое число от 1 до 10000.")
            return True
        if state == "set_sub_price":
            billing.set_subscription_price(value)
        else:
            billing.set_ad_price(int(state.split(":")[1]), value)
        admin_state.pop(uid, None)
        await message.answer("✅ Цена сохранена.", reply_markup=admin_billing_menu())
        return True
    if state == "set_pub_chat":
        try:
            chat_id = int((message.text or "").strip())
        except ValueError:
            await message.answer("Нужен числовой chat ID.")
            return True
        content.set_publication_chat_id(chat_id)
        admin_state.pop(uid, None)
        await message.answer("✅ Чат публикаций сохранён.", reply_markup=admin_menu())
        return True
    if state == "set_ton_wallet":
        billing.set_external(ton_wallet=message.text or "")
        admin_state.pop(uid, None)
        await message.answer("✅ TON wallet сохранён.", reply_markup=admin_menu())
        return True
    if state == "set_ton_key":
        billing.set_external(ton_api_key=message.text or "")
        admin_state.pop(uid, None)
        await message.answer("✅ TON Center key сохранён.", reply_markup=admin_menu())
        return True
    if state == "set_cryptobot":
        billing.set_external(cryptobot_token=message.text or "")
        admin_state.pop(uid, None)
        await message.answer("✅ CryptoBot token сохранён.", reply_markup=admin_menu())
        return True
    return False

@router.message(F.document)
async def document_removed(message: Message, bot):
    if await _handle_user_state(message, bot):
        return
    if _is_admin(message.from_user.id) and await _handle_admin_input(message):
        return
    await message.answer("📁 Раздел «Файл → конвертация» удалён. Используйте обычные видео, аудио, голосовые или кружки.")

@router.message()
async def fallback(message: Message):
    if _admin_reply_ticket(message):
        return await _handle_admin_ticket_reply(message, message.bot)
    if _is_admin(message.from_user.id) and await _handle_admin_input(message):
        return
    if await _handle_user_state(message, message.bot):
        return
    if not _allowed(message.from_user.id):
        return await message.answer("🔒 Доступ закрыт.")
    await message.answer("🎯 Выберите функцию в меню.", reply_markup=menu(message.from_user.id))
