# 02 — Author-filter queries

**What to build:** Let the user ask for everything saved from one specific creator (e.g. "show me @gymshark's reels") and get that list back directly, without it being treated as a semantic topic search.

`ReelStore` gains `find_by_author(name: str) -> list[SavedReel]`, a plain filter (no embedding involved). `ask()`'s classification (from ticket 01) recognizes this phrasing as `AUTHOR_FILTER`, extracts the author name/handle from the query text as part of the same classification call, and routes straight to `find_by_author` — skipping embedding search entirely. The result is returned as a `ListAnswer`.

**Blocked by:** 01 — needs the `classify()`/`ListAnswer` plumbing it establishes.

- [ ] `ReelStore.find_by_author(name)` returns all reels whose stored author matches, independent of caption content or embedding similarity.
- [ ] A query like "show me @creator's reels" classifies as `AUTHOR_FILTER` and the extracted author name is passed to `find_by_author`.
- [ ] An `AUTHOR_FILTER` query does not call the embedder or the store's `search`/similarity path at all.
- [ ] The result is returned as a `ListAnswer` and rendered by the bot the same way as a topic-based `LIST` answer.
- [ ] A query for an author with no saved reels returns an appropriately empty result (not an error, not `NoMatch` conflated with "no semantic match" if that type doesn't fit — use whatever `Answer` shape correctly represents "author matched, zero reels").
</content>
