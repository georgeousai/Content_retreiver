Status: ready-for-agent

# Reel Vault — Chat Orchestration Rewrite

## Problem Statement

`ReelVaultBot._on_message` (`src/reel_vault/bot.py`) is the entire conversation
model, and it is a priority chain checked in a hardcoded, undocumented order:
a reel URL, then a reply to a card, then an open manual-caption prompt, then
an open collection-choice prompt, then an almost-matching Instagram link, and
only then — as the unconditional fallback — a fresh semantic search of the
whole vault via `Vault.ask`. Two of those five checks are per-chat state kept
in plain `dict[int, ...]` instance attributes (`_pending_manual_caption`,
`_pending_collection_choice`); the rest are stateless lookups against the
incoming message itself. This produces four faults, each observed live in
the running vault, not theoretical:

1. **No "I don't understand."** Nothing in the chain can decline to answer.
   Any message that isn't a URL, a reply-to-card, or an answer to an open
   prompt falls straight into `Vault.ask`, which embeds it and searches the
   whole vault — even a message with no topic in it at all. Live: right
   after a good summary of two AI-interview reels, "I don't want to watch
   the reels. I want you to summarize them for me" was embedded as a search
   query and matched an unrelated biceps reel.
2. **Pending states have no exit.** Neither `_pending_manual_caption` nor
   `_pending_collection_choice` has a cancel path or a timeout; both are
   unconditionally popped and consumed by whatever the user's next message
   happens to be. Live: after "please paste the caption, I couldn't read
   it," the user's next message — an unrelated question — was saved
   verbatim as that reel's caption (`instagram.com/p/Dc0WwxqqLx8`, caption
   "Show me all the reels related to Google interview.", filed under AI >
   Interview, `processing_status=failed`). It later matched a real query
   about Google interviews, because its caption *is* that query.
3. **State is in-memory only.** Both pending dicts live on the
   `ReelVaultBot` instance and nowhere else, so a restart silently forgets
   every open question. This is the one part of the app that regressed
   from a pattern already built elsewhere: `Vault.resume_pending_media` /
   `processing_status` exist specifically so the media pipeline survives a
   restart; conversation state was never given the same treatment.
4. **Presentation is welded to answer kind.** `_handle_query` always renders
   `AggregateAnswer` as prose text *plus* one card per reel
   (`_render_summary` then `_send_reel_cards`), unconditionally. There is no
   way to ask for text only. This is what the user in fault #1's example was
   actually trying to do — "I want you to summarize them for me," not shown
   the reels again — and had no way to say.

## Solution

Replace the hardcoded priority chain with an explicit, ordered resolution
over one unified `ChatState`, persisted so it survives a restart, ending in
exactly one narrow LLM decision — never a full agentic loop, never a second
LLM call per message — for the one case that is genuinely ambiguous: an
incoming message that is none of URL / open-state-answer / command / card
reply. That one decision classifies the message as continuing the previous
turn, starting a new one, or neither (and "neither" is now a real, reachable
outcome — "I don't understand" becomes possible for the first time). A small
per-chat "last turn" record lets a continuation be resolved without
re-searching the vault, and a `Presentation` value decouples how an answer is
shown from what kind of answer it is.

Resolution order per message, stop at first match:

1. Contains a reel URL → save (deterministic, unchanged).
2. A `ChatState` is open for this chat → this message answers it
   (deterministic); every open state accepts `/cancel` and expires after a
   fixed idle timeout, checked lazily on next read rather than swept in the
   background.
