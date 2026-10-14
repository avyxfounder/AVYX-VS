import json
from pathlib import Path

DEFAULT_REFERRAL_TEXT = (
    "🤝 <b>Приглашаю тебя в AVYX VS!</b>\n\n"
    "Медиа-бот для видео, фото, аудио, конвертации и расшифровки.\n\n"
    "🎁 За каждого нового пользователя по вашей ссылке — <b>+10 использований</b>."
)
DEFAULT_BOT_INFO = (
    "ℹ️ <b>AVYX VS</b>\n\n"
    "Универсальный Telegram-бот для работы с медиа.\n\n"
    "🎥 Видео → кружок\n"
    "🖼 Фото → кружок\n"
    "🎵 Аудио → голосовое\n"
    "🎬 Видео → MP3\n"
    "⭕ Кружок → MP3 / голосовое\n"
    "🎙 Голос → MP3\n"
    "📝 Расшифровка речи\n\n"
    "⚡ Быстро, удобно и всё в одном боте.\n"
    "🧹 Временные файлы удаляются автоматически."
)
DEFAULT_WELCOME = (
    "👋 <b>Добро пожаловать в AVYX VS!</b>\n\n"
    "🎬 Конвертируй видео и аудио, создавай кружки и получай расшифровку.\n\n"
    "🎁 Первый запуск — бесплатно.\n"
    "🤝 За каждого приглашённого пользователя — <b>+10 использований</b>.\n\n"
    "Выбери нужную функцию в меню ниже."
)

class BotContent:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data = {
            "public_access": True,
            "welcome_text": DEFAULT_WELCOME,
            "welcome_media": None,
            "welcome_media_type": None,
            "referral_text": DEFAULT_REFERRAL_TEXT,
            "referral_media": None,
            "referral_media_type": None,
            "referral_image": None,
            "bot_info_text": DEFAULT_BOT_INFO,
            "bot_info_image": None,
            "publication_chat_id": None,
        }
        self.load()

    def load(self):
        legacy = False
        if self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    legacy = "schema_version" not in loaded
                    self.data.update(loaded)
            except Exception:
                pass
        if legacy:
            self.data["public_access"] = True
        self.data["schema_version"] = 2
        self.data.setdefault("welcome_text", DEFAULT_WELCOME)
        self.data.setdefault("welcome_media", self.data.get("bot_info_image"))
        self.data.setdefault("welcome_media_type", "photo" if self.data.get("bot_info_image") else None)
        self.data.setdefault("referral_media", self.data.get("referral_image"))
        self.data.setdefault("referral_media_type", "photo" if self.data.get("referral_image") else None)
        self.data.setdefault("bot_info_text", DEFAULT_BOT_INFO)
        self.data.setdefault("bot_info_image", None)
        self.save()

    def save(self):
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    @property
    def public_access(self) -> bool:
        return bool(self.data.get("public_access", True))

    def set_public_access(self, value: bool):
        self.data["public_access"] = bool(value)
        self.save()

    def set_welcome_text(self, text: str):
        self.data["welcome_text"] = (text.strip() or DEFAULT_WELCOME)[:1024]
        self.save()

    def set_welcome_media(self, media_type: str | None, file_id: str | None):
        self.data["welcome_media_type"] = media_type
        self.data["welcome_media"] = file_id
        self.save()

    def set_referral_text(self, text: str):
        self.data["referral_text"] = (text.strip() or DEFAULT_REFERRAL_TEXT)[:1024]
        self.save()

    def set_referral_media(self, media_type: str | None, file_id: str | None):
        self.data["referral_media_type"] = media_type
        self.data["referral_media"] = file_id
        self.data["referral_image"] = file_id if media_type == "photo" else None
        self.save()

    def set_referral_image(self, file_id: str | None):
        self.set_referral_media("photo" if file_id else None, file_id)

    def set_welcome_image(self, file_id: str | None):
        self.set_welcome_media("photo" if file_id else None, file_id)

    def set_bot_info_text(self, text: str):
        self.data["bot_info_text"] = (text.strip() or DEFAULT_BOT_INFO)[:1024]
        self.save()

    def set_bot_info_image(self, file_id: str | None):
        self.data["bot_info_image"] = file_id
        self.save()

    def set_publication_chat_id(self, chat_id: int | None):
        self.data["publication_chat_id"] = chat_id
        self.save()

    def get(self, key: str, default=None):
        return self.data.get(key, default)
