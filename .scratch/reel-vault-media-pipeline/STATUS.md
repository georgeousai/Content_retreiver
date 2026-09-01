# Status as of 2026-09-01

## The condenser bug is solved, and it was never what it looked like

**`gpt-oss-20b` was running out of output tokens while thinking, and the
adapter was reading that as "the model says there is nothing here."**

That one line explains the whole multi-session investigation below. The
evidence, from one API response for the chicken recipe:

```
finish_reason:    length
reasoning_tokens: 2046
completion_tokens: 2048       <- the entire budget
content:          ''
```

It is a reasoning model. It spends completion tokens thinking before it
writes. On the recipe it thought until the budget was gone and had nothing
left to answer with. `_ChatAdapter._complete` did
`response.choices[0].message.content or ""` and handed back `""` — which is
byte-for-byte identical to the model deliberately returning nothing, and
returning nothing is a meaningful answer here, because emptying a
content-free transcript is the condenser's job.

**Everything that made no sense before follows from this:**

| what was observed | why |
| --- | --- |
| longer transcripts failed more (recipe 9/10, RAG walkthrough 8/10, Hindi 4/10) | more content to reason about, so more likely to exhaust the budget |
| "stochastic at temperature 0.0" | reasoning length drifts run to run; the cliff is a hard token limit |
| a retry at temp 0.0 never helped (fired 3 times, rescued 0) | same input, same reasoning, same overflow — a retry is not an independent sample |
| Gemini behaved completely differently | it is not burning a reasoning budget the same way, so it never hit the cliff |
| the prompt counter-example "helped" | it changed how much the model reasoned, not what it judged |

### The fix

Two changes in `adapters/llm.py`, both small:

- **`reasoning_effort="low"` on the condense call.** Compressing text is
  mechanical; the deliberation is what broke it. Same answer in **101
  reasoning tokens instead of 2046**, 240 completion tokens instead of 3135.
  A provider that has never heard of the parameter gets the call retried
  without it, so this stays a wire-format detail rather than a code path.
- **`TruncatedResponse` raised instead of `""` returned** when a reply is cut
  off before it produces any content. An empty reply is only an answer once
  `finish_reason` has been checked.

Measured after, same model, same pinned transcripts:

```
                      before          after
chicken recipe (713)  emptied 9/10    kept 5/5
Hindi interview (710) emptied 4/10    kept 5/5
fragrance hook (157)  (see below)     emptied 3/3, correctly
```

### What this undid

The empty replies were read as a judgement the model was making, so a lot of
work went into arguing with that judgement. With the real cause fixed, most
of it turned out to be unnecessary and has been removed:

- **The verbatim counter-example is out of the prompt.** It was never the
  fix, it cost ~1200 characters on a call made twice per reel, and it caused
  its own regression — taught to look harder for something worth keeping, the
  model went from correctly emptying a content-free hook 10/10 to 0/5. The
  prompt is now 1731 characters, down from 2909.
- **"Always condense, never reply empty" is out too.** That was written to
  take the judgement away from the model entirely. A/B'd after the real fix,
  it and the plain prompt score *identically* — recipe 5/5, Hindi 3/3, hook
  emptied 3/3 — so the model has its judgement back, and it makes it well.
- **The retry is gone.** It was compensating for a bug that no longer exists,
  and it never worked: it fired on 3 of 5 recipe runs and rescued none of
  them.

**What survives** is `reel_vault.substance.has_substance` — a rule in code
that skips the model call entirely for text with nothing in it (`"."`,
`"Thank you."`, a blank frame reading). It is now honestly a **cost saving,
not a correctness fix**: it saves two calls per silent reel on a free tier.
It deliberately does not try to tell a hook from a real list, because the
obvious proxies measurably run the wrong way — the vault's one real hook is
*longer* and has *more* distinct content words than a habits transcript that
must be kept. That module's docstring carries the numbers.

### The damage, and its repair

The bug had destroyed four summaries across three reels in the live vault —
an empty `transcript_summary` or `frame_analysis_summary` sitting next to a
full `_raw` column, the reel marked `done`, nothing to show anything was
wrong. `scripts/recondense_media.py` (new) rebuilt them from the stored raw
text, so no video was re-downloaded:

