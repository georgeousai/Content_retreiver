"""Re-embed every saved reel under the current `embedding_text` ordering.

Not part of the app, not a test — a one-time migration. `embedding` is
stored, not recomputed on read, so a reel saved before an `embedding_text`
change keeps describing itself the old way until something re-embeds it —
today that only happens on a move or on the reel's video being read. This
script is the other path: it walks every saved reel and rewrites its
embedding from its own current columns, with no other field touched.

Idempotent and safe to re-run: two runs back to back produce the same
embeddings, since `embedding_text` is a pure function of columns already in
the row. Nothing here calls a model or downloads anything.

Reads through the same two public `ReelStore` methods the app already uses
elsewhere (`known_collections`, `find_by_collection`) rather than adding a
new "list everything" method to the port for what is a one-off script.

Usage:

    uv run python scripts/backfill_embeddings.py            # dry run
    uv run python scripts/backfill_embeddings.py --apply    # write it
"""

from __future__ import annotations

import sys
from dataclasses import replace

from reel_vault.adapters.embedder import LocalEmbedder
from reel_vault.adapters.postgres_store import PostgresReelStore
from reel_vault.config import load_config
from reel_vault.search import embedding_text_for


def main(apply: bool) -> int:
    config = load_config()
    store = PostgresReelStore(config.database_url)
    embedder = LocalEmbedder()

    seen: set[str] = set()
    changed = 0
    unchanged = 0

    for collection in sorted(store.known_collections()):
        for reel in store.find_by_collection(collection):
            if reel.url in seen:
                continue
            seen.add(reel.url)

            # Through the same one function the vault embeds with. Spelled
            # out here instead, this script would go on embedding reels the
            # way it was written to and the vault would embed new ones the
            # way it does now, the moment a field is added to either.
            new_embedding = embedder.embed(embedding_text_for(reel))

            if new_embedding == reel.embedding:
                unchanged += 1
                continue

            changed += 1
            has_media = bool(
                (reel.transcript_summary or "").strip()
                or (reel.frame_analysis_summary or "").strip()
            )
            print(
                f"{'would re-embed' if not apply else 're-embedded'}: "
                f"{reel.url} (media summaries: {has_media})"
            )
            if apply:
                store.update(replace(reel, embedding=new_embedding))

    print(
        f"\n{len(seen)} reels seen, {changed} {'changed' if apply else 'would change'}, "
        f"{unchanged} already current."
    )
    if not apply and changed:
        print("Dry run only — re-run with --apply to write these.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(apply="--apply" in sys.argv[1:]))
