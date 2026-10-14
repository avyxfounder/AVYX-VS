import json
from pathlib import Path

DEFAULT_REFERRAL_TEXT = (
    "🤝 <b>Приглашаю тебя в AVYX VS!</b>\n\n"
    "Медиа-бот для видео, фото, аудио и расшифровки."
)
DEFAULT_BOT_INFO = (
    "ℹ️ <b>AVYX VS</b>\n\n"
    "Медиа-бот для конвертации видео, фото и аудио, а также расшифровки речи."
)

class BotContent:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data = {
            "public_access": False,
            "referral_text": DEFAULT_REFERRAL_TEXT,
            "referral_image": None,
            "bot_info_text": DEFAULT_BOT_INFO,
            "bot_info_image": None,
        }
        self.load()

    def load(self):
        if self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self.data.update(loaded)
            except Exception:
                pass
        self.save()

    def save(self):
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")

    @property
    def public_access(self) -> bool:
        return bool(self.data.get("public_access", False))

    def set_public_access(self, value: bool):
        self.data["public_access"] = bool(value)
        self.save()

    def set_referral_text(self, text: str):
        self.data["referral_text"] = (text.strip() or DEFAULT_REFERRAL_TEXT)[:1024]
        self.save()

    def set_referral_image(self, file_id: str | None):
        self.data["referral_image"] = file_id
        self.save()

    def set_bot_info_text(self, text: str):
        self.data["bot_info_text"] = (text.strip() or DEFAULT_BOT_INFO)[:1024]
        self.save()

    def set_bot_info_image(self, file_id: str | None):
        self.data["bot_info_image"] = file_id
        self.save()

    def get(self, key: str, default=None):
        return self.data.get(key, default)
