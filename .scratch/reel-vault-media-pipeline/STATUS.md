# Status as of 2026-08-31

Live-testing the media pipeline (issues 01-06, all built and unit-tested
against fakes) against real Groq/Gemini/Postgres. This file is what is still
open.

One bug is fixed and verified, and has moved to
[`known-issues.md`](../known-issues.md): the oEmbed caption fetcher failing
on every save (it needed `follow_redirects=True`, and then needed the
non-JSON body that follows the redirect handled, or the save would have
crashed instead of falling back). Everything else below is still open.

## Open: the condenser empties real content - fix written, NOT yet verified

`ChatContentCondenser` (`adapters/llm.py`, `CONDENSE_SYSTEM_PROMPT`)
correctly returns empty for genuine artifacts and hooks, and wrongly returns
empty for transcripts full of real content. Measured against the live
provider (`openai/gpt-oss-20b`, temperature 0.0, 10 runs each, using
`transcript_raw` straight out of the vault):

```
chicken recipe        713 chars   emptied  9/10   WRONG
Hindi interview-prep  710 chars   emptied  4/10   WRONG
RAG pipeline         2304 chars   emptied  8/10   WRONG
fragrance intro       157 chars   emptied 10/10   correct
"."                               emptied 10/10   correct
"Thank you."                      emptied 10/10   correct
RAG vs CAG           1986 chars   emptied  0/10   correct
```

Two things in that table were not known before:

- **The 2304-char reel fails 8/10**, even though the previous version of this
  file recorded it as a success and its row in the DB holds a 1736-char
  summary written at save time. So the failure is not confined to "terse,
  list-like" content — the longest transcript in the vault fails too, and the
  shape hypothesis in the earlier writeup is at best incomplete.
- **It is stochastic at temperature 0.0**, the same way the summarizer
  hallucination in `known-issues.md` was. Any verification has to be a rate
  over repeated runs; a single clean run proves nothing.

**Fix written, following this repo's own established pattern** (see
`known-issues.md`, the caption-crediting hallucination: an abstract rule did
not hold, a concrete counter-example naming the exact failure did).
`CONDENSE_SYSTEM_PROMPT` now carries the chicken-recipe transcript verbatim
as a named example of an input to condense rather than empty.

