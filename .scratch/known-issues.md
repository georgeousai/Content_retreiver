# Known issues and fixes

A running log of real problems found (mostly through live use of the bot, not
just planned tickets) and what fixed them. Newest first. Each entry links the
commit that has the full story in its message.

Not a spec or a ticket — see `.scratch/<feature>/spec.md` and
`.scratch/<feature>/issues/` for planned work. This file is for things that
broke or were missing, discovered after the fact.

---

## URL matcher and dedup key disagreed on what an Instagram URL is

**Symptom:** Sharing `instagram.com/ukjobsinsider/reel/DchAYCOtOI0/` (a
profile-scoped share) got "That doesn't look like a post or reel link I can
save" — even though the plain `/reel/<code>/` and `/p/<code>/` forms worked.

**Cause:** `bot.py` had its own regex deciding "is this a savable link," and
`urls.py` had a separate function computing the dedup key from whatever URL
got through. They were never the same code, so they silently drifted: the
matcher never learned the `<username>/reel/<code>/` shape, and the key
function kept the *entire path*, so `/reel/X`, `/p/X`, and `/user/reel/X`
would each have saved as three different rows for one reel if the matcher
had let them all through.

**Fix:** One regex (`INSTAGRAM_POST_URL` in `urls.py`) extracts Instagram's
shortcode — the part that's actually the reel's identity — with everything
else (username segment, `reel`/`reels`/`p`/`tv`) treated as decoration around
it. Both `find_reel_url()` (the accept/reject gate) and `normalize_reel_url()`
(the dedup key, canonicalized to `.../p/<shortcode>`) read from the same
pattern, so they can't disagree again.

**Commit:** `02373af` — Recognize every Instagram URL shape by its shortcode, not its prefix

---

## List/aggregate replies looked like a disconnected wall of text + photo album

**Symptom:** "show me all my Sales reels" printed a plain-text list of
`• url (Sales) — @handle` lines, then a separate Telegram photo album
underneath with no visual link between a line and its picture.

**Fix:** Each matched reel now sends as its own message — a photo captioned
with its own link, collection (bold), and tags where a thumbnail exists,
plain text otherwise. The picture sits directly under its own details
because it's the same message. Real HTML formatting (bold, tappable links)
replaced emoji-prefixed plain text.

**Also fixed in the same pass:** sub-collections were never being invented —
the collection-assignment prompt said "reuse an existing sub-collection" or
"use null when specific enough," but never told the model to create the
first one for a topic. With zero sub-collections existing anywhere, nothing
was ever specific enough to reuse, so it always fell to null.

**Commit:** `223966d` — Give every reel its own card, and let sub-collections actually get invented

---

## Startup hung silently when the database wasn't there

**Symptom:** Running the bot printed the embedding-model load log and then
nothing — no crash, no error, no Telegram polling. Looked like a bot that
started fine and was ignoring every message.

**Cause:** `PostgresReelStore` connects to Postgres on the line right after
the embedder loads. An unreachable database (the Docker container simply not
started) *times out* rather than refusing the connection, so the process
just hung there with no log line saying a database was even involved.

**Fix:** The store now logs the host it's dialling before connecting, bounds
the attempt to 10 seconds, and turns a timeout into a `RuntimeError` naming
the host and asking "Is the database container running?"

**Commit:** `0ce0f43` — Say when the database isn't there instead of hanging

---

## "my Sales reels" was searched semantically instead of read from the shelf

**Symptom:** "show me all my Sales reels" replied "Nothing in the vault
matches that" while two Sales reels existed. "what have my sales reels said,
grouped by creator" summarized only 1 of 2.

**Cause:** Every reel is filed into a collection at save time, but `ask()`
never used that filing — "my Sales reels" ran as a semantic search over the
literal sentence against caption text, at a similarity threshold nowhere
close to a match. Structurally unfixable by tuning the threshold: one Sales
reel's caption was "5yrs ago this wasn't a thing," which will never score
close to any query about sales, no matter the threshold, because the words
just aren't there.

**Fix:** Classification now receives the collections the vault actually
holds and returns the one the user named (snapped onto the vault's own
spelling; a name that isn't a real collection is dropped so retrieval falls
back to search). Naming a shelf routes straight to a `find_by_collection`
lookup — no embedding, no threshold. A topic that merely sounds like a
collection ("reels about biceps") still searches semantically.

**Also fixed:** the summarizer prompt was letting the model describe its
sources ("shares 4 bicep hacks") instead of reporting them, pad answers with
reels that only carried a matching hashtag, and format markdown tables that
Telegram rendered as literal `|` pipes.

**Commit:** `d3d4f8f` — Answer "my Sales reels" from the shelf, not by similarity

---

## Two bot processes both said "Saved!" for one row

**Symptom:** Sharing a reel while two `reel-vault` processes were running
produced two separate "Saved!" confirmations, but only one row in the
database.

**Cause:** `ReelStore.save()` used `INSERT ... ON CONFLICT DO NOTHING` and
discarded the outcome, so `save_reel()` reported `Saved` regardless of
whether the write actually happened. The losing process's insert did
nothing, but it still congratulated the user on a save it didn't make. Not
just a two-process problem — the same race is a double-tap away, and stops
being incidental the moment two users can share the same reel.

**Fix:** `ReelStore.save()` now reports whether it actually inserted
(`rowcount` on Postgres, key presence in the in-memory fake). A no-op write
returns `AlreadySaved` with the row that won, instead of a false
confirmation.

**Commit:** `c6f5cc8` — Stop claiming "Saved!" for a write that did nothing

---

## Thumbnails needed a second Telegram client and a manually configured chat ID

**Symptom:** The original thumbnail design required setting
`TELEGRAM_THUMBNAIL_CHAT_ID`, found by inspecting `getUpdates` — a step with
no clear instructions, and silently-off if skipped.

**Cause:** The uploader was a standalone adapter making its own raw HTTP
calls to the Telegram Bot API with a second copy of the bot token, posting a
throwaway upload message and deleting it, to a chat ID the user had to
discover manually.

**Fix:** The save confirmation is sent as the reel's own picture, using the
bot's existing Telegram connection. Telegram's response to that one message
hands back a durable `file_id`, which is what gets stored. No second client,
no env var, no chat to configure — one message instead of two-then-delete.

**Commit:** `ae1bffc` — Mint the thumbnail file_id from the save confirmation itself

---

## Older, planned work (from spec/ticket decomposition, not live bugs)

These came from `/grill-with-docs` → `/to-spec` → `/to-tickets` sessions
rather than from something breaking live — listed here only for continuity
with the commits above:

- `5f39803` — SINGLE/LIST/AGGREGATE query classification, replacing a binary
  is-this-an-aggregate check that silently truncated "show me all" to 5.
- `bd4a99e` — Author-filter queries ("show me @gymshark's reels") bypass
  embedding search entirely via a plain `find_by_author` lookup.
- `9bdb000` — Author threaded into the summarizer so "which creator said
  what" can be answered, instead of every caption being anonymous to it.
- `b79ffef` / `bacc858` — Thumbnail capture and display (superseded by the
  `ae1bffc` redesign above).
