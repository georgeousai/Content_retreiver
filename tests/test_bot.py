"""Smoke tests for the Telegram-adapter layer: it should correctly delegate
to `Vault.save_reel`/`Vault.ask` and relay results as replies. No real
Telegram, Instagram, model-provider, or Postgres calls are made."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from telegram.constants import ParseMode
from telegram.error import TelegramError

from reel_vault.bot import (
    ReelVaultBot,
    _collection_picker,
    _move_keyboard,
    _render_summary,
)
from reel_vault.urls import shortcode_of
from reel_vault.models import (
    UNCATEGORIZED,
    CollectionAssignment,
    ExtractedPost,
    Saved,
    SavedReel,
)
from tests.conftest import make_vault


def _make_message(text: str, chat_id: int = 1) -> MagicMock:
    message = MagicMock()
    message.text = text
    message.chat_id = chat_id
    message.reply_text = AsyncMock()
    message.reply_photo = AsyncMock()
    message.reply_media_group = AsyncMock()
    # Real Telegram leaves this unset unless the message really is a reply; a
    # bare MagicMock would instead look like a reply to a mock message.
    message.reply_to_message = None
    return message


def _make_reply_to_card(text: str, card_text: str, chat_id: int = 1) -> MagicMock:
    """A message replying to a card the bot posted earlier. The bot reads the
    reel out of the card's own text, so that is what has to be there."""
    message = _make_message(text, chat_id=chat_id)
    card = MagicMock()
    card.text = card_text
    card.caption = None
    message.reply_to_message = card
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

    saved = bot._vault._store.find_by_url("https://instagram.com/p/VAGUE")
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

    saved = bot._vault._store.find_by_url("https://instagram.com/p/VAGUE2")
    assert saved is not None
    assert saved.collection == UNCATEGORIZED


async def test_aggregate_reply_carries_the_reels_behind_the_answer(
    bot: ReelVaultBot,
) -> None:
    """A synthesized answer with no links leaves the user unable to go watch
    the reels it was built from."""
    assert isinstance(bot._vault.save_reel("https://instagram.com/reel/ABC"), Saved)

    message = _make_message("summarize my ai reels")
    await bot._on_message(_make_update(message), MagicMock())

    all_replies = "\n".join(call.args[0] for call in message.reply_text.await_args_list)
    assert "a caption about ai" in all_replies  # the synthesized text
    assert "instagram.com/p/ABC" in all_replies  # and the reel behind it


async def test_list_reply_shows_every_match_not_just_the_best(
    bot: ReelVaultBot,
) -> None:
    bot._vault = make_vault(
        captions={
            "https://instagram.com/reel/A1": "ai agents explained",
            "https://instagram.com/reel/A2": "ai agents in production",
        },
    )
    for url in ("https://instagram.com/reel/A1", "https://instagram.com/reel/A2"):
        assert isinstance(bot._vault.save_reel(url), Saved)

    message = _make_message("show me my ai agents reels")
    await bot._on_message(_make_update(message), MagicMock())

    all_replies = "\n".join(call.args[0] for call in message.reply_text.await_args_list)
    assert "instagram.com/p/A1" in all_replies
    assert "instagram.com/p/A2" in all_replies


def _photo_reply(file_id: str) -> MagicMock:
    """What Telegram hands back from sendPhoto: the message it posted, with
    one entry per rendered size."""
    sent = MagicMock()
    sent.photo = [MagicMock(file_id=file_id)]
    return sent


def _save_with_picture(vault, url: str, caption: str, file_id: str) -> None:
    """Save a reel and give it the file_id Telegram would have minted."""
    assert isinstance(vault.save_reel(url), Saved)
    vault.attach_thumbnail(url, file_id)


