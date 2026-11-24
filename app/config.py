"""Application settings. All paths are derived from this file's location or env vars."""
import os
from dataclasses import dataclass
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
PROJECT_DIR = APP_DIR.parent
STATIC_DIR = APP_DIR / "static"


@dataclass
class Settings:
    data_dir: Path
    max_upload_bytes: int = 10 * 1024 * 1024
    max_pages: int = 300

    @property
    def db_path(self) -> Path:
        return self.data_dir / "noticeiq.db"

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    def ensure_dirs(self) -> None:
        self.upload_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_env(cls) -> "Settings":
        data_dir = Path(os.environ.get("NOTICEIQ_DATA_DIR", PROJECT_DIR / "data"))
        max_mb = float(os.environ.get("NOTICEIQ_MAX_MB", "10"))
        return cls(data_dir=data_dir, max_upload_bytes=int(max_mb * 1024 * 1024))
