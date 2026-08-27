# 03 — Author-aware aggregate answers + bot surfaces aggregate links

**What to build:** Let synthesized (aggregate) answers attribute or group content by creator when the caption text itself supports it (e.g. "summarize the AI interview-question reels and tell me which creator said what"), and fix the existing bot-layer bug where aggregate replies drop the matched reel links even though the vault already computes them.

`Summarizer.summarize` changes signature from `(query, captions: list[str])` to `(query, entries)`, where each entry pairs a caption with its `author_handle`/`author_name`, so the LLM can reference who said what in its synthesized text. This only works when the real content is present in the caption itself — it cannot recover content that exists only in a reel's audio/video (that gap is tracked separately, out of scope here). Separately, the bot's `_handle_query` currently only sends `AggregateAnswer.text`, silently dropping `AggregateAnswer.reels` — this ticket fixes that so aggregate replies include the matched reels' links alongside the synthesized text.

**Blocked by:** 01 — `AGGREGATE` routing moves into the new `classify()`-based path established there.

- [ ] `Summarizer.summarize` receives each matched reel's author info alongside its caption.
- [ ] A query like "summarize X and group by creator," where the matched captions actually contain attributable content, produces an answer that references the correct creator(s).
- [ ] A query about content that only exists in a reel's video/audio (not its caption) does not fabricate an attribution — the answer simply doesn't contain information that was never in the caption.
- [ ] Aggregate bot replies include the matched reels' links (not just the synthesized `text`).
- [ ] Existing aggregate-answer tests (matched-captions-only synthesis, non-matching content excluded) continue to pass.
</content>
