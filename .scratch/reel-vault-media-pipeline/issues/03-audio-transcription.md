# 03 — Transcribe what the reel says

**What to build:** The words spoken in a reel become part of what the vault
knows about it. The downloaded video's audio is transcribed by a free-tier
speech-to-text adapter, and the resulting transcript flows through the
condensing and storage path built in ticket 01.

This is the ticket that lifts the ceiling the project has been documenting for
weeks: 46% of the live vault's captions are comment-bait with no real content,
and until now the vault could read nothing else.

Demoable end-to-end: save a reel whose caption says nothing, then find it with
a query that matches only what the creator said out loud.

**Blocked by:** 01 (media columns and attach-media), 02 (video download).

**Status:** ready-for-agent

- [ ] A downloaded reel's audio is transcribed to text via a swappable
      transcription adapter — the vault never names the provider.
- [ ] The transcript reaches the reel's stored raw transcript and condensed
      transcript summary.
- [ ] A reel whose content exists only in its audio becomes retrievable by a
      query matching that content.
- [ ] A transcription failure leaves the reel saved and usable on its
      caption-only data, marked failed rather than lost.
