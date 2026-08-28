"""Thin Telegram long-polling wrapper. Only calls `Vault.save_reel`/`Vault.ask`
and relays their results as chat replies — no vault logic lives here."""

from __future__ import annotations

import html
import logging

from telegram import Message, Update
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import Application, ContextTypes, MessageHandler, filters

from reel_vault.models import (
    UNCATEGORIZED,
    AggregateAnswer,
    AlreadySaved,
    ExtractionFailed,
    ListAnswer,
    NeedsCollectionChoice,
    NoMatch,
    Saved,
    SavedReel,
    SaveResult,
    SingleItemAnswer,
)
from reel_vault.urls import INSTAGRAM_URL, find_reel_url
from reel_vault.vault import Vault

logger = logging.getLogger(__name__)

NO_MATCH_REPLY = "Nothing in the vault matches that."


def _esc(text: str) -> str:
    """Escape text bound for an HTML-parse-mode message. Author names and
    tags come from Instagram captions and an LLM, not from us — either can
    contain `<`, `>`, or `&`, which would otherwise break the markup."""
    return html.escape(text)


def _render_summary(text: str) -> str:
    """Turn the summarizer's plain text into Telegram HTML.

    Escaped first, marked up second, so nothing the model writes can be read
    as markup. Letting the model emit HTML directly would put every reply one
    malformed tag away from Telegram rejecting the whole message, and a
    rejected send is a user who gets no answer at all rather than an ugly one.

    (This reply used to be escaped and then sent with no parse mode at all,
    which is why an apostrophe reached the user as a literal "&#x27;".)
    """
    rendered = []
    for line in _esc(text).splitlines():
        line = line.strip()
        if line.startswith("## "):
            rendered.append(f"<b>{line[3:].strip()}</b>")
        elif line.startswith("- "):
            rendered.append(f"• {line[2:].strip()}")
        else:
            rendered.append(line)
    return "\n".join(rendered)


def _format_location(reel: SavedReel) -> str:
    if reel.subcollection:
        return f"{_esc(reel.collection)} › {_esc(reel.subcollection)}"
    return _esc(reel.collection)


def _format_collection_prompt(known: dict[str, list[str]]) -> str:
    if not known:
        existing_line = "You have no collections yet — this will be the first."
    else:
        parts = [
            f"{name} ({', '.join(subs)})" if subs else name
            for name, subs in sorted(known.items())
        ]
        existing_line = "Existing: " + ", ".join(parts)

    return (
        "I'm not confident which collection this belongs in.\n"
        f"{existing_line}\n\n"
        "Reply with a collection name (new or existing). Add "
        '"/ Subcollection" for a sub-collection, e.g. "AI / Interview Prep". '
        'Reply "skip" to leave it Uncategorized.'
    )


def _parse_collection_reply(text: str) -> tuple[str, str | None]:
    if text.strip().lower() == "skip":
        return UNCATEGORIZED, None
    if "/" in text:
        collection, subcollection = text.split("/", 1)
        return collection.strip(), subcollection.strip() or None
    return text.strip(), None


def _describe_reel(reel: SavedReel, *, lead: str) -> str:
    """The collection/tags/author block every single-reel reply shares, under
    whatever line introduces it. HTML parse mode gives the labels real
    structure instead of a wall of emoji-prefixed plain text."""
    tags_text = ", ".join(f"#{_esc(tag)}" for tag in reel.tags) if reel.tags else "—"
    lines = [
        lead,
        f"📁 <b>{_format_location(reel)}</b>",
        f"🏷️ {tags_text}",
    ]
    if reel.author_handle:
        lines.append(f"👤 @{_esc(reel.author_handle)}")
    return "\n".join(lines)


def _format_reel_detail(reel: SavedReel) -> str:
    """One reel, in full — the reply when the user wanted exactly this one,
    led by the link so it is tappable."""
    return _describe_reel(reel, lead=f'<a href="{_esc(reel.url)}">{_esc(reel.url)}</a>')


def _format_list_header(
    reel_count: int, *, author: str | None = None, collection: str | None = None
) -> str:
    """The one-line lead-in before a run of per-reel cards."""
    count = f"{reel_count} {'reel' if reel_count == 1 else 'reels'}"
    if author:
        return f"{count} from @{_esc(author)}:"
    if collection:
        return f"{count} in <b>{_esc(collection)}</b>:"
    return f"{count}:"


def _format_empty_list_reply(*, author: str | None = None, collection: str | None = None) -> str:
    if author:
        return f"Nothing saved from @{author} yet."
    if collection:
        return f"Nothing saved in {collection} yet."
    return NO_MATCH_REPLY


def _format_saved_reply(reel: SavedReel, *, already_saved: bool) -> str:
    return _describe_reel(
        reel, lead="Already saved that one." if already_saved else "Saved!"
    )


