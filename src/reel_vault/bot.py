"""Thin Telegram long-polling wrapper. Only calls `Vault.save_reel`/`Vault.ask`
and relays their results as chat replies — no vault logic lives here."""

from __future__ import annotations

import asyncio
import html
import logging

from telegram import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    Update,
)
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from reel_vault.models import (
    UNCATEGORIZED,
    AggregateAnswer,
    AlreadySaved,
    CompareAnswer,
    ExtractAnswer,
    ExtractionFailed,
    ListAnswer,
    NeedsCollectionChoice,
    NoMatch,
    Saved,
    SavedReel,
    SaveResult,
    SingleItemAnswer,
)
from reel_vault.urls import (
    INSTAGRAM_URL,
    find_reel_url,
    shortcode_of,
    url_for_shortcode,
)
from reel_vault.vault import Vault

logger = logging.getLogger(__name__)

NO_MATCH_REPLY = "Nothing in the vault matches that."
# Distinct from NO_MATCH_REPLY: reels matched, they just did not contain the
# thing that was asked for. Saying "nothing matches" there would send the user
# looking for saves that are sitting right in front of them.
NOTHING_TO_COMPILE_REPLY = (
    "I found matching reels, but none of them list what you asked for."
)

# Callback actions. A reel travels through these as its shortcode rather
# than its URL: Telegram allows 64 bytes for everything a callback carries,
# and the shortcode is the only part of the URL that identifies anything.
MOVE_OPEN = "mv"
MOVE_TO = "mvto"
MOVE_CANCEL = "mvx"
MOVE_UNDO = "mvu"
CALLBACK_LIMIT = 64


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


def _render_comparison(answer: CompareAnswer) -> str:
    """A ranked answer with the measure it used printed above it.

    Shown rather than buried in the prose, because "best" is ambiguous often
    enough that the criterion is the part most worth disagreeing with — and
    the bot never asks which one the user meant, so seeing what it assumed is
    the only way to correct it.
    """
    return (
        f"<i>Ranked by: {_esc(answer.criterion)}</i>\n\n"
        f"{_render_summary(answer.text)}"
    )


def _render_items(items: list[str]) -> str:
    """The compiled list, as a list. The whole request was to be handed the
    things themselves rather than a paragraph about them."""
    return "\n".join(f"• {_esc(item)}" for item in items)


def _move_keyboard(shortcode: str) -> InlineKeyboardMarkup:
    """The button every card carries. Where a reel belongs is often a
    judgement call the classifier can lose honestly, so the way to disagree
    with it belongs on the reel itself rather than in documentation."""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("Move", callback_data=f"{MOVE_OPEN}:{shortcode}")]]
    )