```
CuXvHE1Npbp  transcript   713c raw ->  526c summary   (was empty)
DclrBDUt0Bi  transcript   710c raw ->  317c summary   (was empty)
DclrBDUt0Bi  frames      4646c raw ->  677c summary   (was empty)
DcoQRJKguIZ  frames      1436c raw ->  371c summary   (was empty)
```

The 4646-character frame reading is the largest single loss, and the clearest
confirmation of the cause: the more there was to read, the more the model had
to reason about, and the more certain it was to run out of budget before
answering.

Three reels still have a raw transcript and no summary, and all three are
correct — `"."` and `"Thank you."` from Whisper on silent audio, and the
fragrance hook that names no fragrance. The repair script re-condensed those
too and they came back empty again, which is the pipeline working.

Every repaired reel was re-embedded as it was written, so the new summaries
are actually searchable; `scripts/backfill_embeddings.py` now reports all 33
reels current.

### Two bugs the code review caught in the fix itself

Worth recording, because both were in code written to prevent exactly the
failure they would have caused.

**`has_substance` silently emptied every non-Latin transcript.** Its word
pattern was `[A-Za-z]`, so a transcript in Devanagari, Han, Arabic or
Cyrillic scored zero words, named nothing findable (those scripts have no
capitals, and two of the three rules depend on capitals or digits), and was
thrown away — the precise failure the module exists to avoid, reintroduced
one layer down. The vault's Hindi reel passed only by accident: it names Meta
and Netflix in Latin characters. Fixed by counting words in any script, with
a letter count behind it for scripts written without spaces. Four new tests
cover Devanagari, Han, Arabic and Cyrillic.

**`TruncatedResponse` turned a degraded save into a failed one.** Raising it
from the shared `_complete` reached every adapter, not just the condenser.
The others parse their replies and already degrade sensibly — no tags,
`SINGLE`, `Uncategorized` — and nothing in `Vault.save_reel` or `bot.py`
catches an exception from them, so a truncated *tagger* reply would have
aborted the whole save and left the share unanswered. Now only the condenser
opts in, via `empty_reply_is_meaningful=True`, because it is the only one for
which an empty reply is a valid answer and therefore ambiguous. The rest log
a warning, which is what makes the same failure visible elsewhere without
making it fatal.

Also tightened: the `BadRequestError` fallback now checks that the 400
actually names `reasoning_effort` before retrying without it (a context-length
error would otherwise buy a second identical failure and a misleading log
line), and remembers the answer per instance rather than rediscovering it on
every call.

### The lesson worth keeping

**An empty response is not an answer until you have checked
`finish_reason`.** Three sessions of prompt engineering, two providers, and
a rate table measured over dozens of runs all sat downstream of one
unchecked field. Every measurement in that table was real; the conclusion
drawn from it was not.

## The two follow-ups that started the day

Both done, before the above came to light:

- **The condenser measured on Groq**, not just Gemini — which is what
  surfaced the truncation, since it produced the "retry rescued nothing"
  result that made a judgement explanation untenable.
- **The 33 live reels are re-embedded** under the new ordering.
  `scripts/backfill_embeddings.py` (new) walks every reel and rewrites its
  embedding from its current columns; nothing else about the row changes.
  32 of 33 got a new embedding — the ordering changes the assembled string
  for a media-less reel too, since a sentence transformer is not order-blind
  even over the same bag of parts. Idempotent: a second run reports 33
  already current.

Everything below this point is the original write-up from the evening
before. Four things that were open that morning were closed by that
session:

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

## Superseded: the two "condenser judgement" investigations

> **Both sections below drew the wrong conclusion from real measurements.**
> The rates are accurate; the explanation is not. The condenser was not
> making a bad judgement about what to keep — its replies were being
> truncated before it could answer, and the adapter read that as a
> deliberate empty. See the top of this file. They are kept because the
> reasoning is worth being able to retrace, and because the numbers in them
> are still the evidence base for `reel_vault.substance`.

### Superseded: the condenser on Groq — the fix helps, and creates a new problem

