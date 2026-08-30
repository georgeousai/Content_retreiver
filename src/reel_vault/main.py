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
from reel_vault.adapters.groq_llm import (
    GroqCollectionAssigner,
    GroqComparer,
    GroqContentCondenser,
    GroqItemExtractor,
    GroqQueryIntent,
    GroqSummarizer,
    GroqTagger,
)
from reel_vault.adapters.media import (
    FrameAnalyzer,
    SceneDetectFrameSampler,
    VideoMediaExtractor,
    YtDlpVideoDownloader,
)
from reel_vault.adapters.postgres_store import PostgresReelStore
from reel_vault.adapters.transcribe import GroqTranscriber
from reel_vault.adapters.vision import GeminiFrameAnalyzer
from reel_vault.bot import build_bot
from reel_vault.config import Config, load_config
from reel_vault.ports import MediaExtractor
from reel_vault.vault import Vault

logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    config = load_config()

    groq_client = Groq(api_key=config.groq_api_key)

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
        comparer=GroqComparer(client=groq_client),
        item_extractor=GroqItemExtractor(client=groq_client),
        media_extractor=_build_media_extractor(config, groq_client),
        condenser=GroqContentCondenser(client=groq_client),
    )

    bot = build_bot(vault, config.telegram_bot_token)
    bot.run()


def _build_media_extractor(config: Config, groq_client: Groq) -> MediaExtractor:
    """The video-reading pipeline, assembled from its four steps.

    Without a Gemini key the frames are simply not read: transcription is the
    larger half of what a video adds, and refusing to start the bot over a
    missing optional key would trade a working vault for a complete one.
    """
    frame_analyzer: FrameAnalyzer
    if config.gemini_api_key:
        frame_analyzer = GeminiFrameAnalyzer(config.gemini_api_key)
    else:
        logger.warning(
            "GEMINI_API_KEY is not set — reels will be transcribed, but "
            "on-screen text will not be read."
        )
        frame_analyzer = _NoFrameAnalysis()

    return VideoMediaExtractor(
        downloader=YtDlpVideoDownloader(),
        transcriber=GroqTranscriber(client=groq_client),
        frame_sampler=SceneDetectFrameSampler(),
        frame_analyzer=frame_analyzer,
    )


class _NoFrameAnalysis:
    """Stands in when no vision key is configured. Returning nothing is
    already how the pipeline reports "the frames could not be read", so this
    needs no special handling anywhere downstream."""

    def analyze(self, frames: list[bytes]) -> str:
        return ""


if __name__ == "__main__":
    main()
