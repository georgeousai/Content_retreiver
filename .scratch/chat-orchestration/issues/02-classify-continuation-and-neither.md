# 02 — Split `Vault.classify`/`ask_classified`, add `continuation`, make "I don't understand" reachable

**What to build:** `Vault.ask`'s internal classification step —
`self._query_intent.classify(query, known)`, currently private to `ask` —
becomes a public `Vault.classify(query) -> QueryClassification`. A second
method, `Vault.ask_classified(query, classification) -> Answer`, does what
the body of today's `ask` does, given a classification that was already
computed. `ask` itself becomes
`self.ask_classified(query, self.classify(query))` — behaviorally identical
to today, same one LLM call, existing `test_ask.py` coverage unchanged.

`QueryClassification` gains one field: `continuation: Continuation = NEW`
(a new `Enum`, `NEW | MODIFIER | NEITHER`), decided by the same
classification call from the message text alone — no last-turn context is
given to or needed by the model; whether a last turn actually exists to
continue is a separate, deterministic check made by the caller (ticket 03),
not this one. This keeps `Vault.classify`/`ask_classified` exactly as
stateless as `ask` is documented to be elsewhere in this repo.

`NEITHER` is what fixes fault #1: a message with no topic in it
("I don't want to watch the reels. I want you to summarize them for me")
should classify as `NEITHER` rather than falling into `Vault.ask_classified`
and being embedded as a search query. This ticket does not wire `NEITHER`
into the bot's reply — that's the resolution-order ticket (03) — but it
must be a real, reachable classification outcome, and the exact live
failure text from fault #1 is required test evidence, not optional.

**Blocked by:** None — independent of ticket 01, both feed ticket 03.

- [ ] `Vault.classify(query)` is public and returns the same
      `QueryClassification` `ask` already computed internally; no change to
      `kind`/`author`/`collection` behavior.
- [ ] `Vault.ask_classified(query, classification)` produces the same
      `Answer` `ask` would for that query today, given `ask`'s own
      classification of it — full regression pass of the existing
      `test_ask.py` suite against the split entrypoints.
- [ ] `Vault.ask(query)` is now `ask_classified(query, classify(query))` and
      makes exactly one classification call, as it does today (no added
      latency — assert call count on the fake `QueryIntent` in at least one
      test).
- [ ] `continuation` classifies as `NEW` for ordinary fresh questions
      (regression: every existing `test_ask.py`/`test_collection_queries.py`
      /`test_author_queries.py`/`test_compare_and_extract.py` query
      continues to classify `NEW`).
- [ ] `continuation` classifies as `NEITHER` for fault #1's exact live text
      ("I don't want to watch the reels. I want you to summarize them for
      me"), run against the real configured model, not just a fake —
      following this repo's existing live-model-measurement convention for
      prompt changes (`known-issues.md`'s summarizer/condenser entries).
- [ ] `continuation` classifies as `MODIFIER` for a small set of realistic
      follow-up phrasings ("just the text," "shorter," "no cards," a bare
      pronoun follow-up), measured against the real model the same way.
- [ ] The `INTENT_SYSTEM_PROMPT` extension ships with a concrete
      counter-example for at least the `NEITHER` case, not only an abstract
      instruction — this repo's own prompt-engineering history
      (`known-issues.md`) shows abstract additions to a working prompt
      degrade without one.
