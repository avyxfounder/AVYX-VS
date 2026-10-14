import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

@dataclass(frozen=True)
class Settings:
    bot_token: str
    temp_dir: str = os.getenv("TEMP_DIR", "temp")
    max_download_mb: int = int(os.getenv("MAX_DOWNLOAD_MB", "20"))
    max_output_mb: int = int(os.getenv("MAX_OUTPUT_MB", "50"))
    owner_id: int = int(os.getenv("OWNER_ID", "8710132959"))
    access_db: str = os.getenv("ACCESS_DB", "data/access.json")

    @classmethod
    def from_env(cls) -> "Settings":
        token = os.getenv("BOT_TOKEN", "").strip()
        if not token or token == "PASTE_YOUR_BOT_TOKEN_HERE":
            raise RuntimeError("BOT_TOKEN is not set. Copy .env.example to .env and add your BotFather token.")
        return cls(bot_token=token)
