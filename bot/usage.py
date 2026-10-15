import json
import time
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_FREE_USES = 1
REFERRAL_BONUS_USES = 2
SUPPORT_DAILY_LIMIT = 3

class UsageManager:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data = {"users": {}}
        self.load()

    def load(self):
        if self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self.data.update(loaded)
            except Exception:
                pass
        if not isinstance(self.data.get("users"), dict):
            self.data["users"] = {}
        self.save()

    def save(self):
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def ensure_user(self, user_id: int):
        key = str(user_id)
        if key not in self.data["users"]:
            self.data["users"][key] = {
                "uses": DEFAULT_FREE_USES,
                "total_used": 0,
                "earned": DEFAULT_FREE_USES,
                "subscription_until": 0,
                "support": {},
                "created_at": int(time.time()),
            }
            self.save()
        else:
            user = self.data["users"][key]
            user.setdefault("uses", 0)
            user.setdefault("total_used", 0)
            user.setdefault("earned", user.get("uses", 0))
            user.setdefault("subscription_until", 0)
            user.setdefault("support", {})
        return self.data["users"][key]

    def is_subscribed(self, user_id: int) -> bool:
        return int(self.ensure_user(user_id).get("subscription_until", 0)) > int(time.time())

    def subscription_until(self, user_id: int) -> int:
        return int(self.ensure_user(user_id).get("subscription_until", 0))

    def activate_subscription(self, user_id: int, until_ts: int):
        user = self.ensure_user(user_id)
        user["subscription_until"] = max(int(user.get("subscription_until", 0)), int(until_ts))
        self.save()

    def grant_subscription(self, user_id: int, seconds: int):
        user = self.ensure_user(user_id)
        now = int(time.time())
        base = max(now, int(user.get("subscription_until", 0)))
        user["subscription_until"] = base + max(0, int(seconds))
        self.save()
        return int(user["subscription_until"])

    def revoke_subscription(self, user_id: int):
        user = self.ensure_user(user_id)
        user["subscription_until"] = 0
        self.save()

    def remaining(self, user_id: int) -> str:
        if self.is_subscribed(user_id):
            return "∞"
        return str(max(0, int(self.ensure_user(user_id).get("uses", 0))))

    def can_use(self, user_id: int) -> bool:
        return self.is_subscribed(user_id) or int(self.ensure_user(user_id).get("uses", 0)) > 0

    def consume(self, user_id: int) -> bool:
        user = self.ensure_user(user_id)
        if self.is_subscribed(user_id):
            user["total_used"] = int(user.get("total_used", 0)) + 1
            self.save()
            return True
        if int(user.get("uses", 0)) <= 0:
            return False
        user["uses"] = int(user.get("uses", 0)) - 1
        user["total_used"] = int(user.get("total_used", 0)) + 1
        self.save()
        return True

    def refund(self, user_id: int, amount: int = 1):
        user = self.ensure_user(user_id)
        if not self.is_subscribed(user_id):
            user["uses"] = int(user.get("uses", 0)) + max(0, int(amount))
        user["total_used"] = max(0, int(user.get("total_used", 0)) - max(0, int(amount)))
        self.save()

    def add_uses(self, user_id: int, amount: int):
        user = self.ensure_user(user_id)
        amount = max(0, int(amount))
        user["uses"] = int(user.get("uses", 0)) + amount
        user["earned"] = int(user.get("earned", 0)) + amount
        self.save()

    def support_count_today(self, user_id: int) -> int:
        user = self.ensure_user(user_id)
        day = datetime.now(timezone.utc).date().isoformat()
        return int(user.setdefault("support", {}).get(day, 0))

    def register_support(self, user_id: int) -> bool:
        user = self.ensure_user(user_id)
        day = datetime.now(timezone.utc).date().isoformat()
        support = user.setdefault("support", {})
        count = int(support.get(day, 0))
        if count >= SUPPORT_DAILY_LIMIT:
            return False
        support[day] = count + 1
        if len(support) > 10:
            for old in sorted(support)[:-10]:
                support.pop(old, None)
        self.save()
        return True

    def profile(self, user_id: int) -> dict:
        user = self.ensure_user(user_id)
        return {
            "uses": self.remaining(user_id),
            "total_used": int(user.get("total_used", 0)),
            "subscription_until": self.subscription_until(user_id),
            "support_today": self.support_count_today(user_id),
        }

    def list_users(self):
        return [int(x) for x in self.data["users"].keys()]
