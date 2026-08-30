# 04 — Read what the reel shows on screen

**What to build:** Text and visuals shown on screen — never spoken, never
captioned — become part of what the vault knows. Frames are sampled from the
same already-downloaded video and analyzed for on-screen text and visual
content by a free-tier vision adapter, and the result flows through the same
condensing and storage path as the transcript.

Frames are sampled at detected scene changes rather than on a fixed timer.
This is a deliberate accuracy choice for exactly the content this vault holds:
quick-cut reels whose substance is a series of on-screen text cards, where a
fixed interval can land between two cards and capture neither. A video with no
detectable scene changes still yields frames.

The number of frames analyzed per reel is bounded, so one unusually long or
choppy video cannot exhaust a free-tier quota on its own.

**Blocked by:** 03 (audio transcription) — extends the same extraction pass
over the same downloaded file.

**Status:** ready-for-agent

- [ ] Frames are sampled from the downloaded video at detected scene changes.
- [ ] A video with no detectable scene change still yields frames to analyze.
- [ ] The number of frames analyzed per reel is capped, and the frames kept
      are spread across the video rather than clustered at its start.
- [ ] Sampled frames are analyzed for on-screen text and visual content via a
      swappable vision adapter — the vault never names the provider.
- [ ] The analysis reaches the reel's stored raw frame analysis and condensed
      frame summary.
- [ ] A reel whose content appears only as on-screen text becomes retrievable
      by a query matching that content.
- [ ] Frame analysis failing does not discard a transcript that succeeded in
      the same pass.
