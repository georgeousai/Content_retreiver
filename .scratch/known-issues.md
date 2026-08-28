# Known issues and fixes

A running log of real problems found (mostly through live use of the bot, not
just planned tickets) and what fixed them. Newest first. Each entry links the
commit that has the full story in its message.

Not a spec or a ticket — see `.scratch/<feature>/spec.md` and
`.scratch/<feature>/issues/` for planned work. This file is for things that
broke or were missing, discovered after the fact.

---

## A reel was filed on the wrong shelf, with no way to say so

**Symptom:** `"Five Year Journey #fyp📈 #smallbusiness"` filed under
`Personal Growth › Journey`; it belonged under `Entrepreneurship`. No way for
the user to correct it — the classifier's decision was final.

**Cause:** Rule 2 of the collection prompt says *"STRONGLY prefer reusing an
existing collection"* — deliberate, to stop near-duplicate shelves
multiplying. `Personal Growth › Journey` already existed (from *"6 months to
become unrecognisable"*), and the caption's word *Journey* matched it exactly,
so reuse pressure beat what `#smallbusiness` was pointing at. Both candidate
collections already existed; the subcollection name broke the tie.

**Not fixable by prompting.** A five-year journey building a small business
genuinely *is* both Personal Growth and Entrepreneurship. There is no wording
that gets this class of reel right for everyone — only the user knows which
shelf they'll go looking on.

**Fix:** Two ways to overrule it, because they fail differently.
- **Reply to the reel's card** with `Entrepreneurship / Small Business` — sets
  collection *and* subcollection, and is the only route to a shelf that
  doesn't exist yet.
- **A `Move` button on every card** (including the save confirmation, where a
  misfiling is most likely to be spotted) — the one a user finds without being
  told it exists. Buttons set collection only.

The reel a card refers to is read back out of the card's own printed link,
not from a message-id→reel map — that map would die on restart, and a user
replying to yesterday's card would have no way to know.

**Re-filing re-embeds.** Since a reel is embedded together with its
collection, a move that rewrote only the taxonomy would leave it findable
under the shelf it just left. Caption, tags, author, thumbnail and `saved_at`
are carried across untouched. Verified live:

```
before: Personal Growth / Journey      after: Entrepreneurship / Small Business
re-embedded: True   caption intact: True   picture kept: True   saved_at kept: True
```

**Known nuance, not a bug:** after the move, the reel still appears for
`"reels about personal growth"` — at **0.40**, below all six real Personal
Growth reels at 0.80. Its tags still include `growth`, which is accurate; a
five-year business journey *is* about growth. Partial matches surfacing below
exact ones is the coverage mechanism working.

**Commit:** `413c7d7` — Let the user overrule where a reel was filed

---

## Search ignored everything the vault knew except the caption

**Symptom:** "reels about interview prep" → "Nothing in the vault matches
that", with a reel filed under `Product Management › Interviews` and tagged
`case prep` sitting right there. Separately, "show me all my Sales reels"-style
queries worked, but any query naming a *sub*collection or a tag did not.

**Cause:** Retrieval had exactly two paths — cosine similarity over the
caption embedding, or an exact-name match on `collection`. `subcollection` and
`tags` were written, indexed, and never read by any query. Measured against
the live vault:

```
'reels about interview prep'           threshold 0.35
  0.330  [Product Management/Interviews]  I've interviewed over 30 AI PM candidates…
  0.285  [Product Management/Interviews]  We FIIIINNAAALLLYY have a product manager…
  0.218  [Computer Science/Bit Manipulation]  DSA interview concept Bit Manipulation…
```

Missed by 0.02 — but not a threshold to tune. Ranking was weak in both
directions: for the bare query `interview`, the top hit (0.361) was a caption
that never uses the word, above "DSA interview concept" (0.299).

**Fix:** Two retrieval arms, one per kind of text a reel carries. Captions
(free prose) stay on vector similarity; collection/subcollection/tags (a short
curated vocabulary) get keyword matching via Postgres english text search.
Both score 0–1 so one threshold still governs; a reel matching on both keeps
its *better* score, not the sum. Keyword hits are scored by what fraction of
the query's terms they account for — 1-of-4 lands at 0.2 and stays out, 2-of-2
at 0.8 — with framing words ("show me all my … reels") dropped first so
relevance doesn't depend on phrasing. Captions are deliberately excluded from
the keyword arm: they're long enough to share a word with any query by chance.

Verified against the live vault after backfill:

```
'reels about interview prep'  ->  0.800 / 0.400 / 0.400  (3 reels)
'show me my bit manipulation reels'  ->  0.800
'reels about cooking'  ->  nothing, correctly
```

**Two consequences worth knowing:**
- A reel is now embedded *with* its metadata, so it can't be embedded until
  its collection is settled. A save paused on `NeedsCollectionChoice` no
  longer carries an embedding.
- `metadata_text` is written by Python, not a Postgres `GENERATED` column —
  `array_to_string` over `tags` isn't immutable, so Postgres rejects it
  outright.

**Migration:** existing rows must be re-embedded and have `metadata_text`
filled, or the new arm finds nothing for them. Captions/collections/tags/
thumbnails are untouched by it. Done for the 22 rows in the dev vault.

**Commit:** `b773353` — Search what a reel was filed under, not only what its caption says

---

## Summaries arrived as escaped entities, and read as a table of contents

**Symptom:** "Dev&#x27;s Vlog Diary" shown literally. And asking to summarize
8 Personal Growth reels returned 8 lines — one per reel, each restating that
reel's caption under its creator's name.

**Cause (a):** `reply_text(_esc(answer.text))` escaped the text but passed no
`parse_mode`, so Telegram delivered the entity as characters. The only reply
in the bot that escaped without declaring HTML.

**Cause (b):** The prompt demanded substance over description but never said
what the answer should be *organized around*, so one-line-per-reel was the
path of least resistance.

**Fix:** The prompt now groups by theme by default (by creator only when
asked), opens with a direct answer, and drops captions that are bare titles.
Formatting is a controlled vocabulary rather than free HTML — the model writes
`## ` headings and `- ` bullets, and the renderer escapes *first*, then
converts those markers. A model emitting HTML directly would put every reply
one malformed tag away from Telegram rejecting the whole message, and a
rejected send is worse than an ugly one.

**Ceiling:** none of this manufactures substance for a reel whose caption is
`"Five Year Journey #fyp📈"`. That is the audio-transcription work, not a
prompt.

**Commit:** `efdb9ca` — Let a synthesized answer be read as an answer

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
