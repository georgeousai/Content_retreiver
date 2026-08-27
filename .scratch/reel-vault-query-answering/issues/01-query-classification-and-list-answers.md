# 01 — Query classification + browse/list answers

**What to build:** Replace `ask()`'s binary single-vs-aggregate check with a four-way understanding of what the user wants, and make "show me all my X reels"-style questions return the actual list of matches instead of a synthesized paragraph or a silently-truncated top-5.

Specifically: the `QueryIntent` port changes from `is_aggregate(query) -> bool` to a single `classify(query)` call returning one of `SINGLE` / `LIST` / `AGGREGATE` / `AUTHOR_FILTER` (the `AUTHOR_FILTER` branch itself is built in ticket 02 — this ticket only needs the classification shape to include it so 02 doesn't have to re-touch the port). A new `ListAnswer` answer type is added (matched reels, no LLM summarization call) rather than reusing `AggregateAnswer` with an empty `text`. Match limits (`top_k`) become intent-dependent instead of one shared constant: `SINGLE` keeps today's default (~5, top match used), `LIST` uses a generous cap (50), `AGGREGATE` uses a moderate cap (15, to keep the summarizer's Groq prompt bounded). The bot renders `ListAnswer` replies as a list of reel links/tags.

**Blocked by:** None — can start immediately.

- [x] `QueryIntent.classify(query)` returns `SINGLE`, `LIST`, or `AGGREGATE` for the corresponding phrasing (`AUTHOR_FILTER` case is exercised in ticket 02, but the type/shape exists here).
- [x] A `LIST`-classified query returns a new `ListAnswer{query, reels}` containing the matched reels, with no call made to the summarizer.
- [x] `LIST` queries return up to their own (generous) cap, not silently truncated to the old shared `top_k=5`.
- [x] `AGGREGATE` queries are capped at their own (moderate) limit, independent of `LIST`'s cap.
- [x] Existing `SINGLE`-query behavior is unchanged (existing `test_ask.py` single-item and no-match tests continue to pass against the new `classify()`-based routing).
- [x] The bot formats a `ListAnswer` reply as the list of matched reels' links/tags (not synthesized text).
</content>
