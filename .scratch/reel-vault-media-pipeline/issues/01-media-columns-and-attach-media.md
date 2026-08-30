# 01 — Media columns, condensing, and attaching media to a saved reel

**What to build:** A saved reel can carry what its video said and showed, and
becomes findable by it. The vault gains a way to be handed a reel's raw
transcript and raw frame analysis, condense each into a compact summary, store
both halves against the reel, and re-embed the reel so search reaches the new
content. Every reel also carries a processing status, so the vault can say
which reels are still waiting on their video to be processed.

Nothing downloads a video yet — this ticket is exercised end-to-end with a
handed-in extraction, exactly as the thumbnail work was verifiable at the
vault level before any reply rendered a picture.

The condenser is a swappable adapter like every other LLM-backed step: the
vault never names its provider. Raw text is stored but never embedded or
searched; only the condensed summary is, which is the entire point of keeping
both.

Reels that predate this feature are not queued for processing — backfill is a
deliberate follow-up, not part of this.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] A saved reel carries raw transcript, transcript summary, raw frame
      analysis, frame-analysis summary, and a processing status.
- [ ] Handing the vault a successful extraction for a saved reel stores all
      four text fields and marks the reel processed.
- [ ] The summaries are produced by a condenser adapter; the raw text is
      stored exactly as handed in, never condensed away.
- [ ] After media is attached, the reel is re-embedded so a query matching
      only transcript or frame content retrieves it.
- [ ] Raw text is never passed to the embedder — only the summaries reach it.
- [ ] Handing the vault a failed extraction marks the reel failed and leaves
      its caption, tags, collection, and existing embedding untouched.
- [ ] The vault can list the reels still awaiting processing.
- [ ] Moving a reel between collections (and undoing that move) preserves its
      media summaries in the re-embedded text, rather than dropping them.
- [ ] Existing reels in a live vault are not marked as awaiting processing by
      the schema migration.
