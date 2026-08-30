# Reel Vault

**Share a Reel to a Telegram bot. Ask for it back in plain English — months later.**

A personal vault for the ocean of Instagram Reels you save and never find again. It reads each reel's caption, tags it by topic automatically, and stores it with a semantic embedding — so later you can ask *"find that reel about transformer architecture"* or *"give me all the interview questions from my AI reels"* and get a real answer instead of a scroll session.

Runs entirely on your own machine. No server, no hosting bill, no per-reel API charges.

---

## The problem

You save reels constantly. Sorting them into folders doesn't scale, and it forces a choice you shouldn't have to make — is a reel about AI interview questions filed under *AI* or *Interview Prep*?

Worse, once something is saved it's effectively gone. Finding one specific reel means scrolling an endless grid of thumbnails. And when the information you want is *spread across fifty reels* on the same topic, there's no way to pull it together short of rewatching all fifty.

Reel Vault fixes both halves: **automatic organization on the way in**, and **question-answering on the way out**.

---

## How it works

```mermaid
flowchart LR
    A["📱 Instagram<br/>share sheet"] --> B["💬 Telegram bot"]
    B --> C{"save_reel(url)"}

    C --> D["Caption + author<br/>extraction"]
    D --> D2["📁 Collection<br/>(reuses existing)"]
    D2 --> E["🏷️ Tagging<br/>(LLM)"]
    E --> F["🧮 Embedding<br/>(local, CPU)"]
    F --> G[("🗄️ Postgres<br/>+ pgvector")]
    G --> B

    B --> H{"ask(query)"}
    H --> J{"What kind<br/>of question?"}
    J -->|by creator| M["🗂️ Filter by author<br/>(no embedding)"]
    J -->|single / list / aggregate| I["Semantic<br/>search"]
    I --> G
    M --> G
    I --> K["🔗 One reel<br/>+ picture"]
    I --> N["📜 List of matches<br/>+ pictures"]
    I --> L["📝 Synthesized answer<br/>+ the reels behind it"]
    M --> N
    K --> B
    N --> B
    L --> B
```

**Saving.** You share a Reel from Instagram's native share sheet to your Telegram bot — one tap, no app switching. The bot extracts the caption and the creator's handle, files it into a collection (and sub-collection, when one fits), sends it to an LLM for open-vocabulary topic tags, generates an embedding locally on your CPU, and stores one row. Share the same link twice and it tells you it's already saved instead of duplicating it.

**The confirmation is the reel's picture.** Instagram's thumbnail URLs are signed and expire, so storing one would mean a reel saved today shows a broken image in a few months. Instead the "Saved!" reply *is* the thumbnail: Telegram fetches the image server-side and hands back a `file_id` that never expires, which is what gets stored. Every later reply can then show the picture for free. Nothing to configure — it falls back to a plain text reply if the image can't be sent.

**Two layers of organization.** *Collections* are the browsing structure — exactly one per reel, optionally with a sub-collection (`AI › Interview Prep`). Before filing, the LLM is shown the collections that already exist and told to reuse one unless nothing fits, so the taxonomy stays tight instead of sprawling into `AI` / `Artificial Intelligence` / `AI Stuff`. *Tags* are the search surface — many per reel, freeform. They do different jobs, so the vault keeps both.

**When the LLM isn't confident, it asks instead of guessing.** Some captions genuinely carry no topic (`"5 years ago this wasn't a thing"`) — the video's content may be entirely visual. Rather than silently filing those under an unrelated existing collection or a meaningless catch-all, the save pauses: the bot lists your existing collections and asks you to pick one (or name a new one, or reply `skip` to leave it Uncategorized). Nothing already computed — caption, tags, embedding, author — gets redone once you answer.

