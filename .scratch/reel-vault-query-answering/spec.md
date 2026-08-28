Status: ready-for-agent

# Reel Vault — Richer Query Answering (List, Author, Thumbnails)

## Problem Statement

Reel Vault's `ask(query)` today only distinguishes "find me one reel" from "synthesize an answer across matched reels." That binary split leaves several real user needs unmet: asking to browse everything matching a topic returns a synthesized paragraph (or silently truncates to 5 results) instead of a list; asking who posted what can't be answered because author info never reaches the summarizer; asking for a specific creator's reels can't be answered at all since there's no way to filter by author; and every reply is text-only, so recognizing "which reel was that again" means rereading captions rather than recognizing a thumbnail.

## Solution

Extend the vault's query-answering path (`ask`) with a richer, four-way understanding of what the user wants — find one item, browse a list of matches, get a synthesized answer across matches, or pull everything from one creator — and thread author information all the way from extraction through to synthesized answers. Separately, extend the save path so every saved reel carries a durable thumbnail reference, so replies (single, list, or aggregate) can show the reel's picture, not just its link.

## User Stories

1. As the user, I want to ask "show me all my reels about X" and get back the full list of matches (not a synthesized paragraph, and not silently capped at 5), so that I can browse everything I've saved on a topic.
2. As the user, I want to ask a synthesizing question like "give me all the interview questions from my AI reels" and get a written answer distinct from a browse/list request, so that the vault gives me the right shape of answer for the right kind of question.
3. As the user, I want to ask for all the reels I've saved from a specific creator (e.g. "show me @gymshark's reels") and get that list directly, so that I don't have to phrase it as a topic search when it isn't one.
4. As the user, I want a synthesized answer to be able to tell me which creator said what (e.g. "grouped by who posted them"), so that I can distinguish contributions across creators when the caption text actually contains that content.
5. As the user, I want it to be clear (by the answer simply not containing information that was never in the caption) when the content I'm asking about only exists in the reel's video/audio and not its caption, so that I understand this is a caption-only limitation rather than the app being broken.
6. As the user, I want every reply that shows me a reel (single, list, or aggregate) to include that reel's thumbnail picture, so that I can visually recognize the reel I'm looking for and tap through to it.
7. As the user, I want the thumbnail to be captured and stored automatically when I save a reel, so that I never have to take any extra action beyond sharing the link, exactly like today.
8. As the user, I want a reel's thumbnail to still display correctly months after I saved it, so that an old save isn't a broken image by the time I come back to look for it.
9. As the user, I want the existing single-item retrieval behavior ("find that reel about X") to keep working exactly as it does today, so that this extension doesn't regress what already works.
10. As the user, I want "show me all" queries to actually mean "all, up to a generous limit" rather than being silently capped at 5 results, so that a topic I've saved 20+ reels on isn't truncated without me knowing.
11. As the user, I want synthesized (aggregate) answers to stay bounded to a moderate number of matched reels even if more exist, so that one broad query doesn't blow through the shared Groq free-tier budget in a single call.
12. As the user (looking ahead, once this becomes a multi-user app), I want per-intent match limits to be tunable rather than hardcoded forever, so that limits can later be adjusted per user/tier without a redesign.

## Implementation Decisions

- **Query intent, four-way**: The `QueryIntent` port changes from a boolean `is_aggregate(query) -> bool` to `classify(query) -> QueryClassification`, a single LLM call returning one of four kinds — `SINGLE`, `LIST`, `AGGREGATE`, `AUTHOR_FILTER` — plus an optional extracted author string (populated only for `AUTHOR_FILTER`). One classification call drives the whole branch in `ask()`; there is deliberately no second LLM call to separately detect "is there an author in this query," since every query is free text through the same entrypoint and splitting the call would double Groq usage for no benefit.
- **`ask()` routing**:
  - `AUTHOR_FILTER` skips embedding search entirely and calls a new `ReelStore.find_by_author(name)` — a plain filter, not a semantic match. Returns a `ListAnswer`.
  - `SINGLE` behaves as today: top embedding match returned as `SingleItemAnswer`.
  - `LIST` returns the matched reels as a new `ListAnswer` type, with no LLM summarization call.
  - `AGGREGATE` behaves as today (matched captions summarized by the LLM into `AggregateAnswer`), but each caption is now paired with its author when handed to the summarizer.