Kept deliberately narrow: an earlier draft also added general rules ("length
and language are never reasons to empty"), and those were removed. The
lesson being followed says a concrete counter-example works where a broader
restatement of the rule does not, so adding both would have been hedging
against the very pattern being applied — and it would have cost tokens on a
prompt that is already the reason the daily quota ran out.

Both failing transcripts are now pinned verbatim in
`tests/test_condenser_prompt.py`, including the Hindi one, which existed
nowhere git tracked before today. Only the recipe is in the prompt. If the
recipe alone turns out not to move the rate, the Hindi transcript is the
next counter-example to add, and there is a live test already written for it.

**It is not verified. The prompt as committed has never been run against a
model at all.** Groq's free tier has a 200,000 tokens-per-day cap;
establishing the baseline above exhausted it, and the enlarged prompt costs
roughly twice as much per call (~343 to ~727 tokens, twice per reel). Two
samples were squeezed through afterwards against a longer draft — one
emptied the recipe, one condensed it correctly — and that draft was then
trimmed (see below), so even those two do not describe what is committed.
Two samples against a 9/10 baseline would not have settled it anyway.

The remaining daily quota was deliberately left unspent rather than burned
on more samples of a superseded draft.

**Do this first next session**, once the quota has reset:

```
RUN_LIVE_MODEL_TESTS=1 uv run pytest tests/test_condenser_prompt.py -v
```

Those tests re-run the measurement against the exact failing transcript and
against the controls, and they exist precisely so this does not get called
fixed on a hunch. If the counter-example turns out not to move the rate, the
next thing to try is a smaller counter-example — the current one is a long
verbatim recipe, and it may be diluting the instruction it is meant to
sharpen — or moving the empty-or-not decision out of the prompt and into
code, since "does this text contain a concrete noun, number or step" is
arguably not a judgement that needs a model at all.

The hermetic tests in `tests/test_condenser_prompt.py` run by default and
guard the prompt's contents; only the live measurement is gated.

## Resolved by investigation: the whiteboard reel was never a sampling bug

This was logged as "frame sampling under-covers a video's actual content"
and flagged as ambiguous between **coverage** (the sampler never picked a
frame showing the whiteboards) and **legibility** (it did, and the small
handwriting did not read cleanly). The recommendation was to dump the frames
to disk and look before touching any sampling logic. That was done, and the
answer is **neither**.

`scripts/dump_reel_frames.py` now does this on demand. For the RAG vs CAG
reel (`https://instagram.com/p/DcoQRJKguIZ`):

```
91.6s, 2747 frames, 720x1280, 3 detected scenes (starts 0, 2534, 2598)
chosen frames: 85, 600, 1266, 1287, 1974, 2565, 2661, 2672
chosen times:  2.8  20.0  42.2  42.9  65.8  85.5  88.7  89.1  seconds
```

**Coverage is ruled out.** Both whiteboards are fully drawn and squarely in
shot in *every* one of the eight frames, starting with the first at 2.8s.
Every label the analysis missed — Document, Chunk1/2/3, Embedding, User
Question, Vector Database, LLM, "Generates Relevant Response Based on
Retrieval", Documents, User Query, Context Window, KV Cache — is plainly
legible in the JPEGs at 720x1280. Nothing was missed for want of a frame.

**Legibility is ruled out too**, by the frames themselves: in frame 6 the
model transcribed a *screenshot overlay* — a forum post and its reply — at
near-verbatim accuracy, in printed text far smaller than the whiteboard
handwriting it skipped in the same image. It could see that frame fine.

**The actual cause is the vision prompt's scope.** `FRAME_PROMPT`
(`adapters/vision.py`) frames the whole task as reading text *cards*: "these
videos often carry their whole content as text cards, and a missed card is
content lost." A diagram drawn on a physical whiteboard is not a text card,
and the model treated it as scenery to describe rather than text to
transcribe — its closing line was "each facing a whiteboard on which they
are drawing diagrams," a description of the thing instead of a reading of it.

Confirmed by A/B on the identical eight frames, same model, temperature 0.0.
Changing only the prompt to name handwriting, diagram labels and screenshot
text as text to transcribe returned every whiteboard label listed above,
grouped per board. Same frames, same model — so the difference is the
prompt, and sampling was never involved.

**Not fixed, deliberately.** The investigation was scoped to identifying the
cause before changing anything, and the cause turned out to be neither of
the two candidates, so the prompt change has not been made. Two things to
decide before making it:

- The A/B run also showed the wider prompt inventing detail. Asked to read
  everything, the model rendered the forum post's compensation figures as
  "base of $200,000, bonus of $20,000 and stock options of $100,000" — the
  frame actually reads "Base: 145k, Signing bonus: 20k, Relocation: 3k,
  Stock: 90k". The shipped prompt got it wrong too ("over $200,000"), so
  this is not a regression, but widening the instruction without a rule
  against filling in unreadable text would make it worse.
- The wider prompt also reads *incidental* screen content — a forum post
  about a DoorDash offer, in a reel about RAG — which is already the largest
  chunk of this reel's `frame_analysis_raw` and is noise for retrieval.

**Separate finding, also not acted on: the frame budget clusters.** For this
reel, three of eight frames land in the last 6.1 seconds of a 91.6-second
video, because both detected cuts are at the very end and each contributes a
scene midpoint. Two more (1266 and 1287) are 0.7 seconds apart — a scene
midpoint and a fill frame that `_topped_up` did not merge, because it only
drops exact index collisions. So the 84-second body of the explainer is
covered by four distinct moments, not eight. This is the mirror image of the
front-clustering `_topped_up`'s docstring says it was written to prevent. It
cost nothing here (the whiteboards are static and in every frame), so it is
not the bug above, but it is real and would bite a reel whose content
changes across the middle.

## Not confirmed: a query that should have matched a transcript did not

Logged, not fixed. Investigating it turned out to be cheap, so here is what
it looks like against the live vault (local embedder + Postgres, no LLM;
threshold 0.35):

```
'how does a RAG pipeline work'
  0.361  @qconconferences   no transcript at all - matched on caption
  0.336  @bashi_fuirkashi   RAG vs CAG reel, transcript summary 675 chars
  0.161  @bashi_fuirkashi   2304-char transcript that IS a RAG pipeline walkthrough
```

The two reels whose transcripts answer the question directly both fall below
the threshold; the one that surfaces has no transcript. Two separate causes,
both worth knowing before anything is changed:

1. **The embedder silently truncates.** `all-MiniLM-L6-v2` has
   `max_seq_length = 256` word-pieces and sentence-transformers drops the
   rest without a warning. `embedding_text` orders the parts as
   collection | subcollection | tags | caption | transcript_summary |
   frame_analysis_summary, so the media summaries are last in line. Across
   the live vault, 7 of 33 reels overflow, and for 2 of the 3 overflowing
   reels that have media summaries the summaries never reach the embedder at
   all — including the RAG vs CAG reel at 0.336, which drops 40% of its
   tokens. The one part the media pipeline exists to make searchable is the
   first thing thrown away.

2. **Truncation is not the whole story.** For the 2304-char reel, embedding
   the transcript summary *on its own* still scores 0.161 against the query
   — the same as the full text. Its summary opens "Ingest documents, chunk
   them, create embeddings, store in a vector database, retrieve relevant
   chunks, pass to an LLM to generate an answer," which answers the question
   almost word for word. A 384-dimension MiniLM matching a natural-language
   question against a terse noun-phrase list is simply weak, and no
   threshold fixes it.

So this is not one bug. Ordering or budgeting `embedding_text` around the
truncation limit is a contained fix; the second point is a model choice, and
touches the same "the embedding model is small" theme as the `gpt-oss-20b`
note in the query-answering STATUS. Neither is done.

## Live-tested and confirmed working

- Save confirmation returns immediately; video processing genuinely runs in
  the background (tested via real Telegram shares, not fakes).
- `processing_status` correctly reaches `done`, `transcript_raw`/
  `frame_analysis_raw` populate from real Groq Whisper / Gemini calls.
- The provider-agnostic config (`LLM_API_KEY`/`VISION_API_KEY` etc.) works
  against real Groq and real Gemini endpoints.
- Content that exists only in spoken audio is retrievable by search (verified
  against the RAG/CAG and mock-interview reels, both of which condensed and
  embedded correctly) — with the truncation caveat above.
- Whisper's own artifacts on silent/musical audio (`"."`, `"Thank you."`) are
  handled sensibly — treated as real content by the pipeline (marked `done`,
  not `failed`, since *something* was read), correctly emptied by the
  condenser rather than manufacturing a fake summary from two words.

## Retracted from the earlier version of this file

A 12.5-second perfume-recommendation reel was logged as "only 1 of 5
products caught" by frame analysis. That read came from pgAdmin's grid
truncating the cell by column width, not from the real data — querying
Postgres directly shows `frame_analysis_summary` contains all five
fragrances. **Not a bug.** Lesson: always read a long text column via a
direct query or an expanded cell view, never trust a grid's default width.

## Restart-resume — not actually tested yet, despite one attempt

A Ctrl+C-based attempt looked like it tested this but didn't. Trace of what
actually happened: Ctrl+C stopped Telegram's polling loop ("Application is
stopping" in the log), but the media job was running inside
`asyncio.to_thread`, and Python's default interpreter shutdown **waits for
all such threads to finish before the process actually exits**
(`concurrent.futures.thread._python_exit` joins every worker thread). So the
process didn't die when Ctrl+C was pressed — it kept running in the
background, finished that reel's transcription/frame-analysis, and only then
exited. The row reached `done` because the same process finished the job,
not because a restart resumed anything. Resume-on-startup has not been
proven yet.

**To actually test it:** a graceful Ctrl+C isn't a hard enough kill. Share a
reel, then in a second terminal immediately force-kill the process
(`Stop-Process -Id <pid> -Force` on Windows, or closing the terminal window
entirely) *before* it would plausibly finish — then check the row reads
`pending`, restart, and confirm it flips to `done` without re-sharing the
link. This is worth doing early in the next session, since it wasn't easy to
land cleanly by hand at normal typing speed (the window between "share" and
"the job likely finishes" is short).

## Not yet tested

- Compare/rank and extract/compile against real saved reels (only tested
  against fakes so far).
- Restart mid-processing (kill the bot after a share, before the worker
  finishes, confirm it resumes on next startup).
- A save that should fail cleanly (private/deleted post) — confirm
  `processing_status = 'failed'`, reel still fully usable on caption, worker
  doesn't die.
- No leftover temp files after several real downloads.

## Known cost note

The condense prompt roughly doubled in the attempt at the emptying bug
(~343 to ~727 tokens), and it runs twice per reel — once for the transcript,
once for the frame analysis. On Groq's free tier that is a real constraint:
measuring against it hit the 8000 tokens-per-minute limit repeatedly and
then exhausted the 200,000-per-day cap outright, which is why the fix is
still unverified. It is not a problem for one save at a time; it would be
for a backfill, and it is a reason to prefer a shorter counter-example if a
shorter one works.

## Recommendation

**Start by running the gated condenser tests.** One of the two confirmed
bugs (oEmbed) is fixed and verified; the other (the condenser) has a fix
written and regression tests around it, but no evidence yet that it works —
and the one post-fix sample that got through still failed. That is the
cheapest open question and the only one where work is already sitting
unproven.

Then: the frame-analysis prompt fix is diagnosed and ready to write, pending
a decision on the two caveats above. The retrieval question needs a call
rather than a patch, since half of it is a model choice. Then the untested
items — restart-resume first, since it is the only one that could lose a
user's save.
