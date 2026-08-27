"""Smoke tests for the Telegram-adapter layer: it should correctly delegate
to `Vault.save_reel`/`Vault.ask` and relay results as replies. No real
Telegram, Instagram, Groq, or Postgres calls are made."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from reel_vault.bot import ReelVaultBot
from reel_vault.models import Saved
from tests.conftest import make_vault


def _make_message(text: str, chat_id: int = 1) -> MagicMock:
    message = MagicMock()
    message.text = text
    message.chat_id = chat_id
    message.reply_text = AsyncMock()
    return message


def _make_update(message: MagicMock, chat_id: int = 1) -> MagicMock:
    update = MagicMock()
    update.effective_message = message
    update.effective_chat.id = chat_id
    return update


@pytest.fixture
def bot() -> ReelVaultBot:
    vault = make_vault(
        captions={"https://instagram.com/reel/ABC": "a caption about ai"},
        tags_by_caption={"a caption about ai": ["ai"]},
    )
    return ReelVaultBot(vault, token="123:fake-token-for-tests")


async def test_sharing_a_reel_url_saves_and_replies_with_tags(bot: ReelVaultBot) -> None:
    message = _make_message("https://instagram.com/reel/ABC")
    update = _make_update(message)

    await bot._on_message(update, MagicMock())

    message.reply_text.assert_awaited_once()
    reply = message.reply_text.await_args.args[0]
    assert "#ai" in reply


async def test_extraction_failure_prompts_for_manual_caption_then_saves(
    bot: ReelVaultBot,
) -> None:
    bot._vault = make_vault(
        captions={"https://instagram.com/reel/DEAD": None},
        tags_by_caption={"pasted text": ["manual"]},
    )

    first_message = _make_message("https://instagram.com/reel/DEAD", chat_id=42)
    await bot._on_message(_make_update(first_message, chat_id=42), MagicMock())
    assert "paste" in first_message.reply_text.await_args.args[0].lower()

    second_message = _make_message("pasted text", chat_id=42)
    await bot._on_message(_make_update(second_message, chat_id=42), MagicMock())

    reply = second_message.reply_text.await_args.args[0]
    assert "#manual" in reply


async def test_plain_text_query_delegates_to_ask(bot: ReelVaultBot) -> None:
    result = bot._vault.save_reel("https://instagram.com/reel/ABC")
    assert isinstance(result, Saved)

    message = _make_message("find that reel about ai")
    update = _make_update(message)

    await bot._on_message(update, MagicMock())

    reply = message.reply_text.await_args.args[0]
    assert "instagram.com/reel/ABC" in reply
