from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    telegram_bot_token: str
    groq_api_key: str
    database_url: str


def load_config() -> Config:
    load_dotenv()
    return Config(
        telegram_bot_token=_require_env("TELEGRAM_BOT_TOKEN"),
        groq_api_key=_require_env("GROQ_API_KEY"),
        database_url=_require_env("DATABASE_URL"),
    )


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value