- **New `Answer` variant — `ListAnswer`**: `ListAnswer{query, reels}` is added as its own dataclass rather than reusing `AggregateAnswer` with an empty `text`. Rationale: a shared type with a sometimes-meaningless field is an implicit invariant every caller has to remember to check; a distinct type makes the two cases exhaustively distinguishable by the type checker and keeps `AggregateAnswer.text` always meaningful.
- **Per-intent match limits (`top_k`)**: `top_k` becomes intent-dependent rather than one shared constant. `SINGLE` keeps the current default (~5, top match used). `LIST` uses a generous cap (50) since it costs only a DB read. `AGGREGATE` uses a moderate cap (15) since every matched caption is included in a single Groq prompt, and an unbounded aggregate cap risks exhausting the shared free-tier budget as usage grows. Full pagination ("show 10, then more on request") is explicitly deferred — it is a distinct, stateful-conversation feature, not a fixed-limit fix, and is out of scope here (see Out of Scope).
- **Author threading into the summarizer**: `Summarizer.summarize` changes signature from `(query, captions: list[str])` to `(query, entries)`, where each entry pairs a caption with its `author_handle`/`author_name`. This lets synthesized answers attribute/group content by creator when the caption text itself contains attributable content. It does not and cannot recover content that exists only in a reel's audio/video and never appears in the caption — captions remain the only content source the vault reads from, consistent with the original spec's decision to defer audio transcription/OCR.
- **Author filter on the store**: `ReelStore` gains `find_by_author(name: str) -> list[SavedReel]`, a direct filter (e.g. `WHERE author_handle = ...` in the Postgres adapter), independent of embedding search.
- **Thumbnail capture at save-time**: `ExtractedPost` gains an optional `thumbnail_url` field, populated by the caption-fetcher adapters (oEmbed and/or the yt-dlp fallback) when the underlying extraction exposes one. `save_reel` uses a new adapter port, `ThumbnailStore`, with `store(thumbnail_url: str) -> str | None`, to convert that URL into a durable reference at save-time.
- **Thumbnail storage mechanism**: The `ThumbnailStore` is implemented by a Telegram-backed adapter that uploads the thumbnail image through the bot once and returns the Telegram `file_id` Telegram hands back. That `file_id` — not the raw Instagram CDN URL — is what gets persisted. Rationale: Instagram's thumbnail URLs are signed/expiring, so storing them directly would silently break old reels' images over time; Telegram `file_id`s do not expire, cost nothing extra, and require no separate blob storage, consistent with the zero-recurring-cost constraint. This is fully automatic — no additional user action beyond sharing the link, matching today's flow.
- **Model changes to carry the thumbnail reference**: `SavedReel` and `NeedsCollectionChoice` both gain `thumbnail_ref: str | None`, following the same "compute once, carry through `NeedsCollectionChoice.assign_collection`" pattern already used for `tags`/`embedding`/author fields — a paused save (awaiting a collection choice) must not need to re-fetch or re-upload the thumbnail when it's finished.
- **Bot-layer reply formatting**: The bot's `_handle_query` currently drops `AggregateAnswer.reels` entirely (only sends `answer.text`) even though the core already returns the matched list — this is a pre-existing formatting gap in the bot layer, not a core-model gap, and gets fixed as part of this work: aggregate replies include the matched reels' links (and thumbnails), not just the synthesized text. `ListAnswer` and `SingleItemAnswer` replies also render each reel's thumbnail (via its `thumbnail_ref`) alongside the existing text/link/tags formatting.

