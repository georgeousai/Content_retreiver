"""Rebuild media summaries from the raw text already stored.

Not part of the app, not a test — a repair. A reel keeps both halves of what
its video said: the raw transcript and frame reading, and the condensed
summaries that search actually reads. When condensing produces a bad or empty
summary, the raw half is still there, and that is the whole reason it is
stored — a summary can be redone without downloading the video again.

Written for the truncation bug (`adapters/llm.py`, `TruncatedResponse`),
which silently emptied four summaries across three reels: a reasoning model
spent its entire output budget thinking and returned nothing, and that was
recorded as "this transcript had nothing in it". Useful again any time the
condense prompt or model changes.

Only reels whose summary is missing while the raw text is present are
touched, so this is safe to run against a healthy vault: it will find
nothing. Reels the condenser legitimately emptied — Whisper's "." on a silent
clip, a hook that names nothing — look identical in the database, so they are
re-condensed too and simply come back empty again.

Re-embeds every reel it changes, through the same `embedding_text` the vault
uses: a summary the embedding never saw would be words the vault holds and no
query can reach.

Usage:

    uv run python scripts/recondense_media.py            # dry run
    uv run python scripts/recondense_media.py --apply    # write it
"""

from __future__ import annotations

import sys
from dataclasses import replace

from reel_vault.adapters.embedder import LocalEmbedder
from reel_vault.adapters.llm import ChatContentCondenser, chat_client
from reel_vault.adapters.postgres_store import PostgresReelStore
from reel_vault.config import load_config
from reel_vault.models import ProcessingStatus, SavedReel
from reel_vault.search import embedding_text_for
from reel_vault.substance import has_substance


def summary_missing(raw: str, summary: str) -> bool:
    """One half of a reel's media text whose summary went missing while the
    raw words are still there.

    The single definition of "missing" this script runs on. Selecting a reel
    and deciding which of its two halves to re-condense are the same
    question asked twice, and spelling the condition out at both sites is
    how they come to disagree — the script would then pick a reel up and
    then condense neither half of it.
    """
    return has_substance(raw) and not summary.strip()


def worth_retrying(reel: SavedReel) -> bool:
    """A summary missing beside raw text that has something in it.

    Not the same as "was damaged". A reel the condenser legitimately emptied
    - the vault's fragrance hook promises five fragrances and names none -
    looks identical in the database and matches this every time. That is why
    the caller compares the new summary against the old and writes only a
    difference: otherwise this would re-condense that reel on every run
    forever, spend a call each time, and report it as repaired.
    """
    return summary_missing(
        reel.transcript_raw, reel.transcript_summary
    ) or summary_missing(reel.frame_analysis_raw, reel.frame_analysis_summary)


def main(apply: bool) -> int:
    config = load_config()
    store = PostgresReelStore(config.database_url)
    embedder = LocalEmbedder()
    condenser = ChatContentCondenser(
        client=chat_client(config.condenser), model=config.condenser.model
    )
    print(f"condenser: {config.condenser.model} at {config.condenser.base_url}\n")

    seen: set[str] = set()
    repaired = 0
    still_empty = 0

    for collection in sorted(store.known_collections()):
        for reel in store.find_by_collection(collection):
            if reel.url in seen or not worth_retrying(reel):
                continue
            seen.add(reel.url)

            transcript_summary = reel.transcript_summary
            frame_summary = reel.frame_analysis_summary
            if summary_missing(reel.transcript_raw, transcript_summary):
                transcript_summary = condenser.condense(reel.transcript_raw)
            if summary_missing(reel.frame_analysis_raw, frame_summary):
                frame_summary = condenser.condense(reel.frame_analysis_raw)

            if (
                transcript_summary == reel.transcript_summary
                and frame_summary == reel.frame_analysis_summary
            ):
                # Condensed to nothing again, which for a hook is the right
                # answer. Nothing changed, so nothing is written.
                still_empty += 1
                continue

            print(
                f"{reel.url}\n"
                f"  transcript {len(reel.transcript_raw):5}c raw -> "
                f"{len(transcript_summary):4}c summary\n"
                f"  frames     {len(reel.frame_analysis_raw):5}c raw -> "
                f"{len(frame_summary):4}c summary"
            )
            repaired += 1

            if apply:
                read = replace(
                    reel,
                    transcript_summary=transcript_summary,
                    frame_analysis_summary=frame_summary,
                )
                # A repaired reel is no longer a failed read. Written back
                # still FAILED it stayed indistinguishable from one that
                # never got its summary, so the next run of this script
                # would pick it up again and the vault would go on
                # reporting a reel it had already fixed as broken. Only
                # FAILED is promoted, and only once nothing is missing:
                # a reel whose frames were never looked at is a different
                # statement, and stays the one it was.
                if read.processing_status is ProcessingStatus.FAILED and not (
                    worth_retrying(read)
                ):
                    read = replace(read, processing_status=ProcessingStatus.DONE)
                store.update(
                    replace(read, embedding=embedder.embed(embedding_text_for(read)))
                )

    print(
        f"\n{repaired} reel(s) {'repaired' if apply else 'would be repaired'}; "
        f"{still_empty} condensed to nothing again, which for a hook is correct."
    )
    if not apply and repaired:
        print("Dry run only — re-run with --apply to write these.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(apply="--apply" in sys.argv[1:]))
