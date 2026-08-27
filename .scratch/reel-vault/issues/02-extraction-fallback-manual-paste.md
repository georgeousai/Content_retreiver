# 02 — Extraction fallback & manual-paste recovery

**What to build:** When Instagram's oEmbed endpoint fails or returns an empty/truncated caption, the app falls back to an unofficial scraper (e.g. yt-dlp) to obtain the caption text (caption only — no video/audio download). If the scraper also fails to produce a usable caption, the bot tells the user extraction failed and asks them to paste the caption manually; the manually pasted caption then flows through the same tagging/embedding/storage path (`save_reel`'s downstream steps) as a normally extracted caption, including the existing duplicate check from Ticket 01.

**Blocked by:** 01 — needs the `save_reel` seam, extraction-adapter boundary, and bot reply mechanism.

**Status:** ready-for-agent

- [ ] If oEmbed returns no caption or a clearly truncated one, the scraper fallback is attempted automatically before giving up.
- [ ] If the scraper also fails to produce a caption, the bot replies asking the user to paste the caption text manually, rather than saving an empty/untagged entry.
- [ ] A manually pasted caption is tagged, embedded, and stored the same way an extracted caption would be, including the duplicate-URL check.
- [ ] No video or audio is downloaded at any point in the fallback chain — only caption text is ever extracted.
