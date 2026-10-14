import asyncio
import json
import time
import uuid
from pathlib import Path

class PublicationManager:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data = {"news": [], "ads": [], "next_news": 1, "next_ad": 1}
        self.load()

    def load(self):
        if self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self.data.update(loaded)
            except Exception:
                pass
        self.data.setdefault("news", [])
        self.data.setdefault("ads", [])
        self.save()

    def save(self):
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def news(self, limit=10):
        return list(reversed(self.data["news"][-limit:]))

    def create_news(self, text: str, media_type: str | None, file_id: str | None):
        item = {
            "id": int(self.data.get("next_news", 1)),
            "text": (text or "").strip(),
            "media_type": media_type,
            "file_id": file_id,
            "created_at": int(time.time()),
            "pinned": False,
            "messages": [],
        }
        self.data["next_news"] = item["id"] + 1
        self.data["news"].append(item)
        self.save()
        return item

    def get_news(self, news_id: int):
        return next((x for x in self.data["news"] if int(x["id"]) == int(news_id)), None)

    def delete_news_record(self, news_id: int):
        self.data["news"] = [x for x in self.data["news"] if int(x["id"]) != int(news_id)]
        self.save()

    def create_ad(self, user_id: int, text: str, media_type: str | None, file_id: str | None, duration_seconds: int, pin_requested: bool, price: int):
        order_id = uuid.uuid4().hex[:12]
        item = {
            "id": order_id,
            "user_id": int(user_id),
            "text": (text or "").strip(),
            "media_type": media_type,
            "file_id": file_id,
            "duration_seconds": int(duration_seconds),
            "pin_requested": bool(pin_requested),
            "price": int(price),
            "status": "awaiting_payment",
            "created_at": int(time.time()),
            "paid_at": None,
            "approved_at": None,
            "expires_at": None,
            "messages": [],
            "publication_message_id": None,
        }
        self.data["ads"].append(item)
        self.save()
        return item

    def get_ad(self, order_id: str):
        return next((x for x in self.data["ads"] if x["id"] == order_id), None)

    def update_ad(self, order_id: str, **fields):
        item = self.get_ad(order_id)
        if item:
            item.update(fields)
            self.save()
        return item

    def pending_ads(self):
        return [x for x in self.data["ads"] if x.get("status") in ("paid", "pending_review")]

    async def expire_due(self, bot):
        now = int(time.time())
        changed = False
        for ad in self.data["ads"]:
            if ad.get("status") != "active" or not ad.get("expires_at") or int(ad["expires_at"]) > now:
                continue
            for sent in list(ad.get("messages", [])):
                try:
                    await bot.delete_message(chat_id=int(sent["chat_id"]), message_id=int(sent["message_id"]))
                except Exception:
                    pass
            if ad.get("publication_message_id"):
                try:
                    await bot.unpin_chat_message(chat_id=int(ad["publication_chat_id"]), message_id=int(ad["publication_message_id"]))
                except Exception:
                    pass
            ad["status"] = "expired"
            changed = True
        if changed:
            self.save()

    async def cleanup_loop(self, bot):
        while True:
            try:
                await self.expire_due(bot)
            except Exception:
                pass
            await asyncio.sleep(60)
