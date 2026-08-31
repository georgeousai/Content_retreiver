"""What `load_config` promises about the per-job endpoints.

Every model this app talks to gets its own base URL, key and model name, but
what each falls back to when unset differs, and the differences are the
point:

    condenser      all three fall back to LLM_*
    transcription  base URL and key fall back to LLM_*; the model does not,
                   because a chat model's name is not a speech model's
    vision         nothing falls back; no key means no vision at all

Those asymmetries are argued for in `config.py` and are easy to break
silently. A fallback that stops falling back only shows up as a missing-key
crash on someone else's machine; an override read from the wrong variable
name keeps using the old provider while looking configured.

No call is made to any provider here. `load_config` reads the environment and
builds dataclasses; that is all that is under test.
"""

from __future__ import annotations

import pytest

from reel_vault.config import (
    DEFAULT_LLM_BASE_URL,
    DEFAULT_LLM_MODEL,
    DEFAULT_TRANSCRIPTION_MODEL,
    load_config,
)

# Everything `load_config` reads, so a variable left over from the developer's
# real `.env` cannot leak into a test and make it pass for the wrong reason.
CONFIG_VARS = (
    "TELEGRAM_BOT_TOKEN",
    "DATABASE_URL",
    "LLM_BASE_URL",
    "LLM_API_KEY",
    "LLM_MODEL",
    "CONDENSER_BASE_URL",
    "CONDENSER_API_KEY",
    "CONDENSER_MODEL",
    "TRANSCRIPTION_BASE_URL",
    "TRANSCRIPTION_API_KEY",
    "TRANSCRIPTION_MODEL",
    "VISION_BASE_URL",
    "VISION_API_KEY",
    "VISION_MODEL",
)

REQUIRED = {
    "TELEGRAM_BOT_TOKEN": "token",
    "DATABASE_URL": "postgresql://localhost/test",
    "LLM_API_KEY": "chat-key",
}


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch):
    """A clean environment holding only what the test puts in it.

    `load_config` calls `load_dotenv`, which would otherwise read the real
    `.env` sitting in the repo root and hand these tests live credentials.
    Stubbing it out is what makes the assertions below about the *absence* of
    a variable mean anything.
    """
    monkeypatch.setattr("reel_vault.config.load_dotenv", lambda *a, **k: False)
    for name in CONFIG_VARS:
        monkeypatch.delenv(name, raising=False)
    for name, value in REQUIRED.items():
        monkeypatch.setenv(name, value)
    return monkeypatch


def test_the_condenser_falls_back_to_the_chat_provider(env) -> None:
    """One key in `.env` has to be enough to run the whole vault. If the
    condenser demanded its own, every existing install would break on
    upgrade."""
    config = load_config()

    assert config.condenser.base_url == DEFAULT_LLM_BASE_URL
    assert config.condenser.api_key == "chat-key"
    assert config.condenser.model == DEFAULT_LLM_MODEL
    assert config.condenser == config.llm


def test_the_condenser_follows_an_overridden_chat_provider(env) -> None:
    """The fallback is to whatever `LLM_*` actually is, not to the Groq
    defaults. Someone running the whole vault on DeepSeek must not find the
    condenser quietly still pointed at Groq -- with a Groq-shaped model name
    and a DeepSeek key, which fails at the first call rather than at
    startup."""
    env.setenv("LLM_BASE_URL", "https://api.deepseek.com/v1")
    env.setenv("LLM_MODEL", "deepseek-chat")

    config = load_config()

    assert config.condenser.base_url == "https://api.deepseek.com/v1"
    assert config.condenser.model == "deepseek-chat"
    assert config.condenser.api_key == "chat-key"


def test_the_condenser_can_be_pointed_somewhere_else_entirely(env) -> None:
    """The reason this block exists: the condenser has a measured failure
    rate that is a property of the model, so it has to be testable against a
    second provider without touching the one that does everything else."""
    env.setenv(
        "CONDENSER_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/"
    )
    env.setenv("CONDENSER_API_KEY", "google-key")
    env.setenv("CONDENSER_MODEL", "gemini-2.5-flash")

    config = load_config()

    assert config.condenser.base_url == (
        "https://generativelanguage.googleapis.com/v1beta/openai/"
    )
    assert config.condenser.api_key == "google-key"
    assert config.condenser.model == "gemini-2.5-flash"

    # Moving the condenser must move nothing else. Sharing a client between
    # the two jobs was exactly the coupling this block was added to remove.
    assert config.llm.base_url == DEFAULT_LLM_BASE_URL
    assert config.llm.api_key == "chat-key"
    assert config.llm.model == DEFAULT_LLM_MODEL


@pytest.mark.parametrize(
    "variable, field",
    [
        ("CONDENSER_BASE_URL", "base_url"),
        ("CONDENSER_API_KEY", "api_key"),
        ("CONDENSER_MODEL", "model"),
    ],
)
def test_each_condenser_variable_overrides_on_its_own(
    env, variable: str, field: str
) -> None:
    """Set one, and the other two still fall back. A provider that shares the
    chat provider's base URL but serves a different model there is an ordinary
    case, and it should not require restating the two settings that are
    already right."""
    baseline = load_config().llm
    env.setenv(variable, "overridden")

    condenser = load_config().condenser

    assert getattr(condenser, field) == "overridden"
    untouched = [f for f in ("base_url", "api_key", "model") if f != field]
    for other in untouched:
        assert getattr(condenser, other) == getattr(baseline, other), (
            f"setting {variable} should leave {other} falling back to LLM_*"
        )


def test_transcription_still_falls_back_the_same_way(env) -> None:
    """The pattern the condenser block was copied from. Kept alongside it so
    the two are read together, and so a change to the shared fallback shows up
    as two failures rather than one."""
    config = load_config()

    assert config.transcription.base_url == DEFAULT_LLM_BASE_URL
    assert config.transcription.api_key == "chat-key"
    # The one part that does not fall back: a chat model name is not a
    # speech-to-text model name, so this default stands on its own.
    assert config.transcription.model == DEFAULT_TRANSCRIPTION_MODEL


def test_vision_is_absent_without_its_own_key(env) -> None:
    """The deliberate asymmetry: vision alone does not fall back to the chat
    provider, because a provider serving chat usually serves speech and
    usually does not serve images."""
    assert load_config().vision is None
