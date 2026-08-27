# 04 — Automatic thumbnail capture at save-time

**What to build:** Every reel saved to the vault automatically captures and durably stores a reference to its thumbnail image, so replies can later show the picture and the user can visually recognize a reel. Fully automatic — the user does nothing beyond sharing the link exactly as today.

`ExtractedPost` gains an optional `thumbnail_url`, populated by the caption-fetcher adapters (oEmbed and/or the yt-dlp fallback) when the underlying extraction exposes one. A new `ThumbnailStore` port — `store(thumbnail_url) -> str | None` — converts that URL into a durable reference at save-time; its adapter uploads the image through Telegram once and stores the returned Telegram `file_id`. The raw Instagram CDN URL is deliberately NOT what gets persisted: those URLs are signed/expiring, so storing them directly would leave old reels showing broken images months later, whereas Telegram `file_id`s don't expire and cost nothing extra.

`SavedReel` and `NeedsCollectionChoice` both gain `thumbnail_ref: str | None`, following the same "compute once, carry through" pattern already used for tags/embedding/author — a save paused awaiting a collection choice must not re-upload the thumbnail when finished via `assign_collection`.

This ticket is verifiable at the vault/model level (the reference is captured and stored correctly) even before any bot reply renders it — displaying it is ticket 05.

**Blocked by:** None — can start immediately. Touches the save path, independent of the query-answering work in 01-03.

- [ ] `ExtractedPost` carries an optional `thumbnail_url`, populated by the caption fetchers when available.
- [ ] Saving a reel whose extraction includes a thumbnail results in a `SavedReel.thumbnail_ref` populated via the `ThumbnailStore`.
- [ ] Saving a reel with no available thumbnail results in `thumbnail_ref is None`, with no call made to the thumbnail store, and the save otherwise succeeding normally.
- [ ] The persisted reference is the durable Telegram `file_id`, not the raw expiring Instagram CDN URL.
- [ ] A save that pauses on `NeedsCollectionChoice` carries `thumbnail_ref` through to the `SavedReel` produced by `assign_collection`, with no second thumbnail upload.
- [ ] Thumbnail capture failing (e.g. upload error) does not fail the whole save — the reel still saves with `thumbnail_ref is None`.
</content>
