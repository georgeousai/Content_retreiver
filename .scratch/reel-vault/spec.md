Status: ready-for-agent

# Reel Vault — Sort & Retrieve Saved Instagram Reels

## Problem Statement

The user saves a large number of Instagram Reels (and, eventually, LinkedIn posts and blog links) across platforms. Manually sorting them into folders does not scale, and once saved, finding a specific reel — or pulling together information scattered across many reels on the same topic (e.g. "50 reels of AI interview questions") — requires scrolling through and rewatching an "ocean" of saved content. There is currently no way to organize saved reels by topic automatically, or to ask a question and get an answer synthesized across a whole set of them.

## Solution

A personal vault app: the user shares a Reel link from Instagram's native share sheet to a Telegram bot. The app extracts the reel's caption, automatically tags it by topic (no manual foldering), and stores it with a semantic embedding. Later, in the same Telegram chat, the user can ask to retrieve a specific saved reel or ask a question that should be answered by summarizing/aggregating across a semantically-matched set of saved reels (e.g. "give me all the interview questions from my AI reels").

## User Stories

1. As the user, I want to share a Reel link from Instagram directly to a Telegram bot, so that saving a reel takes one tap and no app-switching beyond the share sheet.
2. As the user, I want the app to automatically read the reel's caption without me typing anything, so that I don't have to manually describe what I just saved.
3. As the user, I want the app to automatically tag a saved reel with relevant topics, so that I never have to manually pick or create a folder.
4. As the user, I want a reel to be able to carry multiple tags at once, so that a reel about "AI interview questions" can show up under both "AI" and "Interview Prep" without me having to choose one bucket.
5. As the user, I want tags/topics to be created automatically as new subjects come up, so that I never have to pre-define a folder structure before I start saving.
6. As the user, I want to ask the bot in plain language for a specific reel (e.g. "find that reel about transformer architecture"), so that I don't have to scroll through my saved items.
7. As the user, I want to ask the bot for all the reels in a given topic/collection, so that I can browse everything I've saved on a subject.
8. As the user, I want to ask the bot to summarize or aggregate content across a set of reels (e.g. "give me all the interview questions from my AI reels"), so that I get the synthesized answer without watching every reel myself.
9. As the user, when the bot answers a retrieval request, I want it to give me back the original Instagram link for a matched reel, so that I can reopen and watch it in Instagram itself.
10. As the user, if I accidentally share a reel link I've already saved, I want the bot to tell me it's already saved (and show its tags) rather than creating a duplicate entry.
11. As the user, if the app cannot extract a caption from a shared link (extraction fails), I want the bot to tell me and ask me to paste the caption manually, so that I don't end up with a silently broken, untagged entry.
12. As the user, I want the whole intake-to-tagging pipeline to run at effectively zero recurring cost, so that I can use it freely without worrying about per-reel API charges.
13. As the user, I want the app to run without needing to set up or pay for server hosting, so that I can start using it immediately from my own machine.
14. As the user, I want my saved reels and tags to persist across restarts of the bot process, so that stopping and restarting my machine doesn't lose my vault.
15. As the user, I want this to work for only my own saved reels (no other users), so that v1 stays simple and I'm not exposed to multi-user data/privacy concerns before the concept is proven.
16. As the user, I want the system built so that LinkedIn posts and blog links can be added as additional sources later, so that today's Instagram-only choice doesn't require a rewrite down the line.
17. As the user, I want the system built so that audio transcription and on-screen text (OCR) extraction can be added later, so that reels whose real content isn't in the caption can eventually be covered without re-architecting.
18. As the user, I want a dedicated web/app UI to be addable later on top of the same vault, so that Telegram-only in v1 doesn't lock me out of a richer browsing experience down the line.

## Implementation Decisions

- **Core seam**: A single core module ("the vault") exposes exactly two operations to the outside world:
  - `save_reel(url) -> SavedReel` — given an Instagram Reel URL, extracts the caption, generates tags and an embedding, stores the reel, and returns the saved record (or a "duplicate" / "extraction failed" result).
  - `ask(query) -> Answer` — given a free-text query, performs semantic search over stored reels' embeddings, and returns either a single matched `SavedReel` (with its link) or a synthesized/aggregated answer across a matched set of reels.
  - All environment-dependent behavior (Telegram transport, Instagram caption fetching, the tagging/summarization LLM, the embedding model, persistence) is injected into the vault as adapters. The Telegram bot itself is a thin wrapper that only calls `save_reel` and `ask` and relays their results as chat replies.
