import json
from pathlib import Path

class AccessManager:
    def __init__(self, path: str, owner_id: int):
        self.path = Path(path)
        self.owner_id = owner_id
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data = {"users": [owner_id], "admins": [owner_id], "blocked": []}
        self.load()

    def load(self):
        if self.path.exists():
            try:
                self.data.update(json.loads(self.path.read_text(encoding="utf-8")))
            except Exception:
                pass
        for key in ("users", "admins", "blocked"):
            self.data[key] = [int(x) for x in self.data.get(key, [])]
        if self.owner_id not in self.data["users"]: self.data["users"].append(self.owner_id)
        if self.owner_id not in self.data["admins"]: self.data["admins"].append(self.owner_id)
        self.save()

    def save(self):
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")

    def allowed(self, user_id: int) -> bool:
        return user_id in self.data["users"] and user_id not in self.data["blocked"]

    def admin(self, user_id: int) -> bool:
        return user_id in self.data["admins"] and user_id not in self.data["blocked"]

    def add(self, user_id: int):
        if user_id not in self.data["users"]: self.data["users"].append(user_id)
        if user_id in self.data["blocked"]: self.data["blocked"].remove(user_id)
        self.save()

    def remove(self, user_id: int):
        if user_id != self.owner_id:
            self.data["users"] = [x for x in self.data["users"] if x != user_id]
            self.data["admins"] = [x for x in self.data["admins"] if x != user_id]
            self.save()

    def block(self, user_id: int):
        if user_id != self.owner_id:
            self.data["blocked"] = list(set(self.data["blocked"] + [user_id]))
            self.data["users"] = [x for x in self.data["users"] if x != user_id]
            self.data["admins"] = [x for x in self.data["admins"] if x != user_id]
            self.save()

    def promote(self, user_id: int):
        self.add(user_id)
        if user_id not in self.data["admins"]: self.data["admins"].append(user_id)
        self.save()

    def list_users(self):
        return self.data["users"]
