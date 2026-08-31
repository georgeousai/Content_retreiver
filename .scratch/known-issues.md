# Known issues and fixes

A running log of real problems found (mostly through live use of the bot, not
just planned tickets) and what fixed them. Newest first. Each entry links the
commit that has the full story in its message.

Not a spec or a ticket — see `.scratch/<feature>/spec.md` and
`.scratch/<feature>/issues/` for planned work. This file is for things that
broke or were missing, discovered after the fact.

---

## oEmbed failed on every save, and following the redirect would have crashed it

**Symptom:** `oEmbed fetch failed for <url>` in the log for every single
save, with the caption arriving from the `yt-dlp` fallback each time. Nothing
visibly broke — a caption still came back — so this had been happening
silently for as long as the endpoint had been redirecting.

**Cause:** `OEmbedCaptionFetcher.fetch()` called `httpx.get()` without
`follow_redirects=True`. httpx does not follow redirects by default, and
`raise_for_status()` treats an unfollowed 3xx as an error, so a 301 landed
straight in the `except httpx.HTTPError` arm. Instagram had started
answering `api.instagram.com/oembed` with a 301 to the trailing-slash form.
Every call failed on the redirect without ever reaching the endpoint.

**What following it actually revealed — the reason this is two fixes, not
one.** Measured live on 2026-08-31 across three URL shapes:

```
follow_redirects=False -> 301
follow_redirects=True  -> 301 -> 302 -> 200, content-type text/html, 619KB
                          <title>Instagram</title>   (the login wall)
```

The endpoint no longer returns JSON to anyone. `api.instagram.com/oembed` is
the legacy unauthenticated endpoint Meta retired in favour of
`graph.facebook.com/<version>/instagram_oembed`, which needs an app token
this project does not have. So `follow_redirects=True` on its own does not
make oEmbed work — it turns a caught `HTTPStatusError` into an **uncaught**
`json.JSONDecodeError` from `response.json()`. Nothing upstream catches it:
`Vault.save_reel()` calls `self._caption_fetcher.fetch(url)` bare, so the
exception would have propagated out and killed the save outright. The "fix"
alone would have converted a silent, working fallback into a hard failure on
every share.

**Fix:** both halves. `follow_redirects=True`, so the call reaches the
endpoint it was aimed at; and `response.json()` wrapped so a non-JSON body
(or a JSON payload that isn't an object) is logged and returns `None`, the
same as any other miss, letting the scraper fallback run. The endpoint is
kept rather than deleted: it costs one request, and it starts working again
the day a Facebook app token is configured.

**Regression tests:** `tests/test_caption_fetchers.py`. Its transport replays
the live chain — 301 to the trailing-slash path, then the HTML login wall —
through a real `httpx.Client`, so httpx itself decides what following a
redirect means and what `raise_for_status` does with one it did not follow.
The tests assert behaviour rather than the call's signature: that the request
which finally lands is for the redirected path (this fails if the flag is
removed — checked by reverting it), that an HTML body is a miss rather than
an exception, and that a real oEmbed payload is still parsed.

**Practical consequence:** captions come from `yt-dlp` in every case today.
That was already true; it is now true on purpose and visible in the log
rather than hidden behind a per-save error.

---

## The summarizer sometimes credited a caption with answering a question it never addressed

**Symptom:** `"how do I grow my personal brand"` against a single matched
reel — caption: `"If you want the full list of habits, COMMENT the word
'HABITS'..."` (no mention of personal branding anywhere) — returned:

> Carina Miller, a business coach, says she has a full list of habits that
> can help grow a personal brand.

That claim is not in the caption. It looked like a nice answer, which is
exactly what made it dangerous: it read as more informative than the honest
"none of the captions address this," while actually being wrong.

**Confirmed real, not a one-off:** ran the identical query/caption 10 times.
**2/10 invented the connection.** Ran again at `temperature=0.0` (down from
0.3, on the theory it was a stochastic slip): **4/10** — temperature made it
*worse*, within noise, and confirmed temperature wasn't the mechanism. The
model was bridging a topical gap ("habits" ≈ "personal brand," adjacent
enough to feel connected) rather than randomly hallucinating.

**Cause:** the existing rule — *"Report only what the captions actually say.
Never invent"* — was abstract, and abstract rules don't reliably suppress a
model's tendency to supply a missing connective claim when two things are
topically adjacent but not actually linked.

**Fix:** added a rule naming this exact failure shape with a concrete
worked example — this caption, this query, the wrong answer and the right
one, spelled out by name. Not a hypothetical; the literal case that failed.

**Result:** 10/10 correct after the change, re-run against the identical
caption and query that produced the original failure.

**Lesson for future prompt work:** when an abstract instruction ("don't
invent") fails at a real rate under test, the fix is a concrete
counter-example naming the specific failure, not a broader restatement of
the same abstract rule.

**Commit:** `61bde6c` — Stop the summarizer from crediting a caption with answering a question it never addressed

---

## The classifier repeated mistakes, and moves could not be taken back

**Symptom:** Two gaps left open after the Move feature. Correcting the same
misfiling twenty times taught the classifier nothing — it would make it a
twenty-first. And a wrong move had no undo; you had to remember the old shelf
and move it back by hand.

**Cause (learning):** The assigner was given the caption and a list of
collection *names*. Names say what shelves exist and nothing about what goes
on them, so the only signal available was word-matching against shelf labels
— which is precisely how `Five Year Journey #smallbusiness` matched a
`Journey` sub-collection belonging to an unrelated collection.

**Fix:** The assigner is now shown the already-filed reels whose captions most
resemble the one being placed, with where each ended up — evidence about how
this library is actually organized. A placement the *user* made is flagged
`[user-placed]` and the model is told to prefer it on conflict.

**Why the flag matters more than it looks:** without it the mechanism decays.
A mistake the classifier made becomes a neighbour, the neighbour becomes
precedent, and the error propagates to every similar reel. A person's decision
is evidence about what they want; the classifier's own earlier guess is not
evidence of anything.

**Two design consequences:**
- **A second embedding per reel.** The retrieval embedding covers collection
  and tags too, so reusing it for neighbour lookup would let a shelf attract
  reels for sharing its vocabulary — reintroducing the exact reuse bias this
  counters, in the place it does most damage. Caption-only embeddings are
  compared caption-to-caption.
- **A similarity floor (0.25).** Live, a novel caption (`"How I closed my
  first enterprise deal"`) drew its five nearest neighbours at 0.15–0.18 —
  unrelated reels formatted identically to real precedent. Noise in the shape
  of evidence is worse than an empty list.

**Verified live** — re-sharing the previously misfiled reel now shows:

```
- filed under Entrepreneurship > Small Business [user-placed] (0.92): "Five Year Journey…"
- filed under Personal Growth > Journey (0.53): "6 months to become unrecognisable…"
```

The correction outranks the mistake, and is flagged as the user's.

**Fix (undo):** Each move is recorded in a `reel_corrections` table; the card
shows `Undo` afterwards. The previous shelf is looked up rather than carried
in the callback — a collection/sub-collection pair overruns Telegram's
64-byte budget on exactly the long names most likely to be misfiled.

Undo **removes** the record rather than reversing it, and restores
`user_placed`. An undone mistake that left that flag set would go on teaching
the classifier something the user had explicitly retracted.

**Migration:** `caption_embedding` backfilled for all 22 rows; without it the
neighbour lookup ignores a reel entirely.

**Still open:** editable tags, and bulk/collection-level moves.

**Commit:** `3a54565` — Place a reel by where comparable reels actually went

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