- **Intake adapter (caption extraction)**: On receiving a URL, try Instagram's oEmbed endpoint first. If the returned caption is empty or truncated, fall back to an unofficial extraction method (e.g. a `yt-dlp`-based fetch) for the caption text only — no video/audio download. If both fail, return an "extraction failed" result so the bot can ask the user to paste the caption manually; the manually pasted caption re-enters the same tagging/embedding path as an extracted caption.
- **Duplicate handling**: Before saving, `save_reel` checks for an existing entry with the same normalized Instagram URL. If found, it returns the existing `SavedReel` (with its tags) instead of creating a new entry — no duplicate rows.
- **Tagging**: The caption is sent to an LLM (via Groq's free-tier API, open-source Llama-family model) which returns zero or more topic tags. Tags are open-vocabulary (the model can introduce new tags freely) — there is no fixed/predefined tag list and no single-folder constraint; a `SavedReel` can carry multiple tags.
- **Embedding/semantic search**: The caption text is embedded using a local open-source embedding model (e.g. `all-MiniLM-L6-v2` via `sentence-transformers`), run on CPU with no external API call. Embeddings are stored alongside each `SavedReel` and queried via cosine-similarity search for both "find this one reel" and "find the set of reels relevant to this topic" style queries.
- **Persistence**: Postgres with the `pgvector` extension (e.g. Supabase free tier) holds one row per `SavedReel`: normalized URL, raw caption, tag list, embedding, and a saved timestamp. No video files or media blobs are stored.
- **Query answering**: `ask(query)` embeds the incoming query, retrieves the top semantically-matching `SavedReel`s, and:
  - If the query reads as a request for one specific item, returns that single reel's link (plus tags).
  - If the query reads as a request to aggregate/summarize across a topic (e.g. "give me all the interview questions from..."), passes the matched captions to the LLM (Groq) to produce a synthesized answer, returned as chat text.
  - This distinction (single-item vs. aggregate) is made by the LLM/query-handling logic, not by the user picking a mode explicitly.
- **Telegram bot**: Runs via long-polling (no public webhook, no inbound network exposure needed) so it can run as a local process on the user's own machine. It is the only intake and query channel for v1.
- **Hosting**: Local machine only for v1; no cloud hosting/deployment in this spec. If the bot process is not running when a link is shared, Telegram queues the message and it is processed on the next run.
- **Cost constraints**: Tagging/summarization uses Groq's free tier; embeddings run locally; Postgres uses a free tier. No paid LLM API calls are part of v1.
- **Explicitly not built in this spec**: LinkedIn/blog ingestion, audio transcription, OCR, video file storage/download, multi-user accounts/auth, a web/app UI, and always-on/cloud hosting. The core-seam design (adapters behind `save_reel`/`ask`) is intended to make these additive later, but none of them are implemented now.

## Testing Decisions

- Tests target the single seam (`save_reel`, `ask`) directly — no test should spin up a real Telegram bot, hit the real Instagram oEmbed endpoint or scraper, call the real Groq API, or run against a real Postgres/pgvector instance. Each of those is a fake/stub adapter injected into the vault for tests: a fake caption fetcher returning canned captions (including an "extraction failed" case), a deterministic fake tagger, a fake/deterministic embedding function, and an in-memory (or test-only) store.
- Good tests here assert on the vault's external behavior — the `SavedReel`/`Answer` returned from `save_reel`/`ask` — not on internal call sequencing or which adapter method was invoked in what order.
- Cases to cover: saving a new reel produces the expected tags/embedding-backed record; saving a duplicate URL returns the existing record without creating a new one; a failed extraction returns a result the bot layer can turn into a "please paste the caption" prompt, and a manually supplied caption flows through the same tagging/storage path; a single-item query returns the correct reel's link; an aggregate query returns a synthesized answer built from the matched captions only (not unrelated ones).
- The Telegram-adapter layer itself (parsing incoming messages, formatting replies) is thin enough that it does not need its own test suite beyond a smoke check that it correctly delegates to `save_reel`/`ask` — the interesting logic lives behind the seam and is covered there.
- No existing test suite or prior art exists in this repo yet (greenfield project) — this establishes the first testing pattern for the codebase.

## Out of Scope

- LinkedIn posts and blog links as content sources.
- Audio transcription and on-screen text (OCR) extraction from reels.
- Downloading or storing the actual reel video file.
- Multi-user support: accounts, authentication, per-user data isolation.
- Any dedicated web or app UI — Telegram is the only interface.
- Always-on/cloud hosting (e.g. Railway, Fly.io) — v1 runs on the user's local machine only.
- Rate-limit handling beyond what Groq's free tier naturally allows for personal-scale usage.

## Further Notes

- This spec follows directly from a `/grill-me` session (2026-08-27) that walked through platform scope, intake channel, extraction depth, storage, organization strategy, retrieval interface, LLM/embedding cost stack, hosting, and duplicate/failure handling. The full session record is saved in Notion on the "RR" page.
- The `RR` project directory was empty prior to this spec — there is no existing codebase, `CONTEXT.md`, or ADRs to reconcile with; this spec establishes the first domain vocabulary (`SavedReel`, vault, tag, `save_reel`, `ask`) for the project going forward.
- The core-seam split (vault operations vs. adapters) is deliberately chosen so that later phases (LinkedIn/blogs, audio/OCR, multi-user, a web UI, cloud hosting) can be added by swapping or adding adapters without changing the `save_reel`/`ask` contract — but no work toward those phases is included here.
