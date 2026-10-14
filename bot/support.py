import json
import time
from pathlib import Path

class SupportManager:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data = {"tickets": {}, "message_map": {}}
        self.load()

    def load(self):
        if self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self.data.update(loaded)
            except Exception:
                pass
        self.data.setdefault("tickets", {})
        self.data.setdefault("message_map", {})
        self.save()

    def save(self):
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def create(self, user_id: int):
        ticket_id = f"T{int(time.time())}-{user_id}"
        self.data["tickets"][ticket_id] = {
            "id": ticket_id,
            "user_id": int(user_id),
            "created_at": int(time.time()),
            "status": "open",
            "admin_message_id": None,
        }
        self.save()
        return ticket_id

    def set_admin_message(self, ticket_id: str, message_id: int):
        item = self.data["tickets"].get(ticket_id)
        if item:
            item["admin_message_id"] = int(message_id)
            self.data["message_map"][str(message_id)] = ticket_id
            self.save()

    def by_admin_message(self, message_id: int):
        ticket_id = self.data["message_map"].get(str(message_id))
        return self.data["tickets"].get(ticket_id) if ticket_id else None

    def close(self, ticket_id: str):
        item = self.data["tickets"].get(ticket_id)
        if item:
            item["status"] = "closed"
            self.save()
        return item
