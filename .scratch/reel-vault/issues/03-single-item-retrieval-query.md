# 03 — Single-item retrieval query

**What to build:** The `ask(query)` core-seam entrypoint: given a free-text request in the Telegram chat (e.g. "find that reel about transformer architecture"), the app embeds the query, performs semantic search over stored reels' embeddings, and the bot replies with the best-matching reel's original Instagram link and tags.

**Blocked by:** 01 — needs stored, embedded `SavedReel`s to search against.

**Status:** ready-for-agent

- [ ] Asking the bot a natural-language question that targets one specific reel returns that reel's original Instagram link and its tags.
- [ ] Matching is done via semantic similarity search over the caption embeddings, not keyword/substring matching.
- [ ] If no reel is a reasonable match, the bot replies indicating nothing matched rather than returning an unrelated reel.
- [ ] `ask` is implemented as a seam function taking a query string and returning a result the bot layer can render, with the embedding and retrieval adapters injected (consistent with `save_reel`'s adapter pattern from Ticket 01).