**Asking.** You type a question into the same chat and — this is the interesting part — the LLM decides *what kind* of question you asked, in one classification call. Looking for one specific reel? You get it, with its picture. Want to browse everything on a topic? You get the list, with pictures to recognize them by. Want something pulled together across a topic? You get a synthesized answer built only from the captions that actually matched, plus the reels it was built from, so you can go watch them. Asking for one creator's reels (`show me @gymshark's reels`) skips semantic search entirely and filters by author — "everything from X" is an identity question, not a similarity one. You never pick a mode; it works out which you meant.

**What the answers can and can't know.** Answers are told who posted each reel, so "which creator said what" works. They now also read what the video *said* and *showed*: after a save, the reel's video is downloaded in the background, its audio transcribed, and frames sampled at scene changes and read for on-screen text. That is what lifts the ceiling this vault used to have — 46% of a real vault's captions were comment-bait (`"comment HABITS for my list"`) whose actual content was spoken aloud and written down nowhere.

**Two more shapes of question.** Beyond finding one reel, browsing a list, filtering by creator, and synthesizing across many, the vault answers *comparisons* ("what's the best bicep workout" — it picks a winner and prints the measure it ranked by, because "best" is ambiguous and a hidden criterion can't be argued with) and *compilations* ("give me every interview question across my reels" — a real deduplicated list, not a paragraph about one).

---

## Status

**Built and working end-to-end against real services**, with 187 tests passing and a clean `mypy` run.

| # | Capability | Status |
|---|---|---|
| 01 | Core save flow — intake → extract → tag → embed → store → confirm, with duplicate detection | ✅ Done |
| 02 | Extraction fallback — scraper backup, then manual-paste recovery | ✅ Done |
| 03 | Single-item retrieval — semantic search returning one reel's link and tags | ✅ Done |
| 04 | Aggregate queries — LLM-synthesized answers across a matched set | ✅ Done |

Since then, a second slice ([`.scratch/reel-vault-query-answering/`](.scratch/reel-vault-query-answering/)) widened what `ask()` understands:

| # | Capability | Status |
|---|---|---|
| 01 | Four-way query classification, browse/list answers, per-intent match caps | ✅ Done |
| 02 | Author-filter queries — "show me @creator's reels", no embedding involved | ✅ Done |
| 03 | Author-aware synthesis, and aggregate replies that name the reels behind them | ✅ Done |
| 04 | Automatic thumbnail capture — the save confirmation itself mints a non-expiring Telegram `file_id` | ✅ Done |
| 05 | Thumbnails rendered in single, list, and aggregate replies | ✅ Done |

A third slice ([`.scratch/reel-vault-media-pipeline/`](.scratch/reel-vault-media-pipeline/)) gave the vault access to the video itself:

| # | Capability | Status |
|---|---|---|
| 01 | Media columns, condensing, and re-embedding a reel around what its video said | ✅ Done |
| 02 | Real video download, with the file guaranteed deleted afterwards | ✅ Done |
| 03 | Audio transcription | ✅ Done |
| 04 | Scene-detected frame sampling and on-screen text reading | ✅ Done |
| 05 | Background processing after save, resumed after a restart | ✅ Done |
| 06 | Compare/rank and extract/compile query kinds | ✅ Done |

**Deliberately not built yet:** LinkedIn, TikTok and YouTube Shorts sources, multi-user accounts, a web UI, and cloud hosting. The architecture is built so these are *additive* rather than rewrites — see [the roadmap](#where-this-is-going).

---

## Architecture

The whole system is organized around one idea: **a core that knows nothing about the outside world.**

The vault is entered through two operations — `save_reel(url)` and `ask(query)`. A handful of others exist for work that arrives *after* a save and cannot be part of it: `attach_thumbnail` (only the transport can mint a durable picture reference), `process_media`/`attach_media`/`resume_pending_media` (reading a reel's video takes minutes, so it happens off the save path), and `refile`/`undo_last_move` (the user overruling where a reel was filed). Each is a follow-up to a save, never a second way in.

What does not vary: everything environment-dependent (Telegram, Instagram, the LLM, the embedding model, the transcriber, the vision model, the database) is injected as an adapter behind a `Protocol`. The vault never imports Telegram, psycopg, or any model provider.

**No provider is named outside the adapters.** Every model this app talks to — chat, speech-to-text, vision — is reached over the OpenAI-compatible HTTP shape that Groq, OpenAI, DeepSeek, Qwen, Together, Moonshot, Mistral and Google's compatibility endpoint all speak. So which provider is in use is a base URL, a key and a model name in `.env`, not a code path: moving off today's provider is a config edit, not a new adapter. The defaults point at Groq's free tier because that is what this runs on today, not because anything depends on it.

```
src/reel_vault/
├── vault.py        ← the seam: save_reel() and ask(). Pure logic.
├── models.py       ← SavedReel, and the result types the bot renders
├── ports.py        ← Protocols the vault depends on
├── search.py       ← what a reel is indexed as, and what a query contributes
├── media.py        ← which frames of a video are worth reading. Pure logic.
├── urls.py         ← URL normalization (the dedup key)
├── bot.py          ← Telegram wrapper. Thin — only relays results.
├── config.py       ← env loading
├── main.py         ← wires real adapters into the vault, starts polling
└── adapters/
    ├── caption.py         ← oEmbed → yt-dlp fallback chain
    ├── llm.py             ← tagging, intent, summarize/compare/extract, condensing
    ├── media.py           ← download → transcribe → sample frames → read → delete
    ├── transcribe.py      ← speech-to-text
    ├── vision.py          ← reading sampled frames
    ├── embedder.py        ← local sentence-transformers, CPU only
    └── postgres_store.py  ← Postgres/pgvector persistence
