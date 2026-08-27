# 04 — Aggregate/summarized query across a collection

**What to build:** Extend `ask(query)` to recognize when a request is asking for aggregated/summarized content across a topic (e.g. "give me all the interview questions from my AI reels") rather than a single item. For an aggregate-style query, the app retrieves the set of semantically matched reels, passes their captions to the Groq LLM to synthesize an answer, and the bot replies with that synthesized text instead of a single link.

**Blocked by:** 03 — extends the same `ask()` entrypoint and query-handling logic.

**Status:** ready-for-agent

- [ ] `ask` distinguishes an aggregate/summarization-style query from a single-item lookup query (e.g. via the LLM), without the user having to select a mode explicitly.
- [ ] For an aggregate query, the bot replies with a synthesized answer built only from the captions of the semantically matched reels — not unrelated ones.
- [ ] The single-item retrieval behavior from Ticket 03 continues to work unchanged for single-item-style queries.
- [ ] The aggregate answer is generated via the Groq API from the matched captions.