async def test_save_confirmation_doubles_as_the_thumbnail_upload(
    bot: ReelVaultBot,
) -> None:
    """The confirmation is sent as the reel's picture, and the file_id
    Telegram returns for it is what gets kept — no separate upload, nothing
    for the user to configure."""
    url = "https://instagram.com/reel/PIC"
    bot._vault = make_vault(
        captions={
            url: ExtractedPost(
                caption="ai agents explained", thumbnail_url="https://cdn/t.jpg"
            )
        },
    )

    message = _make_message(url)
    message.reply_photo.return_value = _photo_reply("tg-file-id")
    await bot._on_message(_make_update(message), MagicMock())

    kwargs = message.reply_photo.await_args.kwargs
    assert kwargs["photo"] == "https://cdn/t.jpg"  # Telegram fetches it server-side
    assert "Saved!" in kwargs["caption"]

    saved = bot._vault._store.find_by_url("https://instagram.com/p/PIC")
    assert saved is not None
    assert saved.thumbnail_ref == "tg-file-id"


async def test_a_reel_still_saves_when_its_picture_cannot_be_sent(
    bot: ReelVaultBot,
) -> None:
    url = "https://instagram.com/reel/PIC"
    bot._vault = make_vault(
        captions={url: ExtractedPost(caption="ai agents", thumbnail_url="https://cdn/x.jpg")},
    )

    message = _make_message(url)
    message.reply_photo.side_effect = TelegramError("bad photo url")
    await bot._on_message(_make_update(message), MagicMock())

    assert "Saved!" in message.reply_text.await_args.args[0]
    saved = bot._vault._store.find_by_url("https://instagram.com/p/PIC")
    assert saved is not None
    assert saved.thumbnail_ref is None


async def test_single_item_reply_shows_the_reels_picture(bot: ReelVaultBot) -> None:
    """The picture is how the user recognizes which reel this is."""
    url = "https://instagram.com/reel/PIC"
    bot._vault = make_vault(captions={url: "ai agents explained"})
    _save_with_picture(bot._vault, url, "ai agents explained", "tg-file-id")

    message = _make_message("find that reel about ai agents")
    await bot._on_message(_make_update(message), MagicMock())

    message.reply_photo.assert_awaited_once()
    kwargs = message.reply_photo.await_args.kwargs
    assert kwargs["photo"] == "tg-file-id"
    assert "instagram.com/p/PIC" in kwargs["caption"]


async def test_a_reel_saved_without_a_thumbnail_still_replies_as_text(
    bot: ReelVaultBot,
) -> None:
    assert isinstance(bot._vault.save_reel("https://instagram.com/reel/ABC"), Saved)

    message = _make_message("find that reel about ai")
    await bot._on_message(_make_update(message), MagicMock())

    message.reply_photo.assert_not_awaited()
    assert "instagram.com/p/ABC" in message.reply_text.await_args.args[0]


async def test_list_reply_sends_each_matching_reel_as_its_own_card(
    bot: ReelVaultBot,
) -> None:
    """Each reel is its own message — the picture directly under its own
    link and details, not batched into a separate album disconnected from
    a shared text list."""
    bot._vault = make_vault(
        captions={
            "https://instagram.com/reel/A1": "ai agents explained",
            "https://instagram.com/reel/A2": "ai agents in production",
        },
    )
    _save_with_picture(bot._vault, "https://instagram.com/reel/A1", "", "file-1")
    _save_with_picture(bot._vault, "https://instagram.com/reel/A2", "", "file-2")

    message = _make_message("show me my ai agents reels")
    await bot._on_message(_make_update(message), MagicMock())

    assert message.reply_photo.await_count == 2
    photos = {call.kwargs["photo"] for call in message.reply_photo.await_args_list}
    assert photos == {"file-1", "file-2"}
    captions = [call.kwargs["caption"] for call in message.reply_photo.await_args_list]
    assert any("instagram.com/p/A1" in c for c in captions)
    assert any("instagram.com/p/A2" in c for c in captions)


async def test_a_large_list_still_gets_every_reel_a_card(bot: ReelVaultBot) -> None:
    """A 12-match browse must not silently drop any reel's picture."""
    captions = {
        f"https://instagram.com/reel/N{i}": f"ai agents topic number{i}"
        for i in range(12)
    }
    bot._vault = make_vault(captions=captions)
    for i, url in enumerate(captions):
        _save_with_picture(bot._vault, url, "", f"file-{i}")

    message = _make_message("show me my ai agents reels")
    await bot._on_message(_make_update(message), MagicMock())

    photos = [call.kwargs["photo"] for call in message.reply_photo.await_args_list]
    assert len(photos) == 12
    assert len(set(photos)) == 12


