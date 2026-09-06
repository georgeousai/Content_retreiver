# Universal Vault — pre-grill product brief

Captured 2026-08-29, before a dedicated grilling session on this vision (in a
separate chat, to keep that session's context clean). This is a strategy
snapshot, not a spec — no code exists for anything in this file yet.

For the current implementation's open technical items (the Instagram/Telegram
version that exists today), see
[`../reel-vault-query-answering/STATUS.md`](../reel-vault-query-answering/STATUS.md)
and [`../known-issues.md`](../known-issues.md).

## The expanded vision

Not "Reel Vault" (Instagram-specific) — a universal save-for-later tool.
Content saved from Instagram, TikTok, YouTube Shorts, LinkedIn posts, and
general read-it-later material (articles, blogs) that a user would otherwise
never revisit because there are hundreds of saved items and no way to
retrieve or synthesize across them.

Two surfaces:
- **Website**, for teams — media-company employees sharing a workspace/account
  on work machines, doing this as professional research.
- **Mobile app**, for everyday personal use — quick retrieval on the go.
- **Sequencing decision (agreed):** ship the website first; wrap it as a
  webview/PWA for mobile rather than building native immediately; go native
  (iOS/Android) once there's a concrete signal to justify it (a metric —
  retention, revenue, DAU — not a vague "if it picks up" feeling; the actual
  threshold is still undecided).

Started with Instagram-on-Telegram deliberately, to validate the core loop
before expanding. Question of when to add platform 2 is addressed below.

## Query taxonomy

The existing four query kinds (SINGLE / LIST / AGGREGATE / AUTHOR_FILTER)
don't cover what's actually being asked for. At least three genuinely
different answer *mechanisms* live inside what's currently lumped as
AGGREGATE:

1. **Synthesize** (exists today) — "what have my reels said about X, grouped
   by creator." Narrative prose across many sources.
2. **Compare / rank** (new) — "the best bicep workout plan," "the easiest way
   to make chicken salad." Requires picking a winner by some criterion, which
   may be ambiguous (best = most effective? fewest steps?) and may need a
   clarifying question back to the user — a new interaction pattern; the bot
   currently only asks clarifying questions at save time, never at query time.
3. **Extract / compile** (new) — "the list of all AI interview questions
   across my reels." Pull a specific structured thing out of many sources and
   merge/dedupe it. Output is a clean list, not a paragraph — a different
   shape than synthesis.

Also named, not yet scoped in or out: constraint queries ("under 30 seconds,"
needs metadata not currently captured), exclusion queries ("not about
crypto"), multi-turn refinement ("no, just the vegetarian ones" — needs
conversation state; `ask()` is stateless per call today).

**Open for the grill session:** do compare/rank and extract/compile become
distinct query kinds with distinct prompts/output shapes, or stay inferred
within one kind? (Leaving it inferred is exactly the kind of implicit
behavior that already failed once this session — the classifier bridging an
unstated connection in the personal-brand hallucination.)

Even the *simplest* existing kind (SINGLE) has a real dependency on
transcription: a fuzzy-recall query ("the one from that creator about $0 to
$60K") fails if the number is only spoken, never captioned. Transcription
isn't only unlocking new query kinds — it also fixes correctness of the one
that already exists.

## Monetization / tiering

**Confirmed 3-tier processing ladder:**
- **Free** — caption + collection/sub-collection/tags only. No transcription
  at all (not even the selective subset described below) — confirmed
  deliberately, on cost-at-scale grounds (100-200K users makes blanket
  transcription a real infrastructure line item; caption/taxonomy retrieval
  does not scale the same way).
- **Medium** — adds audio transcription.
- **Pro** — adds audio-visual (a materially different, pricier pipeline than
  audio-only — not a toggle on the same one).

**Compare/rank and extract/compile query types are gated behind a paid tier**
(mirrors the reasoning above: these are LLM-reasoning-heavy, expensive if
opened to everyone).

**Open question, not yet resolved:** are content-processing tier (Free/
Medium/Pro above) and query-complexity tier (retrieval vs. compare/extract)
the *same* ladder, or two independent axes? E.g., can a Medium user (has
transcripts) ask a compare/rank query, or is compare/rank Pro-only
regardless of what content backs it? If independent, the entitlement model
needs to be a capability matrix (a set of flags), not a single tier enum.

**Free-tier upsell mechanism (agreed in principle):** when a free user's
query would benefit from content that isn't there (thin caption, no
transcript), tell them explicitly — not a silent degraded answer. Reuses the
thin-caption detector already built (see "Selective transcription" below).
**Open:** does this nudge fire at save time (every thin-caption reel — given
46% of the test vault qualifies, this would be near-constant) or at query
time (only when a query actually needed the missing content)? Leaning
query-time, not yet decided.

**Comp/admin accounts** (all features, chosen by the product owner) — agreed
this needs a mechanism; an entitlement flag on the account, not a separate
code path.

## Transcription architecture

**Eager, not lazy.** Transcription begins immediately when a link is shared,
not deferred until a query needs it. (This may also be forced by the same
constraint that already applied to thumbnails: the source video URL expires,
so the content may need to be captured promptly regardless of processing
timing.)

**Selective, not blanket — reuses existing data.** A scan this session found
46% of the test vault's captions are comment-bait with no real content
("comment HABITS for my list"). That's not just diagnostic — it's a
targeting signal: transcribe the thin-caption reels, skip the substantive
ones. Originally framed as a free-tier cost reducer; superseded by the
decision that free tier gets zero transcription, so this now applies as a
**prioritization mechanism within paid tiers** — which reels get transcribed
first (or at all, if a tier has a capped budget) rather than a free-tier
cost lever.

