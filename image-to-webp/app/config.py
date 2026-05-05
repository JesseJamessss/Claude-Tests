from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    upload_dir: Path = Path("uploads")
    max_file_bytes: int = 10 * 1024 * 1024  # 10 MB
    webp_quality: int = 82
    webp_lossless: bool = False
    preserve_animation: bool = True
    url_prefix: str = "/images"

    model_config = SettingsConfigDict(env_prefix="IMG_")


@lru_cache
def get_settings() -> Settings:
    return Settings()
