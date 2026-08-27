"""Smoke tests for the Telegram-adapter layer: it should correctly delegate
to `Vault.save_reel`/`Vault.ask` and relay results as replies. No real
Telegram, Instagram, Groq, or Postgres calls are made."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from reel_vault.bot import ReelVaultBot
from reel_vault.models import UNCATEGORIZED, CollectionAssignment, Saved
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


async def test_sharing_a_p_style_link_saves_it_as_a_reel(bot: ReelVaultBot) -> None:
    """Instagram's generic /p/ permalink covers videos too — a real reel
    share does not reliably come through as /reel/ (regression: a /p/ reel
    link was previously silently misrouted into ask() instead of saved)."""
    bot._vault = make_vault(
        captions={"https://www.instagram.com/p/DcellwxRN1m/": "a caption about ai"},
        tags_by_caption={"a caption about ai": ["ai"]},
    )

    message = _make_message("https://www.instagram.com/p/DcellwxRN1m/")
    await bot._on_message(_make_update(message), MagicMock())

    reply = message.reply_text.await_args.args[0]
    assert "#ai" in reply


async def test_unrecognized_instagram_link_gets_a_clear_reply_not_a_search(
    bot: ReelVaultBot,
) -> None:
    message = _make_message("https://www.instagram.com/some_profile/")
    await bot._on_message(_make_update(message), MagicMock())

    message.reply_text.assert_awaited_once()
    reply = message.reply_text.await_args.args[0]
    assert "vault" not in reply.lower()  # not the ask() "Nothing in the vault..." reply


async def test_unsure_collection_asks_then_completes_the_save_on_reply(
    bot: ReelVaultBot,
) -> None:
    bot._vault = make_vault(
        captions={"https://instagram.com/reel/VAGUE": "5yrs ago this wasn't a thing"},
        tags_by_caption={"5yrs ago this wasn't a thing": ["trend"]},
        assignments={
            "5yrs ago this wasn't a thing": CollectionAssignment(collection=UNCATEGORIZED)
        },
    )

    first_message = _make_message("https://instagram.com/reel/VAGUE", chat_id=99)
    await bot._on_message(_make_update(first_message, chat_id=99), MagicMock())
    prompt = first_message.reply_text.await_args.args[0]
    assert "not confident" in prompt.lower()
    assert "vault" not in prompt.lower()  # not misrouted into ask()'s NoMatch reply

    second_message = _make_message("Old Trends / Fashion", chat_id=99)
    await bot._on_message(_make_update(second_message, chat_id=99), MagicMock())

    reply = second_message.reply_text.await_args.args[0]
    assert "Old Trends" in reply
    assert "Fashion" in reply
    assert "#trend" in reply

    saved = bot._vault._store.find_by_url("https://instagram.com/reel/VAGUE")
    assert saved is not None
    assert saved.collection == "Old Trends"
    assert saved.subcollection == "Fashion"


async def test_skip_reply_leaves_the_reel_uncategorized(bot: ReelVaultBot) -> None:
    bot._vault = make_vault(
        captions={"https://instagram.com/reel/VAGUE2": "wait for it"},
        assignments={"wait for it": CollectionAssignment(collection=UNCATEGORIZED)},
    )

    first_message = _make_message("https://instagram.com/reel/VAGUE2", chat_id=7)
    await bot._on_message(_make_update(first_message, chat_id=7), MagicMock())

    second_message = _make_message("skip", chat_id=7)
    await bot._on_message(_make_update(second_message, chat_id=7), MagicMock())

    saved = bot._vault._store.find_by_url("https://instagram.com/reel/VAGUE2")
    assert saved is not None
    assert saved.collection == UNCATEGORIZED


async def test_plain_text_query_delegates_to_ask(bot: ReelVaultBot) -> None:
    result = bot._vault.save_reel("https://instagram.com/reel/ABC")
    assert isinstance(result, Saved)

    message = _make_message("find that reel about ai")
    update = _make_update(message)

    await bot._on_message(update, MagicMock())

    reply = message.reply_text.await_args.args[0]
    assert "instagram.com/reel/ABC" in reply