async def test_plain_text_query_delegates_to_ask(bot: ReelVaultBot) -> None:
    result = bot._vault.save_reel("https://instagram.com/reel/ABC")
    assert isinstance(result, Saved)

    message = _make_message("find that reel about ai")
    update = _make_update(message)

    await bot._on_message(update, MagicMock())

    reply = message.reply_text.await_args.args[0]
    assert "instagram.com/p/ABC" in reply


def test_a_summarys_apostrophes_reach_the_user_as_apostrophes() -> None:
    """Live failure: "Dev's Vlog Diary" arrived as "Dev&#x27;s Vlog Diary".
    The text was HTML-escaped and then sent with no parse mode, so Telegram
    had no reason to turn the entity back into a character."""
    assert _render_summary("Dev's Vlog Diary") == "Dev&#x27;s Vlog Diary"


async def test_a_summary_is_sent_in_html_so_its_escaping_is_undone(
    bot: ReelVaultBot,
) -> None:
    assert isinstance(bot._vault.save_reel("https://instagram.com/reel/ABC"), Saved)

    message = _make_message("summarize my ai reels")
    await bot._on_message(_make_update(message), MagicMock())

    summary_call = message.reply_text.await_args_list[0]
    assert summary_call.kwargs.get("parse_mode") == ParseMode.HTML


def test_summary_headings_and_bullets_become_telegram_markup() -> None:
    rendered = _render_summary("## Getting unstuck\n- Ask what you are avoiding")

    assert rendered == "<b>Getting unstuck</b>\n\u2022 Ask what you are avoiding"


def test_markup_in_a_summary_is_inert_rather_than_rendered() -> None:
    """The markers are applied after escaping, so a caption quoted into the
    answer cannot close a tag the bot opened and break the whole message."""
    rendered = _render_summary("He said <b>never</b> & meant it")

    assert rendered == "He said &lt;b&gt;never&lt;/b&gt; &amp; meant it"


# --- re-filing a reel the classifier put in the wrong place ----------------


async def test_replying_to_a_card_moves_that_reel(bot: ReelVaultBot) -> None:
    """Live case: a "Five Year Journey #smallbusiness" reel was filed under
    Personal Growth because a "Journey" sub-collection already existed there,
    when it belonged under Entrepreneurship. The reel is identified from the
    card being replied to, so nothing has to be re-pasted."""
    assert isinstance(bot._vault.save_reel("https://instagram.com/reel/ABC"), Saved)
    card = "https://instagram.com/p/ABC\nPersonal Growth > Journey"

    message = _make_reply_to_card("Entrepreneurship / Small Business", card)
    await bot._on_message(_make_update(message), MagicMock())

    moved = bot._vault._store.find_by_url("https://instagram.com/p/ABC")
    assert moved is not None
    assert moved.collection == "Entrepreneurship"
    assert moved.subcollection == "Small Business"


async def test_a_moved_reel_is_re_embedded_for_its_new_shelf(
    bot: ReelVaultBot,
) -> None:
    """A reel is embedded together with its collection, so a move that only
    rewrote the label would leave it findable under the shelf it just left."""
    assert isinstance(bot._vault.save_reel("https://instagram.com/reel/ABC"), Saved)
    before = bot._vault._store.find_by_url("https://instagram.com/p/ABC")
    assert before is not None

    message = _make_reply_to_card(
        "Entrepreneurship", "https://instagram.com/p/ABC"
    )
    await bot._on_message(_make_update(message), MagicMock())

    after = bot._vault._store.find_by_url("https://instagram.com/p/ABC")
    assert after is not None
    assert after.embedding != before.embedding
    assert after.caption == before.caption
    assert after.tags == before.tags


