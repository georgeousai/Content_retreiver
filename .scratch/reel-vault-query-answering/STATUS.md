# Status as of 2026-08-29

Everything through commit `b883136` is merged to `master` via PR #1. This
file is a snapshot of what's still open — not a spec, not a bug log (that's
[`known-issues.md`](../known-issues.md), which covers problems already
fixed this session). Pick up here next time.

## The one architectural decision to make first

**There is no per-user separation.** Confirmed by reading the schema and
`bot.py`: `saved_reels` has no `user_id`/`chat_id` column, and `chat_id` in
the bot is used only for transient prompt state (pending manual caption,
pending collection choice) — never to scope what's saved or searched.
Every Telegram user who talks to this bot shares one global vault; anyone's
"show me my reels" returns everyone's reels.

This was fine as a personal tool. The stated plan is multi-user ("this will
be an app used by all"), and this blocks that outright. Worth deciding
deliberately — does a reel/collection belong to a user, a shared team
space, or both? — before building more on top of the current shared-vault
shape, since some of what's already built (the `reel_corrections` table,
the neighbour-assist pool for classification) would need rethinking
depending on the answer.

## The ceiling that limits search, summaries, and classification alike

Confirmed by direct scan: **11 of 24 saved reels (46%) have comment-bait
captions** ("comment HABITS for my list") where the real content is spoken
in the video and never appears in any text field. This is the audio
transcription gap already flagged as a standing priority (see the
`reel-vault-audio-transcription-priority` memory) — today's testing added
two concrete data points (a misclassified Cryptocurrency reel, a
summarizer hallucination on a Habits reel) but nothing new to build yet.
Still the correct next big investment.

## Gaps identified, deliberately deferred

- **Editable tags.** A reel can be moved between collections, but its tags
  are fixed at save time. Tags now drive keyword search, so a wrong tag is
  a wrong search result, not just a wrong label.
- **Bulk / collection-level moves.** Every correction is one reel at a
  time. Fine at 24 reels, won't be at scale. (Rename/merge a whole
  collection falls under this too.)
- **No delete/forget**, confirmed absent — no route removes a saved reel.

## Scaling risks, not bugs yet (vault is too small to have hit them)

- **Single-term keyword queries have no ranking.** `"AI"` scores every
  match identically at 0.80 (see `reel_vault/search.py`,
  `KEYWORD_WEIGHT`) — harmless at 24 reels, returns hundreds tied with no
  order at real scale.
- **`DEFAULT_TOP_K_LIST = 50` is a silent cap** (`vault.py`). A collection
  with 73 reels shows "50 reels in X:" with no indication 23 were dropped.
- **No pagination anywhere.** Deferred earlier in the project, still
  deferred.

## Loose ends from live testing, never confirmed working

From the last testing round — send results next session:
- Double move + double undo (single move+undo confirmed working)
- A third undo attempt (nothing left) → should say "nothing to undo"
- A `pic=N` reel (no thumbnail) → text-only reply with a working Move
  button attached
- Re-sharing a reel in a different URL shape (`/reel/` vs `/p/`) than
  originally saved → should say "already saved," not duplicate

## Process gaps

- **No CI** — confirmed, no `.github/workflows/`. Tests only run when
  someone runs them locally.
- **The Groq model is small** (`gpt-oss-20b`). It just demonstrated a real
  ~20-40% hallucination rate on one summarization case (see
  `known-issues.md`, "The summarizer sometimes credited a caption..."),
  found by accident during manual testing. Classification and the
  neighbour-assist reasoning haven't been stress-tested for the same
  failure pattern — they may have it too; nobody's looked yet.

## Recommendation

Settle the multi-user/scoping question first. It changes the schema and
could mean rethinking work already built (corrections table, neighbour
pool) before building further on top of it. Everything else in this file
can layer on whatever that decision turns out to be.