def _undo_keyboard(shortcode: str) -> InlineKeyboardMarkup:
    """Offered only just after a move, on the card that move rewrote. The
    previous shelf is not carried in the callback — a collection and
    sub-collection pair overruns Telegram's 64-byte budget on exactly the
    long names most likely to be mis-filed — so the vault looks it up."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Undo", callback_data=f"{MOVE_UNDO}:{shortcode}"),
                InlineKeyboardButton("Move", callback_data=f"{MOVE_OPEN}:{shortcode}"),
            ]
        ]
    )


def _collection_picker(shortcode: str, collections: list[str]) -> InlineKeyboardMarkup:
    """The vault's existing shelves, two to a row.

    A collection whose name would push the callback past Telegram's 64-byte
    limit is left out rather than truncated into a button that would file the
    reel somewhere it never said; replying to the card still reaches it by
    name.
    """
    buttons = [
        InlineKeyboardButton(name, callback_data=data)
        for name in collections
        for data in [f"{MOVE_TO}:{shortcode}:{name}"]
        if len(data.encode()) <= CALLBACK_LIMIT
    ]
    rows = [buttons[at : at + 2] for at in range(0, len(buttons), 2)]
    rows.append(
        [InlineKeyboardButton("Cancel", callback_data=f"{MOVE_CANCEL}:{shortcode}")]
    )
    return InlineKeyboardMarkup(rows)


def _replied_to_reel_url(message: Message) -> str | None:
    """The reel a message is replying to, read back out of the card itself.

    Every card prints its reel's link, so the card is already the record of
    which reel it showed. Keeping a message-id-to-reel map instead would be
    state that dies on restart, and a user replying to yesterday's card has
    no way to know the bot has forgotten what it was.
    """
    replied = message.reply_to_message
    if replied is None:
        return None
    return find_reel_url(replied.text or replied.caption or "")


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
    """The status line, then the reel's link, then its details.

    The link is not decoration here. Re-filing a reel works by replying to its
    card, and the bot recognizes which reel that is by reading the link back
    out of the card being replied to — so a confirmation that omitted it was
    the one card in the bot you could not correct by reply, on the very screen
    where a misfiling is most likely to be noticed.
    """
    status = "Already saved that one." if already_saved else "Saved!"
    link = f'<a href="{_esc(reel.url)}">{_esc(reel.url)}</a>'
    return _describe_reel(reel, lead=f"{status}\n{link}")


class ReelVaultBot:
    def __init__(self, vault: Vault, token: str) -> None:
        self._vault = vault
        self._pending_manual_caption: dict[int, str] = {}
        self._pending_collection_choice: dict[int, NeedsCollectionChoice] = {}
        # Reels whose video is still to be read. A queue with one worker
        # rather than a task per save: reading a video is a download plus a
        # transcription plus a run of vision calls, all against free tiers
        # that rate-limit, and twenty reels shared in a burst would otherwise
        # start twenty downloads at once and fail most of them.
        self._media_queue: asyncio.Queue[str] = asyncio.Queue()
        self._media_worker: asyncio.Task[None] | None = None
        self._app = (
            Application.builder().token(token).post_init(self._on_start).build()
        )
        self._app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._on_message)
        )
        self._app.add_handler(CallbackQueryHandler(self._on_callback))

    def run(self) -> None:
        self._app.run_polling()

    async def _on_start(self, _app: Application) -> None:
        """Start the media worker, and give it the work a previous run left.

        The queue lives in this process and nothing else, so a restart in the
        middle of reading a video would otherwise lose it permanently — and
        invisibly, since a reel missing its transcript looks exactly like one
        that never had a video worth reading. Nobody would find out until an
        answer was quietly worse for it.
        """
        self._media_worker = asyncio.create_task(self._read_videos())
        for url in self._vault.resume_pending_media():
            self._queue_media(url)

    def _queue_media(self, url: str) -> None:
        self._media_queue.put_nowait(url)

    async def _read_videos(self) -> None:
        """One reel at a time, forever.

        `to_thread` because the vault is synchronous and this work is long:
        left on the event loop it would stall every other message for the
        minutes a download and transcription take, which is the whole thing
        this queue exists to avoid.
        """
        while True:
            url = await self._media_queue.get()
            try:
                await asyncio.to_thread(self._vault.process_media, url)
            except Exception:
                # A failure here is one reel without a transcript. Letting it
                # end the worker would be every later reel without one, with
                # no sign anything had stopped.
                logger.exception("Reading the video for %s failed", url)
            finally:
                self._media_queue.task_done()

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

        replied_to = _replied_to_reel_url(message)
        if replied_to is not None:
            await self._handle_refile(message, replied_to, text)
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
            # Queued after the confirmation, never before it: the point of
            # the queue is that sharing a reel stays as fast as it is today,
            # and reading its video takes minutes.
            self._queue_media(result.reel.url)
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
        # The confirmation is where a misfiling is most likely to be spotted,
        # so it carries the same Move button every other card does.
        markup = _move_keyboard(shortcode_of(result.reel.url) or "")
        if not result.thumbnail_url:
            await message.reply_text(
                text, parse_mode=ParseMode.HTML, reply_markup=markup
            )
            return

        try:
            sent = await message.reply_photo(
                photo=result.thumbnail_url,
                caption=text,
                parse_mode=ParseMode.HTML,
                reply_markup=markup,
            )
        except TelegramError as exc:
            # A picture is a nicety; the reel is already saved either way.
            logger.info("Could not send thumbnail for %s: %s", result.reel.url, exc)
            await message.reply_text(
                text, parse_mode=ParseMode.HTML, reply_markup=markup
            )
            return

        if sent.photo:
            self._vault.attach_thumbnail(result.reel.url, sent.photo[-1].file_id)

    async def _handle_refile(self, message: Message, url: str, reply: str) -> None:
        collection, subcollection = _parse_collection_reply(reply)
        if not collection:
            await message.reply_text(
                "Reply with where it should go, like "
                "<code>Entrepreneurship / Small Business</code>.",
                parse_mode=ParseMode.HTML,
            )
            return

        reel = self._vault.refile(
            url, collection=collection, subcollection=subcollection
        )
        if reel is None:
            await message.reply_text("I don't have that reel saved.")
            return

        await message.reply_text(
            f"Moved to <b>{_format_location(reel)}</b>.",
            parse_mode=ParseMode.HTML,
            reply_markup=_undo_keyboard(shortcode_of(reel.url) or ""),
        )

    async def _on_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        query = update.callback_query
        if query is None or not query.data:
            return
        action, _, rest = query.data.partition(":")
        shortcode, _, collection = rest.partition(":")

        if action == MOVE_OPEN:
            await query.answer()
            await self._swap_keyboard(
                query, _collection_picker(shortcode, self._vault.collections())
            )
        elif action == MOVE_CANCEL:
            await query.answer()
            await self._swap_keyboard(query, _move_keyboard(shortcode))
        elif action == MOVE_TO:
            # A button carries a collection only. The sub-collection a reel
            # had belonged to the shelf it is leaving, so it is not carried
            # across; replying to the card sets both.
            reel = self._vault.refile(
                url_for_shortcode(shortcode), collection=collection
            )
            if reel is None:
                await query.answer("I don't have that reel saved.", show_alert=True)
                return
            await query.answer(f"Moved to {collection}")
            await self._redraw_card(query, reel, _undo_keyboard(shortcode))
        elif action == MOVE_UNDO:
            restored = self._vault.undo_last_move(url_for_shortcode(shortcode))
            if restored is None:
                await query.answer("Nothing to undo for that reel.", show_alert=True)
                return
            await query.answer(f"Back in {restored.collection}")
            await self._redraw_card(query, restored)

    async def _swap_keyboard(
        self, query: CallbackQuery, markup: InlineKeyboardMarkup
    ) -> None:
        try:
            await query.edit_message_reply_markup(reply_markup=markup)
        except TelegramError as exc:
            logger.info("Could not update card buttons: %s", exc)

    async def _redraw_card(
        self,
        query: CallbackQuery,
        reel: SavedReel,
        markup: InlineKeyboardMarkup | None = None,
    ) -> None:
        """Rewrite the card in place, so it stops naming the shelf the reel
        has just left."""
        body = _format_reel_detail(reel)
        markup = markup or _move_keyboard(shortcode_of(reel.url) or "")
        # A callback's message can come back as an InaccessibleMessage (too
        # old for Telegram to hand over), which carries no content to inspect.
        card = query.message
        try:
            if isinstance(card, Message) and card.photo:
                await query.edit_message_caption(
                    caption=body, parse_mode=ParseMode.HTML, reply_markup=markup
                )
            else:
                await query.edit_message_text(
                    text=body, parse_mode=ParseMode.HTML, reply_markup=markup
                )
        except TelegramError as exc:
            logger.info("Could not redraw card for %s: %s", reel.url, exc)

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
        elif isinstance(answer, CompareAnswer):
            await message.reply_text(
                _render_comparison(answer), parse_mode=ParseMode.HTML
            )
            await self._send_reel_cards(message, answer.reels)
        elif isinstance(answer, ExtractAnswer):
            if not answer.items:
                await message.reply_text(NOTHING_TO_COMPILE_REPLY)
                return
            await message.reply_text(
                _render_items(answer.items), parse_mode=ParseMode.HTML
            )
            await self._send_reel_cards(message, answer.reels)
        elif isinstance(answer, NoMatch):
            await message.reply_text(NO_MATCH_REPLY)

    async def _reply_with_reel(
        self, message: Message, reel: SavedReel, text: str | None = None
    ) -> None:
        """One reel, as a picture the user can recognize where we have one."""
        body = text if text is not None else _format_reel_detail(reel)
        markup = _move_keyboard(shortcode_of(reel.url) or "")
        if reel.thumbnail_ref:
            await message.reply_photo(
                photo=reel.thumbnail_ref,
                caption=body,
                parse_mode=ParseMode.HTML,
                reply_markup=markup,
            )
        else:
            await message.reply_text(
                body, parse_mode=ParseMode.HTML, reply_markup=markup
            )

    async def _send_reel_cards(self, message: Message, reels: list[SavedReel]) -> None:
        """One message per reel — the picture sits directly under its own
        link and details rather than in a separate album disconnected from
        the text list above it."""
        for reel in reels:
            await self._reply_with_reel(message, reel)


def build_bot(vault: Vault, token: str) -> ReelVaultBot:
    return ReelVaultBot(vault, token)
