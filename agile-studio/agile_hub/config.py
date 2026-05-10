from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Luôn đọc agile-studio/.env (không phụ thuộc cwd khi chạy uvicorn).
_AGILE_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = _AGILE_ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AGILE_",
        env_file=_ENV_FILE if _ENV_FILE.is_file() else None,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = ""
    """``mysql+pymysql://user:pass@host:3306/agile_studio`` — cùng host MySQL với backend, database riêng."""

    api_title: str = "Agile Studio API"
    listen_host: str = "127.0.0.1"
    listen_port: int = 9120

    jwt_secret: str = "agile-studio-dev-secret-change-me"
    """Ký JWT (HS256). Production: đặt ``AGILE_JWT_SECRET`` đủ dài, ngẫu nhiên."""

    jwt_expire_minutes: int = 10080
    """Thời hạn access token (mặc định 7 ngày)."""

    agent_reply_token: str = ""
    """Bearer cho ``POST .../integrations/api-center/agent-reply``; trùng ``API_CENTER_AGILE_REPLY_TOKEN``."""

    chat_service_url: str = ""
    """Base URL Nest chat-service (``AGILE_CHAT_SERVICE_URL``), ví dụ ``http://127.0.0.1:9130``."""

    public_web_url: str = "http://localhost:5175"
    """Base URL web app (invite links). ``AGILE_PUBLIC_WEB_URL``."""

    smtp_host: str = ""
    """Khi rỗng, email mời chỉ ghi log (dev). ``AGILE_SMTP_HOST``."""

    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True
    mail_from: str = "Agile Studio <noreply@localhost>"
    """``AGILE_MAIL_FROM`` — ví dụ ``Agile Studio <team@company.com>``."""


@lru_cache
def get_settings() -> Settings:
    return Settings()