## Testing Decisions

- Tests target the vault seam (`save_reel`, `ask`) directly, per existing project convention — no test spins up a real Telegram bot, hits real Instagram/Groq/Postgres. Fakes for the new/changed ports (`QueryIntent.classify`, `Summarizer.summarize` with author entries, `ReelStore.find_by_author`, `ThumbnailStore.store`) follow the same deterministic-fake pattern already used in `tests/fakes.py` and `tests/conftest.py`.
- Cases to cover, extending `tests/test_ask.py`'s existing structure (`_seeded_vault` pattern):
  - A `LIST`-classified query returns a `ListAnswer` containing the matched reels, with no call to the summarizer.
  - An `AGGREGATE`-classified query still returns `AggregateAnswer` unchanged in shape, but the fake summarizer receives author info alongside each caption (assert on what the fake was called with, to verify author actually reached it — an exception to the "don't assert call sequencing" norm, justified because author-threading is the behavior under test).
  - An `AUTHOR_FILTER`-classified query calls `find_by_author` and returns a `ListAnswer` without touching the embedder/store's `search`.
  - `SINGLE` behavior is unchanged (existing tests in `test_ask.py` continue to pass with `classify` swapped in for `is_aggregate`).
  - `LIST` and `AGGREGATE` each respect their own `top_k` — seed more matching reels than the smaller cap and assert the returned/summarized set is bounded accordingly.
  - Saving a reel whose fetched post includes a `thumbnail_url` results in a `SavedReel.thumbnail_ref` populated from the fake `ThumbnailStore`; a post with no `thumbnail_url` results in `thumbnail_ref is None` and no call to the thumbnail store.
  - A save that pauses on `NeedsCollectionChoice` carries `thumbnail_ref` through to `assign_collection`'s resulting `SavedReel` without a second `ThumbnailStore` call (extending the existing "finishes the save without recomputing anything" test in `tests/test_collections_and_author.py`).
- The Telegram-adapter/bot layer stays covered by a thin smoke-test level, per existing project convention (`tests/test_bot.py`) — verifying it delegates to the vault and renders each `Answer`/thumbnail correctly, not re-testing vault logic.

## Out of Scope

- Pagination / "show more" follow-up browsing (fixed per-intent caps only, in this spec).
- Audio transcription or OCR of reel video content — the summarizer can only attribute/synthesize from what is present in caption text; content that exists only in a reel's audio or on-screen text remains unreachable until a transcription/OCR adapter is added in a future phase. (This is a known, actively-tracked priority gap, not abandoned scope — see Further Notes.)
- Multi-user support, per-user rate limiting/tiering — the "tunable limits" user story (#12) is about not hardcoding values in a way that blocks that future work, not about building multi-user support now.
- Any dedicated web/app UI — Telegram remains the only interface.
- Downloading or storing full-resolution reel video/media — only a thumbnail image reference is stored.

## Further Notes

- This spec extends the original `reel-vault` spec (`.scratch/reel-vault/spec.md`) and its four shipped issues (01-04); it does not restate decisions already settled there (core seam, duplicate handling, tagging, embedding/persistence stack, hosting). It follows a `/grill-with-docs` session (2026-08-28) that resolved the four "known gaps" called out after the original build: missing author threading in aggregate answers, aggregate answers not surfacing the matched link list, `top_k=5` silently capping "all" queries, and no distinct browse/list intent — plus a fifth requirement surfaced in the same session, showing a thumbnail so the user can visually recognize a matched reel.
- Audio/OCR-based transcription was flagged during that session as an important priority for a near-future phase — captions alone will never surface content that a creator only speaks or shows on-screen rather than writing out, and several user-facing "aggregate/attribute" queries will keep hitting this ceiling until it's built. It stays formally out of scope here (this spec is caption-content-only, matching the original spec's decision), but is called out explicitly so it isn't lost as background scope-creep text again.
</content>