Measured 2026-09-01 against `openai/gpt-oss-20b`, the default, once the
prior day's 200k-token daily cap had reset. Same transcripts, same 5-run /
`>=4 kept` bar as the Gemini measurement. Compared against the *original*
unfixed-prompt baseline on Groq (not against yesterday's Gemini numbers,
which are a different model):

```
                          Groq, unfixed prompt    Groq, this prompt
chicken recipe (713)     emptied 9/10 (WRONG)     emptied 3/5, FAILS >=4 kept
                                                   (kept text: faithful,
                                                    trimmed condensations —
                                                    correct where it kept)
Hindi interview (710)    emptied 4/10 (WRONG)     PASS, kept >= 4/5
fragrance hook (157)     emptied 10/10 (correct)  FAILS — emptied 0/5
"." / "Thank you."       emptied 10/10 (correct)  PASS, emptied both
recipe-leak control      n/a                      PASS, no leak
```

**Two real improvements and one real regression, all on the same provider
this fix was originally meant for.** The Hindi transcript — the harder of
the two original failures, since the counter-example is an English recipe —
is now reliably kept. The recipe itself improved from a 10% keep rate to a
40% keep rate, real progress, but still short of the 80% bar the test holds
it to.

**The regression is the same shape as the Gemini control failure, and now
confirmed on both measured providers.** Groq used to correctly empty the
bare fragrance hook 10/10. With the counter-example in the prompt, it now
keeps it every time:

```
run 1: 'five fragrances getting me compliments this summer.'
run 2: 'five fragrances getting me compliments this summer.'
run 3: 'five fragrances that have been getting me a lot of compliments this summer.'
run 4: 'five fragrances getting me compliments this summer.'
run 5: 'five fragrances getting me a lot of compliments this summer.'
```

Nothing invented — it is a faithful one-line restatement of a hook that
named no fragrances — but a hook is exactly the case this method is
supposed to throw away, and now it never does. Groq's version of this
regression is worse than Gemini's: Gemini still emptied it correctly 2/5,
Groq 0/5.

