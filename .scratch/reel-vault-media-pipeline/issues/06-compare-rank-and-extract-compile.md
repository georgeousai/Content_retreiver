# 06 — Answer "which is best" and "give me the whole list"

**What to build:** Two kinds of question the vault currently cannot answer.

**Compare/rank** — "what's the best bicep workout across my reels." The answer
picks a winner and says what it ranked by, because "best" is usually ambiguous
and an answer that hides its criterion cannot be argued with. The bot does not
ask a clarifying question back: `ask` stays a single stateless call, and the
answer states the interpretation it used so a wrong guess is obvious and
re-askable.

**Extract/compile** — "give me the full list of AI interview questions across
my reels." The answer is a real, deduplicated list of the things asked for, not
a paragraph describing them.

Both are classified up front as their own kinds rather than inferred inside the
existing synthesize path. That is deliberate: a broadly-scoped prompt left to
work out its own answer shape is exactly what produced the summarizer
hallucination already on record, and each of these has a narrow enough job to
be told precisely what it is.

Neither is gated — every user gets both.

**Blocked by:** None — can start immediately. Works over whatever content a
reel already carries, so it does not wait on the media pipeline.

**Status:** ready-for-agent

- [ ] A comparison/ranking question is classified as its own kind and answered
      with a ranked answer that names the criterion it ranked by.
- [ ] An extraction/compilation question is classified as its own kind and
      answered with a list of items, deduplicated across reels.
- [ ] Both answers carry the reels they were built from, so the user can go
      and watch the sources.
- [ ] Both draw on transcript and frame content where a reel has it, not only
      its caption.
- [ ] Neither answer type is produced by the existing synthesize path, and the
      existing four query kinds behave exactly as before.
- [ ] A question of either kind that matches nothing says so, rather than
      ranking or extracting from an empty set.
