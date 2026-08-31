# Status as of 2026-08-31 (evening)

Live-testing the media pipeline (issues 01-06) against real
Groq/Gemini/Postgres. Four things that were open this morning are now
closed, and this file is what is still open.

Closed and verified this session, in the order they were done:

1. The condenser is provider-agnostic (`CONDENSER_*`), and the emptying fix
   is measured — against Gemini, because Groq had no quota left. See below,
   including a control that now fails the other way.
2. The vision prompt reads whiteboards, and does not pay for it in invented
   figures or incidental noise. Re-measured on the same eight frames.
3. `embedding_text` puts the media summaries ahead of the metadata, so
   truncation eats the part that has two other retrieval paths.
4. All four untested items are tested. Restart-resume is proven properly
   this time, with a real hard kill.

Also fixed on the way past, and worth knowing because it contradicts the
README: **the app could not create its own schema on a brand-new database.**
`PostgresReelStore.__init__` called `register_vector` before running the
`CREATE EXTENSION IF NOT EXISTS vector` inside `SCHEMA`, so a first run
against an empty database died with "vector type not found in the database".
It never showed up because every existing vault already had the extension.
The extension statement now runs first, on its own. Found by pointing the
live tests at a throwaway database, which is the only way anyone would hit
it.

## Closed: the condenser empties real content — fixed, and measured

The fix (a verbatim counter-example in `CONDENSE_SYSTEM_PROMPT`, following
the pattern `known-issues.md` records for the summarizer hallucination) had
never been run against a model. It has been now.

**Verified against `gemini-3.5-flash-lite`, not Groq.** Groq is where the
9/10 and 4/10 baselines were measured, and it is where this should be
re-measured when quota allows — the emptying rate is a property of the
model, and this file's own history is the argument for not assuming one
provider's result carries to another. What was available:

```
groq   openai/gpt-oss-20b      199,710 of 200,000 tokens-per-day used - dead
google gemini-2.5-flash        free-tier requests-per-day exhausted   - dead
google gemini-3.5-flash-lite   available                              - used
```

Results, 5 runs each at temperature 0.0, on the transcripts pinned in
`tests/test_condenser_prompt.py`:

```
                        groq baseline    gemini-3.5-flash-lite
chicken recipe (713)    emptied 9/10     PASS  kept >= 4/5, kept "honey"
Hindi interview (710)   emptied 4/10     PASS  kept >= 4/5
fragrance hook (157)    emptied 10/10    FAIL  emptied only 2/5
"." / "Thank you."      emptied 10/10    PASS  emptied both
recipe-leak control     n/a              PASS  no leak into an unrelated reel
```

**Both transcripts that were wrongly emptied are now kept.** That is the bug
this session set out to close, and on this model it is closed.

**The control fails in the other direction, and that is a finding, not a
regression.** The fragrance reel is a pure hook — it promises five
fragrances and names none — and should come back empty. Groq emptied it
10/10. Gemini keeps it 3 times in 5, as a faithful one-line restatement:

```
run 1: EMPTY
run 2: 'Five summer fragrances that get many compliments.'
run 3: 'five summer fragrances that get a lot of compliments'
run 4: EMPTY
run 5: 'five fragrances that get compliments in the summer'
```

Nothing there is invented; it is a compression of a hook that had nothing in
it. So the two providers fail in mirror-image ways: **Groq throws away real
content, Gemini keeps content-free hooks.** Of the two, Gemini's is much the
cheaper failure — a slightly noisier embedding versus a transcript that is
silently unsearchable forever.

The test was left asserting the intended behaviour (`emptied >= 4` of 5)
rather than relaxed to match what this model does. It reports the gap
honestly, which is what it is for.

Not decided here, deliberately: **which provider the condenser should
default to.** It still falls back to `LLM_*`, i.e. Groq. That is now a
one-line `.env` change rather than a code change, which was the point.

## Closed: the vision prompt now reads whiteboards

The diagnosis stood: not coverage, not legibility, just `FRAME_PROMPT`'s
scope. It framed the task as reading text *cards*, and a hand-drawn diagram
is not a card.

Re-measured on the same reel and the same eight frames the diagnosis used —
`scripts/dump_reel_frames.py` against `https://instagram.com/p/DcoQRJKguIZ`
re-derived exactly the frames recorded before (85, 600, 1266, 1287, 1974,
2565, 2661, 2672), so this is a like-for-like comparison. All runs
`gemini-2.5-flash`, temperature 0.0.

