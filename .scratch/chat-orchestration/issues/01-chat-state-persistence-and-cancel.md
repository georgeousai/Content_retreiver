# 01 — Unify pending state into `ChatState`, persist it, add `/cancel` and a timeout

**What to build:** Replace `_pending_manual_caption: dict[int, str]` and
`_pending_collection_choice: dict[int, NeedsCollectionChoice]` with one
discriminated union, `ChatState` (`AwaitingManualCaption` /
`AwaitingCollectionChoice`), keyed by `chat_id` and persisted — a new
`chat_state` table/store (`chat_id`, a JSON payload, `created_at`), read and
written the way `ReelStore` already reads and writes everything else. This
fixes fault #3 (a restart forgets every open question) directly: today
nothing about either pending dict survives a process restart.

Reading a `ChatState` back checks `created_at` against a fixed idle timeout
(propose 30 minutes; unmeasured, flag as tunable) and treats an expired
state as absent — cleared, not merely ignored, so the next read doesn't pay
the same check twice. This is a read-time check, not a background sweep: no
scheduler, no new task, nothing running when nobody is asking. This fixes
fault #2's timeout half.

Add the bot's first real command handling — currently there is none;
`_on_message` filters `~filters.COMMAND` and nothing else processes a `/`
message, so commands are silently dropped today. Add `/cancel`: clears any
open `ChatState` for the sending chat and replies confirming what was
cancelled, or that there was nothing to. This fixes fault #2's exit half.

**Blocked by:** None — can start immediately, independent of every other
ticket in this spec.

- [ ] `ChatState` is a discriminated union covering exactly the two states
      that exist today (manual caption pending, collection choice pending);
      no behavior change to either flow's actual content.
- [ ] `ChatState` is persisted (not held only on the `ReelVaultBot`
      instance) and correctly round-trips through a restart — a fresh
      `Vault`/store instance started against the same database still finds
      a state written by a previous run.
- [ ] Reading a `ChatState` older than the timeout returns "no state open"
      and clears the stale row; the message that triggered the read falls
      through to the next step in the resolution order rather than being
      consumed as an answer to the expired prompt.
- [ ] `/cancel` with an open state clears it and confirms what was
      cancelled; the next message from that chat is evaluated fresh (not
      treated as answering the just-cancelled prompt).
- [ ] `/cancel` with nothing open replies that there was nothing to cancel,
      and does not error.
- [ ] The existing manual-caption and collection-choice flows behave
      exactly as they do today in every case that isn't cancel/timeout —
      regression coverage against the current `tests/test_bot.py` /
      `tests/test_collections_and_author.py` cases exercising these paths.
