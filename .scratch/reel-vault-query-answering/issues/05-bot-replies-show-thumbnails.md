# 05 — Bot replies show reel thumbnails

**What to build:** Every bot reply that shows the user a reel — single-item, list, or aggregate — displays that reel's thumbnail picture alongside the existing link/collection/tags text, so the user can visually recognize the reel they're looking for and tap through to it.

Uses the durable `thumbnail_ref` (Telegram `file_id`) captured at save-time in ticket 04: the bot re-sends by `file_id` rather than re-fetching any image, which is instant, free, and never goes stale. Reels saved before this feature existed (or whose thumbnail capture failed) have no `thumbnail_ref` and must still render correctly as text-only replies.

**Blocked by:** 01 (list reply formatting), 03 (aggregate reply formatting + matched links), 04 (`thumbnail_ref` must exist to render).

- [x] A `SingleItemAnswer` reply shows the reel's thumbnail alongside its link/collection/tags.
- [x] A `ListAnswer` reply shows each matched reel's thumbnail alongside its link.
- [x] An `AggregateAnswer` reply shows the synthesized text plus the matched reels with their thumbnails.
- [x] A reel with no `thumbnail_ref` (older save, or failed capture) renders as today's text-only reply without erroring.
- [x] Thumbnails are rendered by re-sending the stored Telegram `file_id` — no re-fetch of the original Instagram image at reply time.
</content>
