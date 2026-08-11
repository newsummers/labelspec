from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore"
    )

    qianfan_api_key: str = ""
    qianfan_base_url: str = "https://qianfan.baidubce.com/v2"
    labelspec_database_path: str = "./backend/data/labelspec.db"
    labelspec_cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    labelspec_log_level: str = "INFO"

    @property
    def database_path(self) -> Path:
        path = Path(self.labelspec_database_path)
        if not path.is_absolute():
            workspace = Path(__file__).resolve().parents[2]
            path = workspace / path
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def cors_origins(self) -> List[str]:
        return [value.strip() for value in self.labelspec_cors_origins.split(",") if value.strip()]

    @property
    def has_api_key(self) -> bool:
        return bool(self.qianfan_api_key.strip())


@lru_cache
def get_settings() -> AppSettings:
    return AppSettings()

