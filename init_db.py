"""Create the data folder and SQLite database (the app also does this on startup)."""
from app.config import Settings
from app.db import Database

settings = Settings.from_env()
settings.ensure_dirs()
Database(settings.db_path)
print(f"Database ready at {settings.db_path}")
