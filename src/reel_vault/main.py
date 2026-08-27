"""Process entrypoint: wires real adapters into `Vault` and runs the Telegram
bot via long-polling."""

from __future__ import annotations

import logging

from groq import Groq

from reel_vault.adapters.caption import (
    CompositeCaptionFetcher,
    OEmbedCaptionFetcher,
    YtDlpCaptionFetcher,
)
from reel_vault.adapters.embedder import LocalEmbedder
from reel_vault.adapters.groq_llm import GroqQueryIntent, GroqSummarizer, GroqTagger
from reel_vault.adapters.postgres_store import PostgresReelStore
from reel_vault.bot import build_bot
from reel_vault.config import load_config
from reel_vault.vault import Vault


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    config = load_config()

    groq_client = Groq(api_key=config.groq_api_key)

    vault = Vault(
        caption_fetcher=CompositeCaptionFetcher(
            [OEmbedCaptionFetcher(), YtDlpCaptionFetcher()]
        ),
        tagger=GroqTagger(client=groq_client),
        embedder=LocalEmbedder(),
        store=PostgresReelStore(config.database_url),
        query_intent=GroqQueryIntent(client=groq_client),
        summarizer=GroqSummarizer(client=groq_client),
    )

    bot = build_bot(vault, config.telegram_bot_token)
    bot.run()


if __name__ == "__main__":
    main()