```

This buys two concrete things:

**Tests run in milliseconds with no network.** The seam is exercised with fake adapters — a canned caption fetcher, a deterministic tagger, a bag-of-words embedder, an in-memory store. No test spins up a bot, calls a model provider, or touches a database.

**New sources are new adapters, not surgery.** Adding LinkedIn means writing a caption fetcher. Transcription and frame reading arrived the same way — as `MediaExtractor` and `ContentCondenser` adapters behind the existing seam. Neither touched `save_reel`'s contract.

### The stack

| Concern | Choice | Why |
|---|---|---|
| Intake | Telegram bot, long-polling | Native share-sheet target; no webhook or public endpoint needed |
| Caption extraction | Instagram oEmbed → `yt-dlp` fallback | Caption text only, so a save stays fast |
| Transcription | Any OpenAI-compatible `/audio/transcriptions` (default: Groq Whisper, free tier) | The mp4 goes straight up — no ffmpeg between a save and its transcript |
| Frame reading | Scene detection (PySceneDetect + OpenCV) → any vision-capable chat model (default: Gemini Flash) | Cuts are where the picture actually changes; a fixed timer misses a card that flashes by |
| Video files | Downloaded to a temp dir, deleted after reading | Disk never grows with the vault — the "no stored media" rule holds |
| Tagging & synthesis | Any OpenAI-compatible `/chat/completions` (default: Groq free tier, `openai/gpt-oss-20b`) | Swappable by config; open-weight default, no per-reel cost |
| Embeddings | `all-MiniLM-L6-v2` via `sentence-transformers` | 384-dim, runs locally on CPU, zero API calls |
| Storage | Postgres + `pgvector` | One row per reel; cosine similarity search in the database |
| Hosting | Your machine | If the bot is offline, Telegram queues the message for next run |

---

## Getting started

### Prerequisites

- **Python 3.12+** and [`uv`](https://docs.astral.sh/uv/)
- **Docker** (for the Postgres + pgvector container)
- A **Telegram bot token** — message [@BotFather](https://t.me/botfather), send `/newbot`
- An **API key for any OpenAI-compatible model provider** — free at [console.groq.com](https://console.groq.com), which is the default

### 1. Start the database

```bash
docker run -d \
  --name reel-vault-db \
  -e POSTGRES_PASSWORD=reelvault \
  -e POSTGRES_DB=reel_vault \
  -p 5434:5432 \
  -v reel-vault-pgdata:/var/lib/postgresql \
  pgvector/pgvector:pg18
