from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    database_url: str = "sqlite:///runtime/contestly.db"
    secure_cookies: bool = False
    public_origin: str = ""
    auto_init: bool = True
    seed_snapshot: bool = True
    session_hours: int = 24
    data_dir: Path = ROOT / "data"

    @classmethod
    def from_env(cls):
        production = os.getenv("APP_ENV") == "production"
        return cls(
            database_url=os.getenv("DATABASE_URL", "sqlite:///runtime/contestly.db"),
            secure_cookies=production or os.getenv("SECURE_COOKIES") == "true",
            public_origin=os.getenv("PUBLIC_ORIGIN", "").rstrip("/"),
            auto_init=os.getenv("AUTO_INIT_DB", "false" if production else "true") == "true",
            seed_snapshot=os.getenv("SEED_SNAPSHOT", "true") == "true",
            session_hours=int(os.getenv("SESSION_HOURS", "24")),
            data_dir=Path(os.getenv("CONTEST_DATA_DIR", str(ROOT / "data"))),
        )