async def test_a_move_keeps_the_reels_picture_and_when_it_was_saved(
    bot: ReelVaultBot,
) -> None:
    """Re-filing is not a re-save: everything that isn't the taxonomy or what
    depends on it survives."""
    url = "https://instagram.com/reel/PIC"
    bot._vault = make_vault(captions={url: "ai agents explained"})
    _save_with_picture(bot._vault, url, "ai agents explained", "tg-file-id")
    before = bot._vault._store.find_by_url("https://instagram.com/p/PIC")
    assert before is not None

    message = _make_reply_to_card("Entrepreneurship", "https://instagram.com/p/PIC")
    await bot._on_message(_make_update(message), MagicMock())

    after = bot._vault._store.find_by_url("https://instagram.com/p/PIC")
    assert after is not None
    assert after.thumbnail_ref == "tg-file-id"
    assert after.saved_at == before.saved_at


async def test_replying_about_a_reel_the_vault_does_not_have_says_so(
    bot: ReelVaultBot,
) -> None:
    message = _make_reply_to_card("Entrepreneurship", "https://instagram.com/p/NOPE")
    await bot._on_message(_make_update(message), MagicMock())

    reply = message.reply_text.await_args.args[0]
    assert "don't have" in reply.lower()


async def test_a_reply_that_is_not_to_a_card_is_still_a_query(
    bot: ReelVaultBot,
) -> None:
    """Replying to something with no reel in it must not be read as a move."""
    assert isinstance(bot._vault.save_reel("https://instagram.com/reel/ABC"), Saved)

    message = _make_reply_to_card("find that reel about ai", "just some chatter")
    await bot._on_message(_make_update(message), MagicMock())

    assert "instagram.com/p/ABC" in message.reply_text.await_args.args[0]


def test_every_card_carries_a_move_button() -> None:
    reel = SavedReel(url="https://instagram.com/p/ABC", caption="c", tags=[], embedding=[])

    markup = _move_keyboard(shortcode_of(reel.url) or "")

    assert markup.inline_keyboard[0][0].callback_data == "mv:ABC"


def test_the_picker_offers_the_vaults_own_collections() -> None:
    markup = _collection_picker("ABC", ["AI", "Entrepreneurship"])

    offered = [b.text for row in markup.inline_keyboard for b in row]
    assert offered == ["AI", "Entrepreneurship", "Cancel"]


def test_a_collection_too_long_for_a_callback_is_left_out_not_truncated() -> None:
    """A truncated callback would file the reel under a name the user never
    chose. Replying to the card still reaches it by name."""
    too_long = "A" * 60

    markup = _collection_picker("ABC", ["AI", too_long])

    offered = [b.text for row in markup.inline_keyboard for b in row]
    assert offered == ["AI", "Cancel"]


async def test_tapping_a_collection_moves_the_reel(bot: ReelVaultBot) -> None:
    assert isinstance(bot._vault.save_reel("https://instagram.com/reel/ABC"), Saved)

    query = MagicMock()
    query.data = "mvto:ABC:Entrepreneurship"
    query.answer = AsyncMock()
    query.edit_message_caption = AsyncMock()
    query.edit_message_text = AsyncMock()
    query.message = MagicMock(spec=[])
    update = MagicMock()
    update.callback_query = query

    await bot._on_callback(update, MagicMock())

    moved = bot._vault._store.find_by_url("https://instagram.com/p/ABC")
    assert moved is not None
    assert moved.collection == "Entrepreneurship"


async def test_opening_the_picker_does_not_move_anything(bot: ReelVaultBot) -> None:
    assert isinstance(bot._vault.save_reel("https://instagram.com/reel/ABC"), Saved)

    query = MagicMock()
    query.data = "mv:ABC"
    query.answer = AsyncMock()
    query.edit_message_reply_markup = AsyncMock()
    update = MagicMock()
    update.callback_query = query

    await bot._on_callback(update, MagicMock())

    query.edit_message_reply_markup.assert_awaited_once()
    unmoved = bot._vault._store.find_by_url("https://instagram.com/p/ABC")
    assert unmoved is not None
    assert unmoved.collection != "Entrepreneurship"


async def test_replying_to_the_save_confirmation_moves_the_reel(
    bot: ReelVaultBot,
) -> None:
    """The confirmation is where a misfiling is most likely to be noticed, so
    replying to it has to work the same as replying to any other card — which
    means it has to print the reel's link like every other card does."""
    message = _make_message("https://instagram.com/reel/ABC")
    await bot._on_message(_make_update(message), MagicMock())
    confirmation = message.reply_text.await_args.args[0]

    reply = _make_reply_to_card("Entrepreneurship / Small Business", confirmation)
    await bot._on_message(_make_update(reply), MagicMock())

    moved = bot._vault._store.find_by_url("https://instagram.com/p/ABC")
    assert moved is not None
    assert moved.collection == "Entrepreneurship"