```

> **Note:** Postgres 18 images mount at `/var/lib/postgresql`, *not* `/var/lib/postgresql/data` as in earlier versions. The container exits at startup if you use the old path.

The app creates the `vector` extension and the `saved_reels` table itself on first run.

### 2. Configure

```bash
cp .env.example .env
```

Fill in the required values. Only `LLM_API_KEY` picks a provider — base URL and model default to Groq's free tier, and every provider setting is overridable:

```ini
TELEGRAM_BOT_TOKEN=your-token-from-botfather
DATABASE_URL=postgresql://postgres:reelvault@localhost:5434/reel_vault
LLM_API_KEY=your-key
VISION_API_KEY=your-vision-key
```

`VISION_API_KEY` is optional. Without it reels are still downloaded and transcribed; only the reading of on-screen text is off, and the bot says so at startup rather than refusing to run.

To run on a different provider, add its endpoint — no code changes:

```ini
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
```

`TRANSCRIPTION_*` defaults to the same provider and key as `LLM_*`, since one provider commonly serves both; override it when yours doesn't. See `.env.example` for every knob.

`.env` is gitignored — your credentials stay local.

### 3. Run

```bash
uv run reel-vault
```

First run downloads the embedding model (~90 MB) and caches it. When you see `Application started`, the bot is live.

> There's no root-level `main.py` to run directly. `reel-vault` is a console script defined in `pyproject.toml` that calls `main()` in `src/reel_vault/main.py` — running through it ensures package imports resolve correctly.

### 4. Use it

Open your bot in Telegram and:

- **Share or paste an Instagram Reel link** → replies with the tags it generated
- **Share the same link again** → tells you it's already saved
- **Ask a question** → *"find that reel about transformer architecture"*
- **Ask across a topic** → *"give me all the interview questions from my AI reels"*

If a caption can't be extracted, the bot asks you to paste it manually — and that pasted text flows through the exact same tagging, embedding, and storage path.

---

## Testing

```bash
uv run pytest          # full suite
uv run mypy src tests  # type check
```

The default run is **hermetic** — no network, no database, no API keys required.

Integration tests for the Postgres adapter skip automatically unless a reachable instance is configured via `TEST_DATABASE_URL` or `DATABASE_URL`. They exist because the seam tests use an in-memory fake store, which by design can't catch SQL or type-adaptation bugs — a gap that let a real one through on the first live run. They clean up their own rows and won't touch your saved reels.

---

## Operational notes

Two things that will bite eventually, documented so they don't cost you an afternoon twice:

**Instagram's oEmbed endpoint always fails.** Meta deprecated the public `api.instagram.com/oembed` endpoint — it returns a 500 without an app access token. The `yt-dlp` fallback does all the real work. The oEmbed attempt costs about a second per save and is kept only because the spec calls for oEmbed-first; it's safe to remove.

**Free-tier model lineups shift.** The originally-specified Llama chat models were retired from Groq's free tier mid-project. If tagging starts returning 404s, set `LLM_MODEL` in `.env` to something currently served — no code change, and the same lever moves you to a different provider entirely.

**Tuning retrieval.** `vault.py` exposes `DEFAULT_MATCH_THRESHOLD` (0.35) and one cap per question type: `DEFAULT_TOP_K_SINGLE` (5), `DEFAULT_TOP_K_LIST` (50), `DEFAULT_TOP_K_AGGREGATE` (15). They differ on purpose — a list costs only a database read, while every reel in an aggregate becomes part of a single LLM prompt, so the free-tier budget is what bounds it. Raise the threshold if unrelated reels surface; lower it if good matches are being rejected as `NoMatch`.

**After a reboot,** bring the database back with `docker start reel-vault-db`.

---

## Where this is going

The vault now reads what a reel says and shows, not only what its caption wrote. What remains narrow: Instagram only, Telegram only, one user. The seam design exists so each of the following is an added adapter rather than a rewrite.

**More sources.** LinkedIn posts and blog links become additional caption fetchers. `save_reel` doesn't change — it never knew what Instagram was.

**More platforms.** TikTok, YouTube Shorts and LinkedIn, deliberately sequenced *after* the media pipeline rather than alongside it: what is platform-specific is only URL parsing and extraction, and every bug in the shared core would otherwise be inherited by each new platform the moment it was added.

**A real UI.** Telegram is a great intake channel and a mediocre browsing one. A web interface over the same vault would add topic browsing, a tag cloud, filtering by date, and reading a synthesized answer alongside the reels it came from.

**Beyond one user.** Accounts and per-user isolation, once the concept has earned it.

**Always-on.** Cloud hosting so saves are processed instantly rather than whenever the bot next runs — though Telegram's message queueing makes this less urgent than it sounds.

The end state is a personal knowledge base that happens to be fed by social media: everything you've ever saved, organized without effort, and answerable in plain language.

---

## License

Personal project — no license specified.