```
                         whiteboard labels   incidental overlays   figures
shipped-before prompt    0 of 12             both, in full         "3.5 hour"
                                             (most of the output)  for "3 hour"
this prompt (3 runs)     12 of 12, grouped   one line each         none invented
                         per board, every                          "(illegible)"
                         run                                       where unsure
```

The three changes are the three rules, and each one is load-bearing:

- **Naming what counts as text** — text cards, burned-in captions, and
  handwriting/diagram labels — plus "a diagram is text to read, not scenery
  to describe". This is what recovers the labels.
- **A rule against guessing an unclear value**, with the real measured
  failure as the worked example.
- **Scoping to what the video is presenting**, so a pasted-in screenshot
  gets one line naming it rather than a full transcription.

**One thing learned the hard way, and it is now a test.** The first draft of
the guessing rule quoted the *fabrication* as the example — "a base of
$200,000, a bonus of $20,000 and stock options of $100,000". The very next
run reproduced that string almost verbatim in its answer. The
counter-example handed the model the wrong answer to reach for. The rule now
quotes only the true reading ("Base: 145k, Signing bonus: 20k, Relocation:
3k, Stock: 90k") and describes the invention in the abstract, and
`tests/test_vision_prompt.py` asserts the fabricated figures are *not* in
the prompt. Worth remembering the next time this repo's "a concrete
counter-example beats an abstract rule" pattern gets applied: the
counter-example has to be concrete about the *right* thing.

Not acted on, unchanged from the earlier writeup: **the frame budget
clusters.** Three of eight frames land in the last 6.1 seconds, and two more
are 0.7s apart, so the 84-second body is covered by four distinct moments.
It cost nothing here because the whiteboards are static, but it would bite a
reel whose content changes across the middle.

## Closed: retrieval ordering

`embedding_text` now assembles caption | transcript_summary |
frame_analysis_summary | collection | subcollection | tags.

The embedder truncates at 256 word-pieces without warning and 7 of 33 live
reels overflow, so the tail of that string is what silently stops being
searchable. The metadata is what can afford to be there: it has an
untruncated keyword arm and a direct collection-name lookup that skips
embedding entirely. The media summaries have this one path and no other.

Tested in `tests/test_hybrid_search.py`, including that a reel with neither
summary still assembles without an empty slot or a doubled separator.

**The existing 33 reels do not benefit until they are re-embedded.** Vectors
are stored, not recomputed, and nothing re-embeds a reel except a move or its
video being read. So every row saved before this change still carries a
vector built under the old order — including the 7 that overflow, which are
exactly the ones the reorder was for. A backfill (re-embed every row from its
current columns) would close that, and is the natural next step; it was not
done here because it is a new piece of work, not a fix to this function.

**Half of this problem is still open and is not a patch.** For the 2304-char
reel, embedding the transcript summary *on its own* still scores 0.161
against "how does a RAG pipeline work" — the same as the full text. A
384-dimension MiniLM matching a natural-language question against a terse
noun-phrase list is simply weak. Ordering cannot fix that; it is the "is
MiniLM too weak" question, still unresolved and still deliberately untouched.

## Closed: restart-resume, with a real hard kill

The earlier Ctrl+C attempt was invalidated by Python joining
`asyncio.to_thread` workers at interpreter shutdown. Redone with
`taskkill /F`, which skips that entirely.

Driven through the real `Vault` and the real bot methods (`_on_start`, which
is what calls `resume_pending_media`, and `_read_videos`) against the live
Postgres, with only `run_polling` left out — the thing under test is what
survives a kill, not the transport.

```
1. row reset to pending
2. worker started, download finished, transcription/vision under way
3. taskkill /F /PID 27268   -> SUCCESS, process gone
4. row reads:  pending, transcript_raw 0 chars, frame_analysis_raw 0 chars
5. restart:    resume_pending_media() -> ['.../p/DclWYQ6MaDq']
6. drained after 14s; row reads: done, transcript 818/546, frames 1521/819
```

Nothing half-written at step 4 — `attach_media` writes once, at the end — and
nothing re-shared at step 5. **Resume-on-startup is proven.**

Separately, a reel left `pending` by an earlier interrupted session was
picked up and finished by the first startup of this one, which is the same
mechanism arriving from a real interruption rather than a staged one.

**One real consequence of a hard kill: it orphans the workspace.** The kill
left `%TEMP%/reel-vault-0488z59h/DclWYQ6MaDq.mp4`, 4.4 MB.
`TemporaryDirectory` cleans up on the way out of its block, and a force-kill
has no way out of the block. Nothing sweeps `reel-vault-*` at startup, so
these accumulate one per hard kill. Small, but it is the one thing the
project says it never does — keep a video. A startup sweep of stale
`reel-vault-*` directories would close it; not done, since it is new work.
(The orphan from this test was deleted.)

## Closed: a link that should fail cleanly

Run against a throwaway database so the live vault was untouched; everything
else real — real fetchers against Instagram, real downloader, real worker
loop.

```
save_reel(dead link)                  -> ExtractionFailed  (bot asks for a caption)
save_reel(dead link, manual_caption)  -> Saved, pending, filed to a real shelf
worker reads it                       -> processing_status = failed
worker still alive afterwards?        -> yes
a real reel queued behind it          -> reached done
the failed reel, searched by caption  -> returned, score 0.800
temp directories leaked               -> none
```

All four of the things that had to hold, hold: it fails rather than hangs,
it stays fully usable on its caption, the worker survives it, and the reel
behind it is not lost.

## Closed: no leftover temp files

Four real downloads back to back through the real extractor. The workspace
was already gone after each one, not merely at the end:

```
before: []
  DcoQRJKguIZ -> temp now: []
  DclWYQ6MaDq -> temp now: []
  CuXvHE1Npbp -> temp now: []
  DcljVtcOgEP -> temp now: []
LEAKED: []
```

The only exception is the hard-kill orphan described above.

## Closed: compare/rank and extract/compile against real saved reels

Previously only tested against fakes. Run against the live vault, read-only
(`ask` writes nothing). `gemini-3.5-flash-lite` standing in for Groq.

```
"which of my saved recipes is the quickest to make"
  -> CompareAnswer, criterion "fastest cooking time mentioned", 1 reel
     Named the frying times and then said the total could not be known,
     since prep and sauce times were never stated. Declined to invent it.

"rank my AI reels by how much practical detail they give"
  -> CompareAnswer, criterion "most practical detail given", 6 reels
     A real ranking with per-reel attribution, and it ranked on content
     that only exists because the media pipeline read it - the winning
     reel's "62 PyTorch, NumPy, CUDA and Triton problems across 15
     sections" is out of its frame analysis, not its caption.

"compile all the fragrances my reels recommend"
  -> ExtractAnswer, 5 items, all five fragrances, from frame_analysis_summary

"list every tool or website my saved reels mention"
  -> NoMatch, 0 reels
```

Three of four are genuinely good, and the second is the clearest evidence
yet that the media pipeline pays for itself in answers rather than only in
columns.

**The fourth is a real gap, logged not fixed.** A vault-wide extract query
that names no topic ("every tool or website") retrieves nothing, because
retrieval is similarity-first and "tool or website" resembles no particular
reel. The query kind is right and the extractor works; it is being handed an
empty source list. Whether a whole-vault sweep should bypass similarity is a
design question, not a bug fix.

## Still open

- **Is MiniLM too weak?** The unresolved half of the retrieval question, and
  the same theme as the `gpt-oss-20b` note in the query-answering STATUS.
  Deliberately untouched.
- **Re-measure the condenser on Groq** when the daily cap resets, and decide
  from both numbers whether to point `CONDENSER_*` somewhere else by
  default. The comparison above is one provider against a baseline taken on
  another; it should be one prompt against two providers.
- **Re-embed the existing 33 reels** so the retrieval reorder actually
  reaches them (above).
- **Whole-vault extract queries retrieve nothing** (above).
- **A startup sweep for orphaned `reel-vault-*` workspaces** (above).
- **The frame budget clusters at the end of a long reel** (above).
- **Per-user separation** — still the architectural decision the
  query-answering STATUS says to settle first. Nothing here changes that.

## Known cost note

The condense prompt roughly doubled (~343 to ~727 tokens) and runs twice per
reel. On Groq's free tier that is a real constraint: it is why this session
could not measure on Groq at all. It is not a problem for one save at a
time; it would be for a backfill.

## Retracted from the earlier version of this file

A 12.5-second perfume reel was logged as "only 1 of 5 products caught" by
frame analysis. That came from pgAdmin's grid truncating the cell, not from
the data. Confirmed again from the other end this session: asked to compile
the fragrances, the vault returned all five. **Not a bug.** Lesson: read a
long text column via a direct query, never a grid's default width.
