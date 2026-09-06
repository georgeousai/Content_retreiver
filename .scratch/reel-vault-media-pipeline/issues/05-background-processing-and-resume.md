# 05 — Process in the background, and survive a restart

**What to build:** The whole pipeline goes live for a real user. Sharing a reel
still confirms the save immediately — the download, transcription, and frame
analysis run afterwards, in the background, without holding up the reply or
blocking anything else the user does meanwhile.

This is genuinely asynchronous, unlike the thumbnail upload it is modelled on:
that one is fast enough to sit inside the save reply, and this one is not
(minutes, not seconds).

Because the work lives only in the running process, a bot restart mid-job would
otherwise leave a reel silently and permanently missing its transcript — with
no error anywhere, and nothing visible until a later answer is quietly worse
for it. So on startup the bot picks up every reel still awaiting processing and
resumes it.

**Blocked by:** 04 (frame analysis) — the last piece of the extraction pass
this ticket schedules.

**Status:** ready-for-agent

- [ ] Sharing a reel returns the save confirmation without waiting for media
      processing.
- [ ] The bot keeps handling messages while a reel is being processed.
- [ ] Media processing runs after a successful save, and not for a reel that
      was already saved.
- [ ] On startup, reels left awaiting processing by a previous run are picked
      up and processed.
- [ ] Reels already processed, or already marked failed, are not reprocessed
      on startup.
- [ ] A crash inside background processing is logged and does not take down
      the bot.
