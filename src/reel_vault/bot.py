"""Thin Telegram long-polling wrapper. Only calls `Vault.save_reel`/`Vault.ask`
and relays their results as chat replies — no vault logic lives here."""

from __future__ import annotations

import re

from telegram import Message, Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

from reel_vault.models import (
    AggregateAnswer,
    AlreadySaved,
    ExtractionFailed,
    NoMatch,
    Saved,
    SavedReel,
    SaveResult,
    SingleItemAnswer,
)
from reel_vault.vault import Vault

INSTAGRAM_REEL_URL = re.compile(
    r"https?://(?:www\.)?instagram\.com/reels?/[\w-]+/?\S*", re.IGNORECASE
)


def _format_location(reel: SavedReel) -> str:
    if reel.subcollection:
        return f"{reel.collection} › {reel.subcollection}"
    return reel.collection


def _format_saved_reply(reel: SavedReel, *, already_saved: bool) -> str:
    tags_text = ", ".join(f"#{tag}" for tag in reel.tags) if reel.tags else "(no tags)"
    lines = [
        "Already saved that one." if already_saved else "Saved!",
        f"📁 {_format_location(reel)}",
        f"🏷️ {tags_text}",
    ]
    if reel.author_handle:
        lines.append(f"👤 @{reel.author_handle}")
    return "\n".join(lines)


class ReelVaultBot:
    def __init__(self, vault: Vault, token: str) -> None:
        self._vault = vault
        self._pending_manual_caption: dict[int, str] = {}
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

    async def _reply_to_save_result(self, message: Message, result: SaveResult) -> None:
        if isinstance(result, Saved):
            await message.reply_text(_format_saved_reply(result.reel, already_saved=False))
        elif isinstance(result, AlreadySaved):
            await message.reply_text(_format_saved_reply(result.reel, already_saved=True))

    async def _handle_query(self, message: Message, query: str) -> None:
        answer = self._vault.ask(query)

        if isinstance(answer, SingleItemAnswer):
            reel = answer.reel
            tags_text = ", ".join(f"#{tag}" for tag in reel.tags)
            lines = [reel.url, f"📁 {_format_location(reel)}", f"🏷️ {tags_text}"]
            if reel.author_handle:
                lines.append(f"👤 @{reel.author_handle}")
            await message.reply_text("\n".join(lines))
        elif isinstance(answer, AggregateAnswer):
            await message.reply_text(answer.text)
        elif isinstance(answer, NoMatch):
            await message.reply_text("Nothing in the vault matches that.")


def build_bot(vault: Vault, token: str) -> ReelVaultBot:
    return ReelVaultBot(vault, token)
