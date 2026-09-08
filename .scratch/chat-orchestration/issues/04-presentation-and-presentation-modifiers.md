# 04 — `Presentation` (explicit → sticky → default) and presentation-only modifiers

**What to build:** `Presentation{include_text: bool, include_sources: bool,
max_cards: int | None}`, resolved in the bot layer only — `Answer` and
`Vault` stay exactly as presentation-agnostic as they are today, nothing in
`models.py` changes. Resolution order: an explicit instruction in the
current message wins; failing that, a sticky per-chat preference
(persisted alongside `ChatState`/`LastTurn`, set the last time the user
stated one explicitly); failing that, a default keyed by `Answer` type
(`AggregateAnswer` today: text + cards, unchanged from current behavior;
`ListAnswer`/`SingleItemAnswer`: cards, no separate text, unchanged).

This is what fixes fault #4 (presentation welded to answer kind) and gives
fault #1's own motivating request ("I want you to summarize them for me,"
i.e. text without being shown the reels again) an actual way to be said.

Wires the presentation-only half of `MODIFIER` handling from ticket 03: a
message classified `MODIFIER` that changes only how the last answer is
shown ("just the text," "no cards," "show me the reels only") re-renders
the stored `LastTurn.answer` under a newly resolved `Presentation` —
zero additional LLM or vault calls. Distinguishing a presentation-only
modifier from a content modifier (ticket 05) is part of this ticket's
classification handling, not a new model call: it reads off which
`Presentation` fields the message's own text implies changing versus
whether it's asking for different content.

**Blocked by:** 03 (`conversation.py`'s resolution order and `LastTurn`).

- [ ] `Presentation` resolves explicit → sticky → default, each level
      tested independently (an explicit instruction beats a stale sticky
      preference; a sticky preference beats the per-kind default; no
      instruction and no sticky preference falls to the default).
- [ ] A sticky preference persists per chat and survives a restart, the
      same way `ChatState`/`LastTurn` do.
- [ ] `AggregateAnswer`'s default presentation (text + cards) matches
      today's unconditional behavior exactly — regression coverage.
- [ ] "just the text" (or equivalent) against an existing `LastTurn`
      re-renders `LastTurn.answer` with cards suppressed, calling neither
      `vault.ask_classified` nor `vault.refine` (ticket 05).
- [ ] "just the text" with no `LastTurn` on record is treated as
      `MODIFIER`-with-nothing-to-modify per ticket 03 (not a crash, not a
      fresh search).
- [ ] A presentation-only modifier updates the sticky preference for that
      chat, so a later answer of the same kind uses it without having to
      be asked again in the same message.