**So the shape of the trade is now clear across two unrelated providers,
which makes it a property of the fix, not of either model.** The
counter-example (a real transcript spelled out verbatim, followed by "this
is what condensing looks like, not emptying") teaches the model to look
harder for something to keep — and it now finds "five fragrances" worth
keeping in a sentence that names none. The original STATUS.md recommendation
for exactly this outcome, written before either measurement existed: *"the
next thing to try is a smaller counter-example — the current one is a long
verbatim recipe, and it may be diluting the instruction it is meant to
sharpen — or moving the empty-or-not decision out of the prompt and into
code, since 'does this text contain a concrete noun, number or step' is
arguably not a judgement that needs a model at all."* Both live tests
(`test_live_a_bare_hook_is_still_emptied` on both providers) are left red
rather than relaxed, on purpose — this is an open regression, not a
tolerance to widen.

Not decided or acted on here: which of the two remedies above to try, or
whether to accept the trade as-is (a wrongly-kept hook costs a little
retrieval noise; a wrongly-emptied transcript costs the content forever,
silently). That is a real product call, not a re-measurement, and it is the
next thing to bring to a decision — see Recommendation.

### Superseded: the condenser empties real content — fixed, and measured

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

**Update, 2026-09-01: the existing 33 reels are now re-embedded.** Vectors
are stored, not recomputed, so every row saved before this change kept a
vector built under the old order until something rewrote it. This didn't
wait for a move or a video read — `scripts/backfill_embeddings.py` (new)
walks every reel via `known_collections()` + `find_by_collection()` (both
already-public store methods, so no new port surface for a one-off script)
and rewrites `embedding` from the row's own current columns. 32 of 33
changed; the ordering changes the assembled string even for a caption-only
reel, since a sentence transformer is not order-blind over the same bag of
parts. Idempotent — safe to re-run any time `embedding_text` changes again.

**Half of this problem is still open and is not a patch.** For the 2304-char
reel, embedding the transcript summary *on its own* still scores 0.161
against "how does a RAG pipeline work" — the same as the full text. A
384-dimension MiniLM matching a natural-language question against a terse
noun-phrase list is simply weak. Ordering cannot fix that; it is the "is
MiniLM too weak" question, still unresolved and still deliberately
untouched. Post-backfill, that reel moved 0.161 -> 0.214: real, and still
nowhere near the 0.35 threshold. See "Still open" for the other reel this
was measured against, whose score barely moved for a different reason (its
caption is long enough to eat the token budget on its own).

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

- **Check the other adapters for the same truncation.** The condenser was
  found by accident; `ChatSummarizer`, `ChatComparer`, `ChatItemExtractor`,
  `ChatTagger`, `ChatQueryIntent` and `ChatCollectionAssigner` all run on the
  same reasoning model through the same `_complete`. They now raise
  `TruncatedResponse` instead of silently returning "" — that part is fixed
  for all of them — but none has been given `reasoning_effort`, and nobody
  has measured how often they truncate. The summarizer is the obvious
  suspect: it reads up to 15 reels into one prompt, so it has the most to
  reason about. **This is the first thing to do next.**
- **Is MiniLM too weak?** The unresolved half of the retrieval question, and
  the same theme as the `gpt-oss-20b` note in the query-answering STATUS.
  Deliberately untouched. The backfill (above) shows this plainly: the
  RAG-vs-CAG reel's match score for "how does a RAG pipeline work" moved
  0.336 -> 0.326 after re-embedding — barely, because its 1223-char caption
  already restates the RAG steps in prose and eats most of the 256-token
  budget on its own. The 2304-char-transcript reel moved 0.161 -> 0.214 — a
  real gain, still nowhere near the 0.35 threshold. Reordering helped
  exactly as much as reordering can; the ceiling is the model and the
  256-token budget, both out of scope here.
- **Re-condense any reel this bug emptied, when a prompt changes.**
  `scripts/recondense_media.py` (new) does it from the stored `_raw`
  columns, so it never re-downloads a video. It has been run once, repairing
  the four summaries the truncation destroyed (see below); it is listed here
  because it will be worth running again after the adapter audit above.
- **Whole-vault extract queries retrieve nothing** (above).
- **A startup sweep for orphaned `reel-vault-*` workspaces** (above).
- **The frame budget clusters at the end of a long reel** (above).
- **Per-user separation** — still the architectural decision the
  query-answering STATUS says to settle first. Nothing here changes that.

## Settled, and no longer open

- **Which provider the condenser defaults to.** It stays on Groq. The reason
  to move it was a failure that turned out to be a truncated response, and
  `gpt-oss-20b` scores 5/5 on both previously-failing transcripts once it is
  allowed to answer. `CONDENSER_*` remains available for pointing it
  elsewhere, and earned its keep: measuring on a second provider is what
  showed the failure was not universal, which is what made a model-judgement
  explanation untenable.
- **The condenser's hook regression.** It was an artefact of the
  counter-example that was added to fix the truncation-that-looked-like-
  judgement. Both are gone; the hook is emptied correctly 3/3.

## Known cost note

Substantially better than it was, in three compounding ways:

```
                        before    after
condense prompt         2909c     1731c   counter-example removed
completion per call     3135t      240t   reasoning_effort="low"
calls per silent reel       2         0   has_substance gates them
```

The completion figure is the one that mattered. At ~3100 tokens a call,
twice per reel, Groq's 200k daily cap was ~32 reels; the measurements in
this file exhausted it twice. That constraint is largely gone.

## Recommendation

**Audit the other adapters for the same truncation, starting with the
summarizer.** The condenser's version of this bug was found only because it
had a visible symptom — an empty column somebody noticed. The same silent
failure in `ChatSummarizer` would look like a slightly worse answer, and
nobody would ever file it. `TruncatedResponse` now makes it loud rather than
silent, which is the safety net; measuring the rate and setting
`reasoning_effort` where it helps is the actual work, and it is cheap now
that the cost per call has dropped.

Then re-condense the four reels whose summaries this bug destroyed.

## Retracted from the earlier version of this file

A 12.5-second perfume reel was logged as "only 1 of 5 products caught" by
frame analysis. That came from pgAdmin's grid truncating the cell, not from
the data. Confirmed again from the other end this session: asked to compile
the fragrances, the vault returned all five. **Not a bug.** Lesson: read a
long text column via a direct query, never a grid's default width.
