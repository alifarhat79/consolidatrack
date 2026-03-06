"""Application configuration loaded from environment variables."""
import os
from pathlib import Path

basedir = Path(__file__).resolve().parent.parent


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-fallback-key-change-in-production")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", f"sqlite:///{basedir / 'consolidatrack.db'}"
    )
    # Render uses "postgres://" but SQLAlchemy needs "postgresql://"
    if SQLALCHEMY_DATABASE_URI.startswith("postgres://"):
        SQLALCHEMY_DATABASE_URI = SQLALCHEMY_DATABASE_URI.replace(
            "postgres://", "postgresql://", 1
        )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # SeaRates
    SEARATES_API_KEY = os.environ.get("SEARATES_API_KEY", "")
    SEARATES_BASE_URL = os.environ.get(
        "SEARATES_BASE_URL", "https://api.searates.com/v1"
    )

    # Scheduler
    TRACKING_INTERVAL_HOURS = int(os.environ.get("TRACKING_INTERVAL_HOURS", 6))

    # Business rules
    PROPORTIONAL_TOLERANCE = float(os.environ.get("PROPORTIONAL_TOLERANCE", 0.01))

    # WTF CSRF
    WTF_CSRF_ENABLED = True

    # File Uploads
    UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER", str(basedir / "uploads" / "photos"))
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB max


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False
    SERVER_NAME = "localhost"
