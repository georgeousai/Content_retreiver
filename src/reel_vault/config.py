from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    telegram_bot_token: str
    groq_api_key: str
    database_url: str
    # Optional, unlike the rest: without it the vault still saves, searches
    # and answers, and reels are still transcribed — only the reading of
    # on-screen text is off. Making it required would stop a working bot from
    # starting over a feature it can do without.
    gemini_api_key: str | None = None


def load_config() -> Config:
    load_dotenv()
    return Config(
        telegram_bot_token=_require_env("TELEGRAM_BOT_TOKEN"),
        groq_api_key=_require_env("GROQ_API_KEY"),
        database_url=_require_env("DATABASE_URL"),
        gemini_api_key=os.environ.get("GEMINI_API_KEY") or None,
    )


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value
