from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AGILE_", env_file=".env", extra="ignore")

    database_url: str = ""
    """``mysql+pymysql://user:pass@host:3306/agile_studio`` — cùng host MySQL với backend, database riêng."""

    api_title: str = "Agile Studio API"
    listen_host: str = "127.0.0.1"
    listen_port: int = 9120

    jwt_secret: str = "agile-studio-dev-secret-change-me"
    """Ký JWT (HS256). Production: đặt ``AGILE_JWT_SECRET`` đủ dài, ngẫu nhiên."""

    jwt_expire_minutes: int = 10080
    """Thời hạn access token (mặc định 7 ngày)."""


@lru_cache
def get_settings() -> Settings:
    return Settings()
