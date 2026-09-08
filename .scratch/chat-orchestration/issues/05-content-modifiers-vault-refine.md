# 05 — Content modifiers via `Vault.refine`

**What to build:** `Vault.refine(instruction: str, reels: list[SavedReel]) ->
Answer`, for the `MODIFIER` subcase that needs genuinely new text but from
the *same* reel set the last turn already matched — "shorter," "focus on
the pricing part," a pronoun follow-up resolved against what was just
discussed. Re-running `vault.ask`/`ask_classified` here would re-search the
vault from scratch and could plausibly return a different set of reels for
a differently-phrased instruction; `refine` reuses `LastTurn.reels`
directly, the same way `_written_answer` already builds `SummarySource`
entries from a given reel list rather than re-deriving it.

Reuses the existing `_written_answer`/`SummarySource` machinery (the same
three writer adapters — summarizer, comparer, item extractor — already
used by `AGGREGATE`/`COMPARE_RANK`/`EXTRACT_COMPILE`) against the given
`reels`, under a system prompt scoped to "revise the previous answer per
this instruction," not "answer this question from scratch." This is the
one place in this rewrite that adds a second LLM call for a single user
message — the classification call from ticket 02, plus this one — and only
for this subcase; presentation-only modifiers (ticket 04) add none.

**Blocked by:** 03 (`conversation.py`'s resolution order and `LastTurn`).
Not blocked by 04, but the two tickets together are what fully resolve
`MODIFIER` — a build that ships 05 without 04 (or vice versa) is
incomplete but each is independently testable.

- [ ] `Vault.refine(instruction, reels)` returns an `Answer` built from
      exactly the given `reels`, with no new retrieval/search call against
      the store.
- [ ] A content modifier ("shorter") against a `LastTurn` calls
      `vault.refine` with that turn's `reels`, not `vault.ask_classified` —
      asserted on what the fake was called with (the same justified
      exception to "don't assert call sequencing" already used for
      author-threading in the query-answering spec).
- [ ] `refine`'s output answer type matches what makes sense for the kind
      of answer being revised — refining an `AggregateAnswer` yields
      another `AggregateAnswer`, not a different `Answer` variant.
- [ ] `refine` writes a new `LastTurn` afterward (a refined answer can
      itself be further modified), reusing the same `reels`.
- [ ] The new "revise per instruction" prompt is measured against a
      handful of realistic instructions on real matched content ("shorter,"
      "focus on X"), not only asserted against a fake, per this repo's
      existing live-model-measurement convention.
- [ ] A content-modifier instruction that names something not actually
      present in any of `reels` does not fabricate it — same "report only
      what the sources say" discipline already enforced in
      `SUMMARY_SYSTEM_PROMPT`/`COMPARE_SYSTEM_PROMPT`, carried into this new
      prompt rather than assumed to transfer automatically.