**Storage — hot/cold split (agreed):**
- Paid tiers: raw transcript kept in cheap long-term/cold storage; a compact,
  topic-relevant summary kept in the fast/indexed path (Postgres) for actual
  retrieval — keeps the DB small and retrieval fast.
- If a user is unsatisfied with a summary, it can be regenerated from the
  cold-stored raw transcript rather than re-transcribing from scratch.
- This resolves a risk flagged mid-session: compact-only storage with no raw
  backup would make the ingestion-time summarization a one-shot operation —
  anything it drops is unrecoverable once the source URL expires. The hot/
  cold split gives paid tiers a safety net; free tier never has this risk
  since it has no transcription at all.
- Not free: cold storage is categorically cheaper than a hot indexed column,
  but still a real, uncosted line item.

**Model tier:** audio-only transcription is the default paid capability;
full audio-visual (frame/OCR-level) understanding is a distinctly pricier,
separate pipeline reserved for the top tier — not a variant of the same job.

## Citations

Clarified: "citation" means the reel's own link, shown alongside a
recommendation — not a quoted excerpt from the transcript. Simpler to build
than originally assumed.

## Multi-user

Agreed in principle: the account model needs both **ownership scope** (whose
vault is this — personal vs. shared/team space, still to be decided in
detail) and **tier/entitlement** (what can this account do). Tiering
sharpens this further — it's not only a data-scoping question anymore, it's
also an entitlement question, so the account model was already going to need
this shape regardless.

Deferred for the grill session itself — this was flagged as the single
highest-leverage undecided item across the whole conversation.

## Platform scope

Confirmed vision always included Instagram + TikTok + YouTube Shorts +
LinkedIn + general read-later content; Instagram-on-Telegram was a
deliberate first slice to validate the core loop, not the entire plan.

**Open question raised, with a recommendation (not yet a decision):**
whether Instagram needs to be "done" before adding platform 2, build all
platforms in parallel, or go one at a time. Recommendation: reframe from "is
Instagram perfected" to "is the *shared core* solid" — classification,
search, correction, and summarization are already platform-agnostic in the
`Vault`/ports architecture; what's platform-specific is just URL parsing and
extraction. This session alone found and fixed a URL-matching bug, a search
blind spot, a classification bias, and a summarizer hallucination — all in
the shared core. Every one of those would be inherited by every future
platform the instant it's added. Suggested bar before platform 2: multi-user
shipped, structured answers landed, transcription live and cost-validated —
then go platform-by-platform, not in parallel. Not yet agreed by the user.

## Legal / ToS — RESOLVED: the current transcription design is not viable as specced

Full findings, every claim cited to an official primary source with exact
URL and quoted clause: [`tos-research.md`](tos-research.md).

**All three platforms explicitly prohibit the download-and-transcribe
architecture described in this brief.** Not silence, not ambiguity on the
core question — named, specific "you must not download/cache/store...
without written approval" language on every platform:

- **Instagram/Meta** — Terms of Use + a dedicated Automated Data Collection
  Terms document bar automated download without Meta's express written
  permission; even where granted, permitted uses are limited to search
  indexing/link previews, with no transcription/summarization category. The
  official Graph API has no endpoint to fetch an arbitrary other user's
  Reel at all — access is scoped to the authorizing account's own content.
- **TikTok** — Terms of Service + Developer Terms bar scraping/automated
  extraction without prior written permission. The one API broad enough to
  read others' content (Research API) is contractually restricted to
  non-profit academic researchers; commercial users are explicitly
  ineligible.
- **YouTube** — the most explicit of the three. YouTube API Services
  Developer Policies state outright that apps "must not download, import,
  backup, cache, or store copies of YouTube audiovisual content without
  YouTube's prior written approval," with a hard 30-day cap on any stored
  API data regardless. `captions.download` requires the video's own
  channel owner's authorization, so it isn't a workaround for other
  creators' content either.

**This directly invalidates the transcription architecture as designed** —
eager download at save time, hot/cold transcript storage, the whole Medium/
Pro tier structure built on "we transcribe the audio." That plan assumed the
download step was legally available and only the cost/storage shape needed
deciding. It isn't available, on any of the three platforms, at any paid
API tier.

**Two narrower points remain genuinely ambiguous** (need actual legal
counsel, not resolved by reading): whether an AI-generated summary/
transcript counts as restricted "derived data" once created, and how
broadly TikTok's "commercial purpose" restriction should be read. Neither
matters until/unless the download step itself is resolved some other way.

**Paths not foreclosed by this research** (each has its own tradeoffs, none
evaluated yet):
- A user manually uploading their own already-downloaded file, rather than
  the product fetching it from the source platform on their behalf
- Direct partnership/licensing agreements with a platform
- A licensed third-party data provider
- Staying caption/metadata-only (the current implementation's actual
  approach) and accepting the ceiling that comes with it, rather than
  building a transcription pipeline at all

**This is now the top item for the grill session** — it changes the shape
of the product's core differentiator, not a peripheral detail.

## Still open / unresolved going into the grill session

- Multi-user account model, in detail (ownership scope shape, team spaces)
- Free-tier nudge timing (save-time vs. query-time)
- Whether processing tier and query-complexity tier are one ladder or two
  independent axes
- Whether compare/rank and extract/compile become distinct query kinds
- Platform-2 timing bar (recommendation given, not agreed)
- Async UX for slow answers — not addressed this conversation. Now
  secondary: if transcription isn't viable as designed, the thing it was
  deferring (a slow eager-processing step) may not exist in its current
  form either.
- **Which of the four "paths not foreclosed" (above) to pursue, if any** —
  the single highest-priority open question now, since it determines
  whether Medium/Pro tiers, hot/cold transcript storage, and the
  compare/rank and extract/compile query types have any content to run on
  at all.
