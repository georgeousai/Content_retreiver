# 02 — Download the video, and always clean it up

**What to build:** Given a reel URL, the actual video file is downloaded to a
temporary location so audio and frames can be taken from it. Today `yt-dlp` is
deliberately metadata-only; this turns on a real download, used solely by the
background media pipeline and never by the save-time caption fetch (a save
must stay as fast as it is now).

The file is temporary in the strict sense: whether the processing that follows
succeeds, fails, or raises, the downloaded file is gone afterwards. Disk usage
must not grow with the size of the vault — the project's "no stored media"
decision survives intact, since nothing durable is ever written.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] A reel URL yields a downloaded video file on local disk.
- [ ] The file is removed after processing completes successfully.
- [ ] The file is removed even when the processing that follows it raises.
- [ ] A download failure is reported as "no media available" rather than
      raising into the caller.
- [ ] The save-time caption path still performs no download.
