"""Environment configuration.

Deliberately names no vendor. Every model this app talks to is reached over
the OpenAI-compatible HTTP shape — `/chat/completions` and
`/audio/transcriptions` — which Groq, OpenAI, DeepSeek, Qwen, Together,
Moonshot, Mistral and Google's compatibility endpoint all speak. So which
provider is in use is a base URL, a key and a model name, not a code path:
moving off today's provider is an `.env` edit, not a rewrite.

The defaults point at Groq's free tier because that is what this vault runs
on today, not because anything here depends on it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

# Today's defaults. Every one is overridable; none is reached for in code.
DEFAULT_LLM_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_LLM_MODEL = "openai/gpt-oss-20b"
DEFAULT_TRANSCRIPTION_MODEL = "whisper-large-v3-turbo"
# Google's OpenAI-compatibility endpoint, so vision needs no second SDK and
# no second code path — it is the same chat call with images attached.
DEFAULT_VISION_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
DEFAULT_VISION_MODEL = "gemini-2.5-flash"


@dataclass(frozen=True)
class ModelEndpoint:
    """One model, wherever it lives. The unit of provider choice: swapping
    providers means a different instance of this, never a different class."""

    base_url: str
    api_key: str
    model: str


@dataclass(frozen=True)
class Config:
    telegram_bot_token: str
    database_url: str
    # Writes tags, collections, query classifications, summaries, rankings,
    # compiled lists, and condensed transcripts.
    llm: ModelEndpoint
    # Hears a reel. Its own endpoint because the provider that hosts the best
    # free chat model is not necessarily the one hosting speech-to-text —
    # though when it is, it needs no separate configuration.
    transcription: ModelEndpoint
    # Reads a reel's frames. Optional, unlike the other two: without it the
    # vault still saves, searches, answers and transcribes, and only
    # on-screen text goes unread. Making it required would stop a working
    # bot from starting over a feature it can do without.
    vision: ModelEndpoint | None = None


def load_config() -> Config:
    load_dotenv()

    llm_base_url = os.environ.get("LLM_BASE_URL") or DEFAULT_LLM_BASE_URL
    llm_api_key = _require_env("LLM_API_KEY")

    return Config(
        telegram_bot_token=_require_env("TELEGRAM_BOT_TOKEN"),
        database_url=_require_env("DATABASE_URL"),
        llm=ModelEndpoint(
            base_url=llm_base_url,
            api_key=llm_api_key,
            model=os.environ.get("LLM_MODEL") or DEFAULT_LLM_MODEL,
        ),
        # Falls back to the chat provider rather than demanding its own keys:
        # one provider commonly serves both, and asking for the same
        # credentials twice is a setup step that exists only to be forgotten.
        transcription=ModelEndpoint(
            base_url=os.environ.get("TRANSCRIPTION_BASE_URL") or llm_base_url,
            api_key=os.environ.get("TRANSCRIPTION_API_KEY") or llm_api_key,
            model=(
                os.environ.get("TRANSCRIPTION_MODEL") or DEFAULT_TRANSCRIPTION_MODEL
            ),
        ),
        vision=_optional_vision(),
    )


def _optional_vision() -> ModelEndpoint | None:
    """Vision is configured only if a key is given for it. Its base URL is
    not defaulted from the chat provider the way transcription's is: a
    provider that serves chat very often serves speech too, and much less
    often serves images."""
    api_key = os.environ.get("VISION_API_KEY")
    if not api_key:
        return None
    return ModelEndpoint(
        base_url=os.environ.get("VISION_BASE_URL") or DEFAULT_VISION_BASE_URL,
        api_key=api_key,
        model=os.environ.get("VISION_MODEL") or DEFAULT_VISION_MODEL,
    )


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value
