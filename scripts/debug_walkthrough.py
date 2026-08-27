"""Step-through walkthrough of the real save_reel/ask pipeline for learning
purposes. Not part of the app, not a test — a debugger target.

Uses the exact same adapters as `main.py` (real Groq, real local embedder,
real Postgres), just called directly instead of via the Telegram bot, so you
can set breakpoints and step through without a live chat round-trip.

Run this under the VS Code debugger (see .vscode/launch.json), not with
`uv run` directly, or you'll just see it finish with no chance to inspect
anything.
"""

from __future__ import annotations

from groq import Groq

from reel_vault.adapters.caption import (
    CompositeCaptionFetcher,
    OEmbedCaptionFetcher,
    YtDlpCaptionFetcher,
)
from reel_vault.adapters.embedder import LocalEmbedder
from reel_vault.adapters.groq_llm import (
    GroqCollectionAssigner,
    GroqQueryIntent,
    GroqSummarizer,
    GroqTagger,
)
from reel_vault.adapters.postgres_store import PostgresReelStore
from reel_vault.config import load_config
from reel_vault.vault import Vault


def main() -> None:
    config = load_config()
    groq_client = Groq(api_key=config.groq_api_key)

    # --- Step 1: build the vault -------------------------------------------
    # Breakpoint here to see each real adapter get constructed.
    vault = Vault(
        caption_fetcher=CompositeCaptionFetcher(
            [OEmbedCaptionFetcher(), YtDlpCaptionFetcher()]
        ),
        tagger=GroqTagger(client=groq_client),
        collection_assigner=GroqCollectionAssigner(client=groq_client),
        embedder=LocalEmbedder(),
        store=PostgresReelStore(config.database_url),
        query_intent=GroqQueryIntent(client=groq_client),
        summarizer=GroqSummarizer(client=groq_client),
    )

    # --- Step 2: save a reel -------------------------------------------------
    url = input("Paste an Instagram Reel URL to save (or press Enter to skip): ").strip()
    if url:
        # Breakpoint here, then Step Into (F11) to follow save_reel() itself.
        result = vault.save_reel(url)
        print(f"\nsave_reel result: {type(result).__name__}")
        print(result)

    # --- Step 3: ask a question ----------------------------------------------
    query = input("\nAsk a question about your saved reels (or press Enter to skip): ").strip()
    if query:
        # Breakpoint here, then Step Into (F11) to follow ask() itself.
        answer = vault.ask(query)
        print(f"\nask result: {type(answer).__name__}")
        print(answer)


if __name__ == "__main__":
    main()
