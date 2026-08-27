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
    D2 --> E["🏷️ Tagging<br/>(Groq LLM)"]
    E --> F["🧮 Embedding<br/>(local, CPU)"]
    F --> G[("🗄️ Postgres<br/>+ pgvector")]
    G --> B

    B --> H{"ask(query)"}
    H --> I["Semantic<br/>search"]
    I --> G
    I --> J{"Single item<br/>or aggregate?"}
    J -->|single| K["🔗 Link + tags"]
    J -->|aggregate| L["📝 Synthesized<br/>answer"]
    K --> B
    L --> B
```

**Saving.** You share a Reel from Instagram's native share sheet to your Telegram bot — one tap, no app switching. The bot extracts the caption and the creator's handle, files it into a collection (and sub-collection, when one fits), sends it to an LLM for open-vocabulary topic tags, generates an embedding locally on your CPU, and stores one row. Share the same link twice and it tells you it's already saved instead of duplicating it.

**Two layers of organization.** *Collections* are the browsing structure — exactly one per reel, optionally with a sub-collection (`AI › Interview Prep`). Before filing, the LLM is shown the collections that already exist and told to reuse one unless nothing fits, so the taxonomy stays tight instead of sprawling into `AI` / `Artificial Intelligence` / `AI Stuff`. *Tags* are the search surface — many per reel, freeform. They do different jobs, so the vault keeps both.

**When the LLM isn't confident, it asks instead of guessing.** Some captions genuinely carry no topic (`"5 years ago this wasn't a thing"`) — the video's content may be entirely visual. Rather than silently filing those under an unrelated existing collection or a meaningless catch-all, the save pauses: the bot lists your existing collections and asks you to pick one (or name a new one, or reply `skip` to leave it Uncategorized). Nothing already computed — caption, tags, embedding, author — gets redone once you answer.

**Asking.** You type a question into the same chat. The query gets embedded, matched against your stored reels by cosine similarity, and then — this is the interesting part — the LLM decides *what kind* of question you asked. Looking for one specific reel? You get its link and tags. Asking to pull something together across a topic? You get a synthesized answer built only from the captions of the reels that actually matched. You never pick a mode; it just works out which you meant.

---

## Status

**v1 is built and working end-to-end against real services.** All four tickets from the spec are implemented, with 16 tests passing and a clean `mypy` run.

| # | Capability | Status |
|---|---|---|
| 01 | Core save flow — intake → extract → tag → embed → store → confirm, with duplicate detection | ✅ Done |
| 02 | Extraction fallback — scraper backup, then manual-paste recovery | ✅ Done |
| 03 | Single-item retrieval — semantic search returning one reel's link and tags | ✅ Done |
| 04 | Aggregate queries — LLM-synthesized answers across a matched set | ✅ Done |

**Deliberately not in v1:** LinkedIn and blog sources, audio transcription, on-screen text (OCR), video downloads, multi-user accounts, a web UI, and cloud hosting. The architecture is built so these are *additive* rather than rewrites — see [the roadmap](#where-this-is-going).

---

## Architecture

The whole system is organized around one idea: **a core that knows nothing about the outside world.**

The vault exposes exactly two operations — `save_reel(url)` and `ask(query)`. Everything environment-dependent (Telegram, Instagram, the LLM, the embedding model, the database) is injected as an adapter behind a `Protocol`. The vault never imports Telegram, Groq, or psycopg.

```
src/reel_vault/
├── vault.py        ← the seam: save_reel() and ask(). Pure logic.
├── models.py       ← SavedReel, and the result types the bot renders
├── ports.py        ← Protocols the vault depends on
├── urls.py         ← URL normalization (the dedup key)
├── bot.py          ← Telegram wrapper. Thin — only relays results.
├── config.py       ← env loading
├── main.py         ← wires real adapters into the vault, starts polling
└── adapters/
    ├── caption.py         ← oEmbed → yt-dlp fallback chain
    ├── groq_llm.py        ← tagging, intent classification, summarization
    ├── embedder.py        ← local sentence-transformers, CPU only
    └── postgres_store.py  ← Postgres/pgvector persistence
```

This buys two concrete things:

**Tests run in milliseconds with no network.** The seam is exercised with fake adapters — a canned caption fetcher, a deterministic tagger, a bag-of-words embedder, an in-memory store. No test spins up a bot, calls Groq, or touches a database.

**New sources are new adapters, not surgery.** Adding LinkedIn means writing a caption fetcher. Adding audio transcription means extending the extraction chain. Neither touches `save_reel`'s contract.

### The stack

| Concern | Choice | Why |
|---|---|---|
| Intake | Telegram bot, long-polling | Native share-sheet target; no webhook or public endpoint needed |
| Caption extraction | Instagram oEmbed → `yt-dlp` fallback | Caption text only — no video or audio is ever downloaded |
| Tagging & synthesis | Groq free tier (`openai/gpt-oss-20b`) | Open-weight model, no per-reel cost |
| Embeddings | `all-MiniLM-L6-v2` via `sentence-transformers` | 384-dim, runs locally on CPU, zero API calls |
| Storage | Postgres + `pgvector` | One row per reel; cosine similarity search in the database |
| Hosting | Your machine | If the bot is offline, Telegram queues the message for next run |

---

## Getting started

### Prerequisites

- **Python 3.12+** and [`uv`](https://docs.astral.sh/uv/)
- **Docker** (for the Postgres + pgvector container)
- A **Telegram bot token** — message [@BotFather](https://t.me/botfather), send `/newbot`
- A **Groq API key** — free at [console.groq.com](https://console.groq.com)

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

Fill in all three values:

```ini
TELEGRAM_BOT_TOKEN=your-token-from-botfather
GROQ_API_KEY=your-groq-key
DATABASE_URL=postgresql://postgres:reelvault@localhost:5434/reel_vault
```

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

**Groq's model lineup shifts.** The originally-specified Llama chat models have already been retired from the free tier. If tagging starts returning 404s, run `client.models.list()` to see what's currently available and update `DEFAULT_MODEL` in `adapters/groq_llm.py` — it's a single constant.

**Tuning retrieval.** `vault.py` exposes `DEFAULT_MATCH_THRESHOLD` (0.35) and `DEFAULT_TOP_K` (5). Raise the threshold if unrelated reels surface; lower it if good matches are being rejected as `NoMatch`.

**After a reboot,** bring the database back with `docker start reel-vault-db`.

---

## Where this is going

v1 proves the concept on a deliberately narrow slice: Instagram only, captions only, Telegram only, one user. The seam design exists so each of the following is an added adapter rather than a rewrite.

**More sources.** LinkedIn posts and blog links become additional caption fetchers. `save_reel` doesn't change — it never knew what Instagram was.

**Deeper extraction.** Plenty of reels carry their real content in the audio or in on-screen text, not the caption. Audio transcription (Whisper) and OCR slot into the extraction chain, feeding the same tagging and embedding path. This is the single biggest quality upgrade available — it would take the vault from *"what the creator wrote"* to *"what the reel actually says."*

**A real UI.** Telegram is a great intake channel and a mediocre browsing one. A web interface over the same vault would add topic browsing, a tag cloud, filtering by date, and reading a synthesized answer alongside the reels it came from.

**Beyond one user.** Accounts and per-user isolation, once the concept has earned it.

**Always-on.** Cloud hosting so saves are processed instantly rather than whenever the bot next runs — though Telegram's message queueing makes this less urgent than it sounds.

The end state is a personal knowledge base that happens to be fed by social media: everything you've ever saved, organized without effort, and answerable in plain language.

---

## License

Personal project — no license specified.
