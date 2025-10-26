"""Configuration utilities for the TriFiVend MVP backend."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field, HttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from the environment."""

    environment: str = Field(
        default="development",
        description="Name of the current environment (development, staging, production).",
    )
    api_base_url: HttpUrl | None = Field(
        default=None,
        description="Publicly reachable base URL for the API. Required for real Twilio callbacks.",
    )
    data_path: Path = Field(
        default=Path("data/calls.json"),
        description="Filesystem location where call records are stored as JSON.",
    )

    twilio_account_sid: Optional[str] = Field(default=None, description="Twilio Account SID.")
    twilio_auth_token: Optional[str] = Field(default=None, description="Twilio Auth Token.")
    twilio_from_number: Optional[str] = Field(
        default=None,
        description="Twilio phone number used to originate outbound calls.",
    )

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @property
    def twilio_enabled(self) -> bool:
        return all(
            (
                self.twilio_account_sid,
                self.twilio_auth_token,
                self.twilio_from_number,
            )
        )


class AppState(BaseModel):
    settings: Settings


@lru_cache
def get_settings() -> Settings:
    return Settings()


def ensure_data_directory(path: Path) -> None:
    """Ensure the directory containing the data file exists."""

    path.parent.mkdir(parents=True, exist_ok=True)
