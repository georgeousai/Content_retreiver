# 04 — Automatic thumbnail capture at save-time

**What to build:** Every reel saved to the vault automatically captures and durably stores a reference to its thumbnail image, so replies can later show the picture and the user can visually recognize a reel. Fully automatic — the user does nothing beyond sharing the link exactly as today.

`ExtractedPost` gains an optional `thumbnail_url`, populated by the caption-fetcher adapters (oEmbed and/or the yt-dlp fallback) when the underlying extraction exposes one. A new `ThumbnailStore` port — `store(thumbnail_url) -> str | None` — converts that URL into a durable reference at save-time; its adapter uploads the image through Telegram once and stores the returned Telegram `file_id`. The raw Instagram CDN URL is deliberately NOT what gets persisted: those URLs are signed/expiring, so storing them directly would leave old reels showing broken images months later, whereas Telegram `file_id`s don't expire and cost nothing extra.

`SavedReel` and `NeedsCollectionChoice` both gain `thumbnail_ref: str | None`, following the same "compute once, carry through" pattern already used for tags/embedding/author — a save paused awaiting a collection choice must not re-upload the thumbnail when finished via `assign_collection`.

This ticket is verifiable at the vault/model level (the reference is captured and stored correctly) even before any bot reply renders it — displaying it is ticket 05.

**Blocked by:** None — can start immediately. Touches the save path, independent of the query-answering work in 01-03.

- [x] `ExtractedPost` carries an optional `thumbnail_url`, populated by the caption fetchers when available.
- [x] Saving a reel whose extraction includes a thumbnail results in a `SavedReel.thumbnail_ref` populated via the `ThumbnailStore`.
- [x] Saving a reel with no available thumbnail results in `thumbnail_ref is None`, with no call made to the thumbnail store, and the save otherwise succeeding normally.
- [x] The persisted reference is the durable Telegram `file_id`, not the raw expiring Instagram CDN URL.
- [x] A save that pauses on `NeedsCollectionChoice` carries `thumbnail_ref` through to the `SavedReel` produced by `assign_collection`, with no second thumbnail upload.
- [x] Thumbnail capture failing (e.g. upload error) does not fail the whole save — the reel still saves with `thumbnail_ref is None`.

## Built differently from the spec: no `ThumbnailStore` port

Every outcome above holds, but the mechanism named here — a `ThumbnailStore`
port whose adapter uploads the image — was not what shipped, and the ticket
went on claiming it was. What exists instead: the save confirmation *is* the
upload. Telegram fetches the expiring Instagram URL server-side to render the
reply, and the `file_id` it hands back is what gets stored, via
`Vault.attach_thumbnail`. See commit `ae1bffc`.

The reason it is better: a separate `ThumbnailStore.store()` call has nowhere
to upload to except the same chat, so it would post the picture twice — once
to mint the reference and once to show the user — for a reply that already
had to send it.

The reason the spec's wording still mattered: it also asked
`NeedsCollectionChoice` to carry a `thumbnail_ref`, and the shipped version
carried the raw `thumbnail_url` across an unbounded pause instead — a save
paused overnight minted its "durable" reference from a signed URL that had
already expired, which is the one failure this whole decision existed to
prevent. Fixed by minting when the collection question is asked: that message
is now the upload, exactly as the confirmation is for a reel that needed no
question. `NeedsCollectionChoice` carries both fields, and the vault prefers
the ref.
</content>