3. Starts with `/` → a command (`/cancel` when nothing is open, and whatever
   else this ticket's issues add) — genuinely new: no `CommandHandler` is
   registered today, so unprefixed commands are currently just dropped by
   the message filter.
4. Is a reply to a card → refile (deterministic, unchanged mechanism — the
   reel is read back out of the card's own printed link).
5. Otherwise, classify: `NEW` / `MODIFIER` / `NEITHER`, decided from the
   message text alone (no last-turn context needed by the model — see
   Implementation Decisions). `NEITHER` replies "I don't understand" and
   calls nothing else. `MODIFIER` resolves against the chat's last-turn
   record if one exists (see below); if none exists, it is treated the same
   as `NEITHER` — there is nothing to modify. `NEW` proceeds to
   `Vault.ask` exactly as today.

## User Stories

1. As the user, when I send a message that isn't a link, a reply to a card,
   an answer to something the bot just asked, or a recognizable follow-up to
   the last answer, I want the bot to say it didn't understand rather than
   silently searching the vault and returning something plausible-looking
   but wrong.
2. As the user, when the bot is waiting on me for something (a caption, a
   collection choice), I want a way to back out (`/cancel`) instead of being
   stuck until I happen to send something that looks like an answer.
3. As the user, if I don't respond to a pending prompt for a while, I want
   the bot to stop waiting on it rather than silently consuming whatever I
   eventually send as the answer to a question I've forgotten was asked.
4. As the user, if the bot restarts while it's waiting on me for something,
   I want that still to be true when it comes back — not silently
   forgotten, and not left waiting forever with no way to ever complete it
   from my side either (see Implementation Decisions on what "surviving a
   restart" means for a UI-facing prompt).
5. As the user, after getting an answer, I want to be able to say "just the
   text" (or similar) and get the same answer without the reel cards, rather
   than getting text-plus-cards unconditionally every time.
6. As the user, after getting an answer, I want to be able to ask for a
   modified version of it — "shorter," "focus on the pricing part" — and
   have the bot work from the same set of reels it just answered from,
   rather than re-searching the vault (which could plausibly return a
   different set entirely).
7. As the user, I want the previous two behaviors to cost no extra waiting
   compared to today — the classification that makes them possible should
   ride on the one LLM call already made per question, not add a second
   round-trip.
8. As the user, I want a message that is neither a new question nor a
   follow-up (chit-chat, a stray remark) to get a plain "I don't understand"
   rather than being embedded and searched anyway.

## Implementation Decisions

- **`ChatState`, one type, replacing the two pending dicts.** A discriminated
  union (`AwaitingManualCaption`, `AwaitingCollectionChoice` — the two states
  that exist today; new states, if any, join this union rather than becoming
  a third dict) keyed by `chat_id`. Only two of the "four checks" the
  original framing of this problem described are actually per-chat dicts
  today (`_pending_manual_caption`, `_pending_collection_choice`); the URL
  check and the reply-to-card check are stateless lookups against the
  incoming message and stay that way — folding them into `ChatState` would
  make "is there an open state" ambiguous with "did this message happen to
  look like a URL," which is not the same question.
- **Persisted, not swept.** `ChatState` is written to Postgres (a
  `chat_state` table: `chat_id`, a JSON payload, `created_at`) rather than
  kept only on the `ReelVaultBot` instance. Unlike
  `Vault.resume_pending_media` — which actively re-queues every pending
  reel at startup because nobody is coming back to ask for it — a chat
  state needs no startup re-drive: it is read lazily, the next time (if
  ever) that chat sends a message. This is deliberately simpler than the
  media pipeline's resume mechanism, not a copy of it.
- **Timeout is a read-time check, not a background job.** Every `ChatState`
  carries `created_at`. Reading it back compares against a fixed idle
  timeout (proposed default: 30 minutes, tunable, not derived from
  anything measured — flag this in review) and treats an expired state as
  absent, clearing it and falling through to step 3 of the resolution
  order. No scheduler, no sweep — a state nobody ever reads again simply
  sits in the table inert, exactly like a `processing_status='failed'` row
  does today.
- **`/cancel` is real command handling, which does not exist today.**
  `_on_message` is registered against `filters.TEXT & ~filters.COMMAND`
  with no `CommandHandler` registered anywhere, so a message starting with
  `/` is currently just dropped. This ticket adds the first real command
  path: a `CommandHandler` (or an explicit prefix check ahead of the
  existing text handler) that recognizes `/cancel`, clears any open
  `ChatState` for that chat, and replies confirming what was cancelled (or
  that there was nothing to cancel).
- **Message classification stays a single LLM call, but moves out of
  `Vault.ask`'s exclusive ownership.** `Vault.ask(query) -> Answer` is
  documented elsewhere in this repo as stateless (the media-pipeline spec's
  Out of Scope: "`ask()` remains fully stateless — no multi-turn/
  conversation-state mechanism is introduced by this feature") and nothing
  here reverses that. `Vault`'s internal classification step —
  `self._query_intent.classify(query, known)`, currently private to `ask` —
  becomes a public `Vault.classify(query) -> QueryClassification`, and
  `QueryClassification` gains one new field: `continuation: Continuation =
  NEW` (`NEW | MODIFIER | NEITHER`), an `Enum` alongside `QueryKind`. A
  second method, `Vault.ask_classified(query, classification) -> Answer`,
  does what the body of today's `ask` does, taking a classification that
  was already computed rather than computing its own. `ask` itself becomes
  `self.ask_classified(query, self.classify(query))` — unchanged behavior,
  same one call. The bot-layer orchestration (see below) calls
  `vault.classify(query)` once per step-5 message; on `NEW` it calls
  `vault.ask_classified(query, classification)` to finish the job without a
  second classification round-trip. `continuation` is decided by the model
  from the message text alone — "just the text," "shorter," a bare pronoun
  reference read as continuation-shaped regardless of whether the chat
  actually has an open last turn to continue. Whether one actually exists
  is a deterministic check the orchestration layer makes afterward,
  keeping the classification call itself free of last-turn state and the
  vault seam exactly as stateless as it is everywhere else in this
  codebase.
  - **This is a genuinely new field on an existing prompt, not a free
    lunch.** `INTENT_SYSTEM_PROMPT` already carries five `QueryKind`
    definitions and worked examples; this repo's own history
    (`known-issues.md`, the summarizer-hallucination and condenser-hook
    entries) shows that an abstract instruction added to a working prompt
    degrades unless it ships with a concrete counter-example and is
    measured against real messages, not assumed. Budget for this in
    testing, not just implementation — see Testing Decisions.
- **"Modifier" is not one thing — split into two, because they need
  different amounts of new machinery.**
  - *Presentation-only modifiers* ("just the text," "no cards," "show me
    the reels only") change nothing about the answer's content — they
    change `Presentation` (below) and re-render the stored last-turn
    `Answer`. Zero additional LLM/vault calls.
  - *Content modifiers* ("shorter," "focus on the pricing part," a bare
    pronoun follow-up that needs resolving against what was just discussed)
    need genuinely new text, but from the *same* reel set the last turn
    already matched — re-running `vault.ask` would re-search and could
    plausibly return a different set of reels for a differently-phrased
    query. These route to a new `Vault.refine(instruction: str, reels:
    list[SavedReel]) -> Answer`, which reuses the existing
    `_written_answer`/`SummarySource` machinery against the given `reels`
    instead of a freshly matched set, with a system prompt scoped to "revise
    the previous answer per this instruction" rather than "answer this
    question from scratch." This is the one place this rewrite adds a
    second LLM call for a single user message, and only for this subcase.
- **`LastTurn`, one small per-chat record**: `query: str`, `answer: Answer`,
  `reels: list[SavedReel]`, written after every `Vault.ask`/`ask_classified`
  /`refine` call that produces one, read only by step 5's `MODIFIER`
  handling. Lives alongside `ChatState` in the same persisted store (same
  `chat_id` key), not a third table — it is conversation state exactly like
  `ChatState` is, just not one that blocks the next message from being
  freely anything.
- **`Presentation{include_text: bool, include_sources: bool, max_cards: int
  | None}`, resolved explicit → sticky → default.** An explicit instruction
  in the current message (from step 5's classification, or the
  presentation-modifier path above) wins; failing that, a sticky per-chat
  preference (persisted, one more small column alongside `ChatState`/
  `LastTurn`) set the last time the user stated one explicitly; failing
  that, a default keyed by `Answer` type (`AggregateAnswer` today: text +
  cards; `ListAnswer`/`SingleItemAnswer`: cards, no separate text). This
  ladder mirrors a pattern already used in this codebase for collection
  assignment (caption analysis → neighbour evidence → `Uncategorized`
  fallback) so it isn't a new shape for this project. Resolution happens
  entirely in the bot layer — `Answer` and `Vault` stay exactly as
  presentation-agnostic as they are today; nothing here touches
  `models.py`'s `Answer` union.
- **`conversation.py`, a new module, scoped narrowly.** The decision logic
  for step 5 — call `vault.classify`, decide `NEW`/`MODIFIER`/`NEITHER`,
  resolve a `MODIFIER` against `LastTurn` if one exists, resolve
  `Presentation` — is pulled out of `bot.py` into pure functions that take
  and return plain values (`ChatState`, `LastTurn`, classification results,
  a small `Action` result type), never a `telegram.Message` or `Update`.
  **The justification is testability, not a second transport.** No other
  transport is planned anywhere in this project's specs, so "reusable by a
  future web client" is not a design goal here and this ticket should not
  be graded against it; the reason to split it out is that step 5 is the
  single most complex piece of logic this rewrite adds, and this repo's own
  testing convention (fakes over mocks, a pure seam per concern —
  `Vault`'s own module docstring: "no knowledge of Telegram... any model
  provider... any other concrete integration") already argues for keeping
  it free of `python-telegram-bot` objects so it can be tested the same way
  `vault.py` is, rather than only through `bot.py`'s existing thin
  smoke-test level. `bot.py` keeps every Telegram call (`reply_text`,
  `reply_photo`, keyboards) and steps 1–4 of the resolution order, which are
  already deterministic and already live there.

## Testing Decisions

- Tests target `conversation.py`'s pure decision functions directly, the
  same way `tests/test_ask.py` targets `Vault.ask` — no test in this file
  spins up a real Telegram bot or a real LLM. Fakes for the extended
  `QueryIntent` (now returning `continuation` too) and the new
  `Vault.refine` follow the existing deterministic-fake pattern in
  `tests/fakes.py`.
- Cases to cover:
  - Steps 1–4 (URL, open `ChatState`, `/cancel`, reply-to-card) still take
    priority over step 5 in every ordering that matters — a message that
    is simultaneously a URL and a reply to a card behaves as it does today
    (regression coverage, not new behavior).
  - `/cancel` with an open `AwaitingManualCaption`/`AwaitingCollectionChoice`
    clears it and the next message is evaluated fresh from step 1, not
    consumed as the answer.
  - `/cancel` with nothing open replies that there was nothing to cancel,
    and does not error.
  - An open `ChatState` older than the timeout is treated as absent on the
    next message — the message falls through to step 3 onward, and the
    stale state does not consume it.
  - `NEITHER`-classified text (this ticket's own "I don't want to watch the
    reels, I want you to summarize them for me" as a named regression case,
    pulled directly from the live failure that motivated this rewrite)
    produces "I don't understand" and calls neither `Vault.ask_classified`
    nor `Vault.refine`.
  - `MODIFIER`-classified text with no `LastTurn` on record is treated the
    same as `NEITHER`.
  - A presentation-only modifier ("just the text") against a `LastTurn`
    re-renders the stored `Answer` under a new `Presentation` and calls
    neither `Vault.ask_classified` nor `Vault.refine`.
  - A content modifier ("shorter") against a `LastTurn` calls
    `Vault.refine` with that turn's `reels`, not a fresh `Vault.ask`/
    `ask_classified` call — asserted on what the fake was called with, the
    same justified exception to "don't assert call sequencing" the
    query-answering spec already used for author-threading.
  - `NEW`-classified text proceeds through `vault.ask_classified` exactly as
    `vault.ask` does today (regression coverage against the existing
    `test_ask.py` suite, now exercised through the split `classify`/
    `ask_classified` pair instead of the single `ask` entrypoint).
  - `Presentation` resolution: an explicit instruction in the current
    message beats a sticky preference beats the per-answer-kind default,
    each tested independently.
  - `ChatState`/`LastTurn` round-trip through the persisted store
    (Postgres-backed `ReelStore` extension, or a sibling store — see issue
    01) the same way `processing_status` already does, including a restart
    (fresh `Vault`/store instance) still finding a state that predates it.
- The `INTENT_SYSTEM_PROMPT` extension for `continuation` gets the same
  live-model measurement treatment this repo already requires for prompt
  changes (see `known-issues.md`'s summarizer and condenser entries): a
  handful of real or realistic messages per case (`NEW`, both `MODIFIER`
  subtypes, `NEITHER` — including the exact live failure text from fault
  #1), run against the real configured model, not just asserted against a
  fake. This is new evidence to gather during implementation, not
  something this spec can supply in advance.
- `bot.py` keeps its existing thin smoke-test level (`tests/test_bot.py`) —
  verifying it delegates to `conversation.py` and renders whatever `Action`
  comes back, not re-testing the decision logic itself.

## Out of Scope

- A full agentic loop (the model deciding what to do on every message,
  including "here's a link"). Rejected in favor of the deterministic
  five-step order above for the same reason this project has never put an
  LLM call in front of a deterministic path: 348 existing tests and every
  adapter faked depend on the vault seam staying predictable, and nothing
  observed in the four faults needs that traded away.
- A pure state machine with no continuation/modifier support. Considered
  and rejected on its own — it would fix faults #2 and #3 completely but
  leaves fault #1's own motivating example unaddressed, since "I want you
  to summarize them for me" needs to be recognized as *something*
  (unfortunately, in that live case, as `NEITHER` — it names no topic —
  but a differently-phrased version of the same intent plausibly reads as
  a `MODIFIER`), not just declined by default.
- Any second transport (web, REST, etc.). `conversation.py`'s pure-function
  shape is a testability choice for this rewrite, not a step toward one;
  no work here is scoped, sized, or justified against a future consumer
  that doesn't exist in any other spec in this repo.
- Multi-user separation. Still the single largest open architectural item
  per `.scratch/reel-vault-query-answering/STATUS.md`; `ChatState` and
  `LastTurn` are keyed by `chat_id` exactly the way every other per-chat
  concern in this bot already is, and inherit the same "one shared vault"
  limitation everything else does. Not this rewrite's problem to solve.
- Tuning the idle timeout value against real usage data. A default is
  proposed above (30 minutes) with no measurement behind it — flagged
  explicitly rather than presented as decided.
- Editable tags, bulk moves, delete/forget, pagination, retrieval-threshold
  work, and every other item already tracked in `.scratch/TODO.md` —
  unrelated to conversation orchestration, untouched by this spec.
- The condenser's occasional under-keeping of short numeric claims and
  `content_of`'s blind spot for a reply truncated *with* partial content
  (both flagged in the originating task description) — already tracked in
  `.scratch/TODO.md`, not part of this rewrite.

## Further Notes

- This spec responds to a session that first attempted a code-level fix
  directly (a stashed, half-finished "UNCLEAR query kind + Unclear answer"
  spike) before any design existed for where the classification and its
  resolution should actually live. That spike is not carried forward here
  and should be discarded rather than resumed — the design in this spec
  (splitting `Vault.classify`/`ask_classified`, keeping the vault seam
  stateless, and resolving continuations in `conversation.py` against a
  persisted `LastTurn`) is a different shape from "a new `QueryKind` inside
  `ask`," specifically because a `QueryKind` living entirely inside
  `Vault.ask` has no access to `LastTurn` and cannot resolve a `MODIFIER`
  on its own — which is very likely *why* that spike stalled before it
  worked, though its actual contents were not reviewed in writing this
  spec (it was left stashed, unread, per instruction).
- The four faults in the Problem Statement are all drawn from live use of
  the running bot, the same evidentiary standard this repo's
  `known-issues.md` already holds itself to — this spec deliberately does
  not add a fault that hasn't been observed.
- `Vault`'s module docstring already states its contract precisely: "no
  knowledge of Telegram, any model provider, Postgres, or any other
  concrete integration." Every decision above was checked against that
  sentence before being written down; the one field this spec adds to a
  `Vault`-owned type (`QueryClassification.continuation`) is deliberately
  just an enum value, decided from message text alone, carrying no
  Telegram- or session-shaped state across the boundary.
