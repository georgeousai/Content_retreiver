# 03 — `conversation.py`: wire the five-step resolution order, add `LastTurn`

**What to build:** A new module, `conversation.py`, holding the pure
decision logic `_on_message` currently mixes with Telegram I/O: given a
`chat_id`, the inbound text, whatever `reply_to` text it carries (already
extracted by `_replied_to_reel_url`), and the persisted `ChatState`/
`LastTurn` for that chat, decide what to do — a small `Action` result type
the bot layer then renders. No `telegram.Message`/`Update` object crosses
into this module; that is the entire point of splitting it out (testability
against this repo's existing fake-based convention, not a bet on a second
transport — see the spec's Out of Scope).

Implements the five-step resolution order from the spec:

1. URL in the message → save (existing logic, relocated, not changed).
2. Open `ChatState` (ticket 01) → existing answer-the-prompt logic,
   relocated.
3. `/cancel` (ticket 01) or another recognized command → run it.
4. Reply to a card → existing refile logic, relocated.
5. Otherwise: call `vault.classify(query)` (ticket 02) once. `NEITHER` →
   "I don't understand," nothing else called. `MODIFIER` with no
   `LastTurn` on record → same as `NEITHER`. `MODIFIER` with a `LastTurn`
   → hand off to ticket 04/05's resolution. `NEW` → `vault.ask_classified`
   (ticket 02), then write the resulting `LastTurn`.

Also introduces `LastTurn{query, answer, reels}`, persisted per-chat
alongside `ChatState` (same store, not a third table), written after every
call that produces an `Answer` this conversation could later be asked to
continue, and read only by step 5's `MODIFIER` handling.

**Blocked by:** 01 (`ChatState`, `/cancel`), 02 (`classify`/
`ask_classified`, `continuation`).

- [ ] `_on_message`'s five checks (URL, open state, command, card reply,
      fallback) now run through `conversation.py`'s decision function in
      that exact order; `bot.py` renders whatever `Action` comes back and
      contains no routing logic of its own beyond calling it.
- [ ] A message that is simultaneously a URL and a reply to a card behaves
      exactly as it does today (regression: step order is preserved, not
      just each step individually).
- [ ] `NEITHER`-classified text produces "I don't understand" and calls
      neither `vault.ask_classified` nor anything from ticket 05 —
      including fault #1's exact live text as a named regression case.
- [ ] `MODIFIER`-classified text with no `LastTurn` for that chat also
      produces "I don't understand" (or an equivalent "nothing to modify
      yet" message) rather than erroring or falling through to a fresh
      search.
- [ ] `NEW`-classified text produces the same `Answer` `vault.ask` would
      have for that query, via `ask_classified`, and writes a `LastTurn`
      afterward.
- [ ] `LastTurn` persists and survives a restart the same way `ChatState`
      does (ticket 01's persistence mechanism, reused).
- [ ] `conversation.py`'s decision function is tested with zero Telegram
      objects — plain values in, an `Action` value out — per the fake-based
      convention already used for `vault.py`.
