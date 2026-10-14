import json
import time
import uuid
from pathlib import Path

MONTH_SECONDS = 30 * 24 * 60 * 60

class BillingManager:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data = {
            "subscription_price": 100,
            "ad_prices": {"3600": 50, "21600": 100, "86400": 200, "259200": 450, "604800": 800},
            "ton_wallet": "",
            "ton_api_key": "",
            "cryptobot_token": "",
            "payments": {},
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
        self.data.setdefault("payments", {})
        self.data.setdefault("ad_prices", {})
        self.save()

    def save(self):
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    @property
    def subscription_price(self) -> int:
        return max(1, int(self.data.get("subscription_price", 100)))

    def set_subscription_price(self, value: int):
        self.data["subscription_price"] = max(1, int(value))
        self.save()

    def ad_price(self, duration_seconds: int) -> int:
        return max(1, int(self.data.get("ad_prices", {}).get(str(duration_seconds), 50)))

    def set_ad_price(self, duration_seconds: int, value: int):
        self.data.setdefault("ad_prices", {})[str(duration_seconds)] = max(1, int(value))
        self.save()

    def set_external(self, ton_wallet=None, ton_api_key=None, cryptobot_token=None):
        if ton_wallet is not None:
            self.data["ton_wallet"] = ton_wallet.strip()
        if ton_api_key is not None:
            self.data["ton_api_key"] = ton_api_key.strip()
        if cryptobot_token is not None:
            self.data["cryptobot_token"] = cryptobot_token.strip()
        self.save()

    def create_payment(self, kind: str, user_id: int, amount: int, meta: dict | None = None) -> str:
        payment_id = uuid.uuid4().hex[:16]
        self.data["payments"][payment_id] = {
            "kind": kind,
            "user_id": int(user_id),
            "amount": int(amount),
            "created_at": int(time.time()),
            "status": "created",
            "meta": meta or {},
        }
        self.save()
        return payment_id

    def mark_paid(self, payment_id: str, charge_id: str | None = None):
        item = self.data["payments"].get(payment_id)
        if not item:
            return
        item["status"] = "paid"
        if charge_id:
            item["charge_id"] = charge_id
        item["paid_at"] = int(time.time())
        self.save()

    def get_payment(self, payment_id: str):
        return self.data["payments"].get(payment_id)
