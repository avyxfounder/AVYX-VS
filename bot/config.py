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
    content_db: str = os.getenv("CONTENT_DB", "data/content.json")
    usage_db: str = os.getenv("USAGE_DB", "data/usage.json")
    billing_db: str = os.getenv("BILLING_DB", "data/billing.json")
    publication_db: str = os.getenv("PUBLICATION_DB", "data/publications.json")
    support_db: str = os.getenv("SUPPORT_DB", "data/support.json")

    @classmethod
    def from_env(cls) -> "Settings":
        token = os.getenv("BOT_TOKEN", "").strip()
        if not token or token == "PASTE_YOUR_BOT_TOKEN_HERE":
            raise RuntimeError("BOT_TOKEN is not set.")
        return cls(bot_token=token)
