import os
from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql://flowcheck_user:changeme@127.0.0.1:5432/flowcheck_db"

    # JWT
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 30

    # StreamflowOps
    dataops_api_url: str = "https://streamflowops.3rdplaces.io"
    dataops_api_token: str
    dataops_timeout: int = 30

    # Firebase — path to service account JSON downloaded from Firebase console
    firebase_credentials_path: str = ""

    # Station cache TTL (seconds)
    station_cache_ttl: int = 1800

    class Config:
        env_file = ".env"


@lru_cache
def get_settings() -> Settings:
    return Settings()
