"""Thin Telegram long-polling wrapper. Only calls `Vault.save_reel`/`Vault.ask`
and relays their results as chat replies — no vault logic lives here."""

from __future__ import annotations

import logging
import re

from telegram import InputMediaPhoto, Message, Update
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
from reel_vault.vault import Vault

logger = logging.getLogger(__name__)

INSTAGRAM_REEL_URL = re.compile(
    # Instagram's generic /p/ permalink covers photos, carousels, AND
    # videos/reels depending on how the link was generated — a real reel
    # share does not reliably come through as /reel/. Matching /p/ too was
    # previously removed as scope creep, but that broke real reel shares.
    r"https?://(?:www\.)?instagram\.com/(?:reel|reels|p)/[\w-]+/?\S*",
    re.IGNORECASE,
)

INSTAGRAM_URL = re.compile(r"https?://(?:www\.)?instagram\.com/\S*", re.IGNORECASE)

# Telegram caps a media group at 10, so longer runs of reels go out as
# several albums.
MEDIA_GROUP_LIMIT = 10

NO_MATCH_REPLY = "Nothing in the vault matches that."


def _format_location(reel: SavedReel) -> str:
    if reel.subcollection:
        return f"{reel.collection} › {reel.subcollection}"
    return reel.collection


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
    whatever line introduces it."""
    tags_text = ", ".join(f"#{tag}" for tag in reel.tags) if reel.tags else "(no tags)"
    lines = [lead, f"📁 {_format_location(reel)}", f"🏷️ {tags_text}"]
    if reel.author_handle:
        lines.append(f"👤 @{reel.author_handle}")
    return "\n".join(lines)


def _format_reel_detail(reel: SavedReel) -> str:
    """One reel, in full — the reply when the user wanted exactly this one,
    led by the link so it is tappable."""
    return _describe_reel(reel, lead=reel.url)


def _format_reel_list(reels: list[SavedReel], *, author: str | None = None) -> str:
    """Many reels, one line each — enough to scan and pick, not the full
    detail block repeated N times."""
    if not reels:
        return f"Nothing saved from @{author} yet." if author else NO_MATCH_REPLY

    count = f"{len(reels)} {'reel' if len(reels) == 1 else 'reels'}"
    header = f"{count} from @{author}:" if author else f"{count}:"
    lines = []
    for reel in reels:
        suffix = f" — @{reel.author_handle}" if reel.author_handle else ""
        lines.append(f"• {reel.url} ({_format_location(reel)}){suffix}")
    return "\n".join([header, *lines])


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
        url_match = INSTAGRAM_REEL_URL.search(text)

        if url_match:
            await self._handle_url(message, url_match.group(0))
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
        await message.reply_text(_format_saved_reply(result.reel, already_saved=False))

    async def _reply_to_save_result(self, message: Message, result: SaveResult) -> None:
        if isinstance(result, Saved):
            await self._confirm_save(message, result)
        elif isinstance(result, AlreadySaved):
            await message.reply_text(_format_saved_reply(result.reel, already_saved=True))
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
            await message.reply_text(text)
            return

        try:
            sent = await message.reply_photo(photo=result.thumbnail_url, caption=text)
        except TelegramError as exc:
            # A picture is a nicety; the reel is already saved either way.
            logger.info("Could not send thumbnail for %s: %s", result.reel.url, exc)
            await message.reply_text(text)
            return

        if sent.photo:
            self._vault.attach_thumbnail(result.reel.url, sent.photo[-1].file_id)

    async def _handle_query(self, message: Message, query: str) -> None:
        answer = self._vault.ask(query)

        if isinstance(answer, SingleItemAnswer):
            await self._reply_with_reel(message, answer.reel)
        elif isinstance(answer, ListAnswer):
            await message.reply_text(
                _format_reel_list(answer.reels, author=answer.author)
            )
            await self._send_thumbnails(message, answer.reels)
        elif isinstance(answer, AggregateAnswer):
            # The vault has always returned the reels behind a synthesized
            # answer; the reply used to drop them, leaving no way to go and
            # watch what the answer was built from.
            await message.reply_text(
                f"{answer.text}\n\n{_format_reel_list(answer.reels)}"
            )
            await self._send_thumbnails(message, answer.reels)
        elif isinstance(answer, NoMatch):
            await message.reply_text(NO_MATCH_REPLY)

    async def _reply_with_reel(self, message: Message, reel: SavedReel) -> None:
        """One reel, as a picture the user can recognize where we have one."""
        detail = _format_reel_detail(reel)
        if reel.thumbnail_ref:
            await message.reply_photo(photo=reel.thumbnail_ref, caption=detail)
        else:
            await message.reply_text(detail)

    async def _send_thumbnails(self, message: Message, reels: list[SavedReel]) -> None:
        """Pictures to scan alongside the list — every matched reel that has
        one, in albums of ten. Reels saved before thumbnails existed have
        none, and are already in the text list."""
        pictures = [
            (reel.thumbnail_ref, reel.url) for reel in reels if reel.thumbnail_ref
        ]

        for start in range(0, len(pictures), MEDIA_GROUP_LIMIT):
            batch = pictures[start : start + MEDIA_GROUP_LIMIT]
            if len(batch) == 1:
                ref, url = batch[0]
                await message.reply_photo(photo=ref, caption=url)
                continue
            await message.reply_media_group(
                [InputMediaPhoto(media=ref, caption=url) for ref, url in batch]
            )


def build_bot(vault: Vault, token: str) -> ReelVaultBot:
    return ReelVaultBot(vault, token)