async def test_a_move_offers_an_undo(bot: ReelVaultBot) -> None:
    assert isinstance(bot._vault.save_reel("https://instagram.com/reel/ABC"), Saved)

    message = _make_reply_to_card("Entrepreneurship", "https://instagram.com/p/ABC")
    await bot._on_message(_make_update(message), MagicMock())

    markup = message.reply_text.await_args.kwargs["reply_markup"]
    assert [b.text for b in markup.inline_keyboard[0]] == ["Undo", "Move"]


async def test_tapping_undo_puts_the_reel_back(bot: ReelVaultBot) -> None:
    assert isinstance(bot._vault.save_reel("https://instagram.com/reel/ABC"), Saved)
    before = bot._vault._store.find_by_url("https://instagram.com/p/ABC")
    assert before is not None
    bot._vault.refile("https://instagram.com/p/ABC", collection="Entrepreneurship")

    query = MagicMock()
    query.data = "mvu:ABC"
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    query.message = MagicMock(spec=[])
    update = MagicMock()
    update.callback_query = query

    await bot._on_callback(update, MagicMock())

    back = bot._vault._store.find_by_url("https://instagram.com/p/ABC")
    assert back is not None
    assert back.collection == before.collection


async def test_undo_on_a_reel_that_was_never_moved_says_so(bot: ReelVaultBot) -> None:
    assert isinstance(bot._vault.save_reel("https://instagram.com/reel/ABC"), Saved)

    query = MagicMock()
    query.data = "mvu:ABC"
    query.answer = AsyncMock()
    update = MagicMock()
    update.callback_query = query

    await bot._on_callback(update, MagicMock())

    assert "nothing to undo" in query.answer.await_args.args[0].lower()


async def test_a_ranked_reply_prints_the_measure_it_ranked_by(
    bot: ReelVaultBot,
) -> None:
    """The bot never asks which reading of "best" was meant, so showing the
    one it chose is the only way the user can tell it got it wrong."""
    bot._vault = make_vault(
        captions={"https://instagram.com/reel/B1": "bicep curl form tips"},
    )
    assert isinstance(bot._vault.save_reel("https://instagram.com/reel/B1"), Saved)

    message = _make_message("best bicep exercise")
    await bot._on_message(_make_update(message), MagicMock())

    all_replies = "\n".join(call.args[0] for call in message.reply_text.await_args_list)
    assert "Ranked by:" in all_replies
    assert "instagram.com/p/B1" in all_replies  # and the reel behind the verdict


async def test_a_compiled_reply_is_a_list_not_a_paragraph(bot: ReelVaultBot) -> None:
    bot._vault = make_vault(
        captions={
            "https://instagram.com/reel/Q1": "interview question: tell me about yourself",
            "https://instagram.com/reel/Q2": "interview question: why this company",
        },
    )
    for url in ("https://instagram.com/reel/Q1", "https://instagram.com/reel/Q2"):
        assert isinstance(bot._vault.save_reel(url), Saved)

    message = _make_message("compile the interview questions")
    await bot._on_message(_make_update(message), MagicMock())

    all_replies = "\n".join(call.args[0] for call in message.reply_text.await_args_list)
    assert "• interview question: tell me about yourself" in all_replies
    assert "• interview question: why this company" in all_replies


async def test_matching_reels_that_list_nothing_is_not_reported_as_no_match(
    bot: ReelVaultBot,
) -> None:
    """"Nothing matches" would send the user hunting for saves that are
    sitting right there — the reels matched, they just had no items in them."""
    bot._vault = make_vault(captions={"https://instagram.com/reel/E1": "ai agents"})
    assert isinstance(bot._vault.save_reel("https://instagram.com/reel/E1"), Saved)
    bot._vault._item_extractor = MagicMock(extract_items=MagicMock(return_value=[]))

    message = _make_message("compile the ai tools")
    await bot._on_message(_make_update(message), MagicMock())

    reply = message.reply_text.await_args.args[0]
    assert reply != "Nothing in the vault matches that."
    assert "none of them" in reply.lower()


