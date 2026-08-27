# 01 — Core save flow (intake → extract → tag → embed → store → confirm)

**What to build:** A working Telegram bot (long-polling) that, given a shared Instagram Reel link, fetches the caption via Instagram's oEmbed endpoint (happy path only — no scraper fallback yet), generates topic tags via the Groq LLM, generates a local embedding for the caption, stores the reel in Postgres/pgvector, and replies in chat with the saved tags. Also handles the duplicate case: sharing a URL that's already saved replies with the existing entry's tags instead of creating a new row. This ticket establishes the `save_reel` core-seam entrypoint, the Postgres/pgvector schema, and the Telegram bot skeleton that later tickets build on.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] Sharing an Instagram Reel link to the bot results in a stored `SavedReel` (normalized URL, caption, tags, embedding, timestamp) in Postgres/pgvector.
- [ ] The bot replies in the Telegram chat with the generated tags after a successful save.
- [ ] Tags are generated via the Groq API from the extracted caption; a reel can receive more than one tag.
- [ ] The embedding is generated locally (no external API call) from the caption text.
- [ ] Sharing a URL that is already saved (by normalized URL) does not create a duplicate row — the bot replies with the existing entry's tags instead.
- [ ] The bot runs via Telegram long-polling as a local process (no webhook/public endpoint required).
- [ ] `save_reel` is implemented as a seam function taking the URL and returning a `SavedReel` (or duplicate) result, with the Instagram-fetch, tagging, embedding, and storage adapters injected — not hardwired — so later tickets can swap/extend them.
