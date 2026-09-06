# Reel Vault — To-Do

The one place for things flagged "come back to this later," across sessions.
Kept deliberately short: full reasoning for most of these already lives in
`reel-vault-media-pipeline/STATUS.md` or `reel-vault-query-answering/STATUS.md`
— this is the checklist, not the explanation. Add new items here instead of
starting another status file. Check items off (or move them to
`known-issues.md`) once actually done, don't just leave them stale.

## In progress — resume next session

- [ ] **Finish the live-testing batch.** As of 2026-09-06, 6 reels shared
  across two niches (cooking, strength training) after the DB was cleared
  again. Still to check: burst processing, whether collection classification
  keeps improving with more neighbours, and a natural, unscripted `ask()`
  question once there's enough content to make one meaningful.

## New from live testing (2026-09-06)

- [ ] **The condenser can wrongly empty a short, numerically-specific frame
  reading.** Confirmed live, 5/5 runs, not truncation (`finish_reason: stop`,
  5 reasoning tokens each time). Real example from a strength-training reel:
  "100 reps before bed is all you need for 18 inch biceps in 60 days" — a
  short, headline/hook-shaped claim that nonetheless contains three concrete
  numbers, which the condense prompt's own rule says to keep. Looks like the
  model is pattern-matching "sounds like a hook" without weighing the
  presence of real numbers heavily enough on *short* inputs specifically —
  different shape of failure than the messy-long-transcript under-keeping
  case below. Only one confirmed example so far.
- [x] **DONE 2026-09-06 — `has_substance` doesn't catch Whisper
  hallucinations that happen to look like real language.** Fixed upstream of
  `has_substance` instead: `adapters/transcribe.py` now asks for
  `verbose_json` and discards a transcript only when the model was *both*
  unsure and said almost nothing for the length of the audio. Calibrated on
  six real reels; density turned out to be the stronger signal (1.14 vs
  11.90 chars/sec between the worst hallucination and the worst real
  transcript, against 0.41 on confidence), and confidence alone proved
  unstable — the same reel scored -0.509 and -0.677 on two runs of identical
  audio. Verified live: 6/6 correct, both hallucinations emptied, all four
  real transcripts kept. `tests/test_transcription_gate.py`.
- [ ] **Whisper's Hindi transcription accuracy is genuinely poor on fast/
  colloquial Hinglish, and the full `whisper-large-v3` does not fix it.**
  Measured on the strength-training reel: turbo produced 385 chars of
  mostly-garbled Hindi (avg_logprob −0.68, min −1.67); full v3 produced 183
  chars that were cleaner-looking but hallucinated ("subscribe... WhatsApp").
  Neither is usable. Real content (5 kg dumbbells, 5 sets, biceps) survives
  in both, so it's not a total loss, but it's the underlying model's ceiling
  on this kind of speech, not a Reel Vault bug. A Hindi/Indic-specialised
  ASR (e.g. Sarvam's Saarika) is the real lever — but its API is not
  OpenAI-shaped, so unlike every other provider swap so far it needs a small
  new adapter behind the `Transcriber` port, not just a `.env` change.
- [ ] **Add a transcription-confidence gate — the evidence-backed fix for
  hallucinated transcripts on music-only reels.** Whisper's `verbose_json`
  returns per-segment `avg_logprob`, which the app currently discards.
  Measured 2026-09-06 on real reels: narrated speech ≈ −0.13; hallucinated
  segments on the two silent reels ("Sous-titrage Société Radio-Canada",
  "I'm going to go to the next video") ≈ −1.2 to −1.4; the garbled Hindi
  reel ≈ −0.68. A gate around −0.6/−0.7 would have emptied both silent reels
  *and* flagged the garbled one. **`no_speech_prob` is NOT usable** — it
  reads 0.000 on every segment on Groq, almost certainly because these reels
  have background music, not silence. Caveat: threshold calibrated on 4
  reels; check it against a few more narrated ones before shipping. Contained
  to `adapters/transcribe.py`.
- [ ] **A frame-analysis failure is marked `done` and never retried.** Real
  example: `DJWt0lGyRGJ` has a full transcript and *zero* frame data. In
  `media.py`, a vision error (a Gemini rate limit, most likely) is caught,
  logged at INFO only, and returns "" — then the reel is marked `done` because
  the transcript half succeeded. In the DB that's indistinguishable from "the
  video had nothing on screen," and nothing ever comes back for it. Worth
  either a `partial` status or logging at WARNING so it's visible.
- [ ] **The classifier only ever sees the caption** — the transcript and
  frame summaries arrive later, in the background, after the collection is
  already assigned. Real cost, 2026-09-06: a Bengaluru restaurant-visit reel
  was filed under "Cooking > Ramen" because its caption mentioned in-house
  noodle-making, three food reels already sat in Cooking, and rule 2 of the
  prompt says "STRONGLY prefer reusing an existing collection." The frame
  summary (menu prices, "Neon Market, Indiranagar") would have said
  "restaurant" plainly — it just wasn't there yet. Options: reclassify after
  media processing when the summaries disagree with the caption, or soften
  the reuse bias. Relates to the onboarding-survey idea below.

## New from today's live testing (2026-09-02)

- [ ] **The condenser may under-keep messy, real-world non-English audio.**
  Confirmed *not* a repeat of the truncation bug (no exception raised — this
  was a genuine, repeatable model decision, empty 3/3 on retest). One real
  example: a Hindi transcript recommending a specific YouTube channel
  ("Pepcoding") for coding practice was emptied, even though
  `has_substance` correctly flagged it as having content. Only one data
  point so far — watch for repeats on future real saves before deciding
  whether this needs a prompt change.
- [ ] **Is `reasoning_effort="medium"` better than `"low"` for the item
  extractor?** Still unmeasured — Groq's daily cap ran out both times this
  was attempted (2026-09-01 and 2026-09-02).
- [ ] **Turn the retrieval-threshold evaluation into a real script.** The
  17-query-plus-6-adversarial-query test that justified moving the match
  threshold to 0.30 only exists as a throwaway scratch file. Save it under
  `scripts/` so it can be re-run later as the vault grows, instead of
  rebuilt by hand each time.

## Feature ideas raised by the user, not yet scoped (2026-09-02)

- [ ] **Onboarding survey to pre-seed collections.** Ask a new user a few
  questions upfront so the classifier has a scaffold instead of inventing
  top-level collections from a single cold-start reel. Tension to resolve
  first: this is a different philosophy from the app's current "make
  correcting a bad guess cheap" approach (the Move button, the correction/
  undo history) — worth deciding deliberately, not bolting on.