async def test_a_stale_file_id_costs_one_card_not_the_rest_of_the_answer(
    bot: ReelVaultBot,
) -> None:
    """The confirmation path guarded `reply_photo` and the query path did
    not. One file_id Telegram no longer honours therefore raised out of the
    middle of the card loop: the user lost every remaining reel and the
    answer they were the evidence for, over a picture."""
    bot._vault = make_vault(
        captions={
            "https://instagram.com/reel/A1": "ai agents explained",
            "https://instagram.com/reel/A2": "ai agents in production",
        },
    )
    _save_with_picture(bot._vault, "https://instagram.com/reel/A1", "", "dead-file-id")
    _save_with_picture(bot._vault, "https://instagram.com/reel/A2", "", "file-2")

    message = _make_message("show me my ai agents reels")

    def photo(*args, **kwargs):
        if kwargs["photo"] == "dead-file-id":
            raise TelegramError("wrong file identifier")
        return _photo_reply(kwargs["photo"])

    message.reply_photo.side_effect = photo
    await bot._on_message(_make_update(message), MagicMock())

    # The good card still went as a picture...
    photos = {
        call.kwargs["photo"] for call in message.reply_photo.await_args_list
    }
    assert photos == {"dead-file-id", "file-2"}
    # ...and the dead one fell back to text rather than taking the reply down.
    text_replies = [
        call.args[0] for call in message.reply_text.await_args_list if call.args
    ]
    assert any("instagram.com/p/A1" in reply for reply in text_replies)


async def test_the_collection_question_mints_the_picture_before_the_pause(
    bot: ReelVaultBot,
) -> None:
    """The extracted thumbnail URL is signed and expires, and a save paused
    on a collection choice sits in front of the user for as long as they take
    to answer. Minting the durable reference when the question is asked —
    rather than carrying the raw URL across that pause — is what keeps an
    overnight answer from finishing with a link that has already gone. It
    also shows the reel at the moment the user is asked where to file it.
    """
    url = "https://instagram.com/reel/PIC"
    bot._vault = make_vault(
        captions={
            url: ExtractedPost(
                caption="5yrs ago this wasn't a thing",
                thumbnail_url="https://cdn/expiring.jpg",
            )
        },
        assignments={
            "5yrs ago this wasn't a thing": CollectionAssignment(
                collection=UNCATEGORIZED
            )
        },
    )

    asking = _make_message(url, chat_id=7)
    asking.reply_photo.return_value = _photo_reply("tg-file-id")
    await bot._on_message(_make_update(asking, chat_id=7), chat_id_ignored := MagicMock())

    # The question itself was the upload.
    assert asking.reply_photo.await_args.kwargs["photo"] == "https://cdn/expiring.jpg"
    assert bot._pending_collection_choice[7].thumbnail_ref == "tg-file-id"

    answering = _make_message("Old Trends", chat_id=7)
    await bot._on_message(_make_update(answering, chat_id=7), chat_id_ignored)

    saved = bot._vault._store.find_by_url("https://instagram.com/p/PIC")
    assert saved is not None
    assert saved.collection == "Old Trends"
    # Kept from the question, and never re-minted from the expired URL.
    assert saved.thumbnail_ref == "tg-file-id"
    assert answering.reply_photo.await_args.kwargs["photo"] == "tg-file-id"


async def test_a_collection_question_without_a_picture_is_still_just_asked(
    bot: ReelVaultBot,
) -> None:
    url = "https://instagram.com/reel/NOPIC"
    bot._vault = make_vault(
        captions={url: "5yrs ago this wasn't a thing"},
        assignments={
            "5yrs ago this wasn't a thing": CollectionAssignment(
                collection=UNCATEGORIZED
            )
        },
    )

    message = _make_message(url, chat_id=8)
    await bot._on_message(_make_update(message, chat_id=8), MagicMock())

    message.reply_photo.assert_not_awaited()
    assert bot._pending_collection_choice[8].thumbnail_ref is None