class ReelVaultBot:
    def __init__(self, vault: Vault, token: str) -> None:
        self._vault = vault
        self._pending_manual_caption: dict[int, str] = {}
        self._pending_collection_choice: dict[int, NeedsCollectionChoice] = {}
        self._app = Application.builder().token(token).build()
        self._app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._on_message))

    def run(self) -> None:
        self._app.run_polling()

    async def _on_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        chat_id = update.effective_chat.id if update.effective_chat else None
        if message is None or message.text is None or chat_id is None:
            return

        text = message.text.strip()
        reel_url = find_reel_url(text)

        if reel_url:
            await self._handle_url(message, reel_url)
            return

        pending_url = self._pending_manual_caption.pop(chat_id, None)
        if pending_url is not None:
            await self._handle_manual_caption(message, pending_url, text)
            return

        pending_choice = self._pending_collection_choice.pop(chat_id, None)
        if pending_choice is not None:
            await self._handle_collection_choice(message, pending_choice, text)
            return

        if INSTAGRAM_URL.search(text):
            # Looks like an Instagram link, but not one our pattern recognizes
            # (e.g. a profile or explore link) — say so, rather than silently
            # treating the raw URL as a semantic search query.
            await message.reply_text(
                "That doesn't look like a post or reel link I can save."
            )
            return

        await self._handle_query(message, text)

    async def _handle_url(self, message: Message, url: str) -> None:
        result = self._vault.save_reel(url)

        if isinstance(result, ExtractionFailed):
            self._pending_manual_caption[message.chat_id] = url
            await message.reply_text(
                "I couldn't read the caption on that one. Please paste the caption text "
                "and I'll save it."
            )
            return

        await self._reply_to_save_result(message, result)

    async def _handle_manual_caption(self, message: Message, url: str, caption: str) -> None:
        result = self._vault.save_reel(url, manual_caption=caption)

        if isinstance(result, ExtractionFailed):
            await message.reply_text("That caption looked empty — nothing was saved.")
            return

        await self._reply_to_save_result(message, result)

    async def _handle_collection_choice(
        self, message: Message, pending: NeedsCollectionChoice, reply: str
    ) -> None:
        collection, subcollection = _parse_collection_reply(reply)
        result = self._vault.assign_collection(
            pending, collection=collection, subcollection=subcollection
        )
        await self._reply_to_save_result(message, result)

    async def _reply_to_save_result(self, message: Message, result: SaveResult) -> None:
        if isinstance(result, Saved):
            await self._confirm_save(message, result)
        elif isinstance(result, AlreadySaved):
            # Show the picture here too: recognizing the reel you just
            # re-shared is the same problem as recognizing one you searched for.
            await self._reply_with_reel(
                message, result.reel, _format_saved_reply(result.reel, already_saved=True)
            )
        elif isinstance(result, NeedsCollectionChoice):
            self._pending_collection_choice[message.chat_id] = result
            await message.reply_text(_format_collection_prompt(result.known_collections))

    async def _confirm_save(self, message: Message, result: Saved) -> None:
        """Confirm the save with the reel's own picture where there is one.

        The confirmation doubles as the upload that mints a Telegram file_id:
        Telegram fetches the (expiring) Instagram URL server-side, and the
        file_id it returns never expires, so every later reply can show the
        picture for free. One message, no clutter, nothing for the user to
        configure.
        """
        text = _format_saved_reply(result.reel, already_saved=False)
        if not result.thumbnail_url:
            await message.reply_text(text, parse_mode=ParseMode.HTML)
            return

        try:
            sent = await message.reply_photo(
                photo=result.thumbnail_url, caption=text, parse_mode=ParseMode.HTML
            )
        except TelegramError as exc:
            # A picture is a nicety; the reel is already saved either way.
            logger.info("Could not send thumbnail for %s: %s", result.reel.url, exc)
            await message.reply_text(text, parse_mode=ParseMode.HTML)
            return

        if sent.photo:
            self._vault.attach_thumbnail(result.reel.url, sent.photo[-1].file_id)

    async def _handle_query(self, message: Message, query: str) -> None:
        answer = self._vault.ask(query)

        if isinstance(answer, SingleItemAnswer):
            await self._reply_with_reel(message, answer.reel)
        elif isinstance(answer, ListAnswer):
            if not answer.reels:
                await message.reply_text(
                    _format_empty_list_reply(author=answer.author, collection=answer.collection)
                )
                return
            await message.reply_text(
                _format_list_header(
                    len(answer.reels), author=answer.author, collection=answer.collection
                ),
                parse_mode=ParseMode.HTML,
            )
            await self._send_reel_cards(message, answer.reels)
        elif isinstance(answer, AggregateAnswer):
            # The vault has always returned the reels behind a synthesized
            # answer; the reply used to drop them, leaving no way to go and
            # watch what the answer was built from.
            await message.reply_text(
                _render_summary(answer.text), parse_mode=ParseMode.HTML
            )
            await self._send_reel_cards(message, answer.reels)
        elif isinstance(answer, NoMatch):
            await message.reply_text(NO_MATCH_REPLY)

    async def _reply_with_reel(
        self, message: Message, reel: SavedReel, text: str | None = None
    ) -> None:
        """One reel, as a picture the user can recognize where we have one."""
        body = text if text is not None else _format_reel_detail(reel)
        if reel.thumbnail_ref:
            await message.reply_photo(
                photo=reel.thumbnail_ref, caption=body, parse_mode=ParseMode.HTML
            )
        else:
            await message.reply_text(body, parse_mode=ParseMode.HTML)

    async def _send_reel_cards(self, message: Message, reels: list[SavedReel]) -> None:
        """One message per reel — the picture sits directly under its own
        link and details rather than in a separate album disconnected from
        the text list above it."""
        for reel in reels:
            await self._reply_with_reel(message, reel)


def build_bot(vault: Vault, token: str) -> ReelVaultBot:
    return ReelVaultBot(vault, token)