- [ ] **Automatic provider failover on rate limit.** If the configured LLM/
  condenser hits a quota wall, automatically retry against a second,
  pre-configured fallback provider instead of stalling for hours. Should
  stay opt-in — a single-key setup must keep working with no fallback
  configured. Real and well-motivated (this session hit Groq's cap
  repeatedly and worked around it by hand), but a genuine feature to design,
  not a quick fix.

## Retrieval / embedding

- [ ] Whole-vault, topic-less extract queries ("compile every tool my reels
  mention") still return `NoMatch` — the extractor itself works, but
  retrieval is similarity-first and never hands it anything.
- [ ] A reel whose caption alone is long enough to eat the whole 256-token
  embedding budget still gets a partially truncated summary, regardless of
  ordering. Needs a bigger embedding model or a higher token ceiling —
  bigger changes than tuning ordering or threshold.
- [ ] Whether the 0.30 match threshold holds as the vault grows past ~33
  reels — not a known problem, just the condition that could reopen it.
  (The reusable eval script above is how to actually find out later.)

## Smaller and lower priority

- [ ] A hard-kill of the bot can leave an orphaned `reel-vault-*` temp
  directory (a few MB of undeleted video). Nothing sweeps these up on
  restart.
- [ ] Frame sampling can bunch its picks near the end of a long video
  instead of spreading evenly. Hasn't caused a real miss yet.
- [ ] Editable tags — fixed at save time, but they drive keyword search, so
  a wrong tag is a wrong search result, not just a wrong label.
- [ ] Bulk / collection-level moves — every correction is one reel at a
  time.
- [ ] No delete/forget — no route removes a saved reel at all.
- [ ] Single-term keyword queries have no ranking (`KEYWORD_WEIGHT` scores
  every match identically at 0.80).
- [ ] `DEFAULT_TOP_K_LIST = 50` is a silent cap, no "N more not shown"
  indication.
- [ ] No pagination anywhere.
- [ ] No CI — tests only run when someone runs them locally.
- [ ] Untested from an earlier round: double move + double undo; a third
  undo attempt should say "nothing to undo"; a `pic=N` (no-thumbnail) reel
  should still get a working Move button; re-sharing a reel under a
  different URL shape (`/reel/` vs `/p/`) should say "already saved," not
  duplicate.
- [ ] Classification and the neighbour-assist reasoning haven't been
  stress-tested for the same kind of hallucination the summarizer once had
  (see `known-issues.md`) — nobody has specifically looked.

## The big, deliberately-undecided architectural question

- [ ] **Per-user separation.** No `user_id`/`chat_id` scoping anywhere —
  every Telegram user shares one global vault. Blocks any multi-user plan
  outright, and changes schema/corrections/neighbour-pool design depending
  on the answer. Flagged repeatedly as "decide this before building
  further" — still not decided.

## No longer applicable (kept so it isn't reintroduced by mistake)

- ~~Re-analyze frame data on reels saved before the vision-prompt fix~~ —
  moot. The whole database was cleared and is being repopulated with new
  reels as of 2026-09-02; there are no pre-fix reels left to repair.
- ~~Re-run `recondense_media.py` after the adapter audit~~ — same reason.
