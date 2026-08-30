"""Process entrypoint: wires real adapters into `Vault` and runs the Telegram
bot via long-polling.

This is the only module that decides which concrete thing sits behind each
port — and even here the choice is read from configuration rather than
written down, so switching model provider is an `.env` edit.
"""

from __future__ import annotations

import logging

from reel_vault.adapters.caption import (
    CompositeCaptionFetcher,
    OEmbedCaptionFetcher,
    YtDlpCaptionFetcher,
)
from reel_vault.adapters.embedder import LocalEmbedder
from reel_vault.adapters.llm import (
    ChatCollectionAssigner,
    ChatComparer,
    ChatContentCondenser,
    ChatItemExtractor,
    ChatQueryIntent,
    ChatSummarizer,
    ChatTagger,
    chat_client,
)
from reel_vault.adapters.media import (
    FrameAnalyzer,
    SceneDetectFrameSampler,
    VideoMediaExtractor,
    YtDlpVideoDownloader,
)
from reel_vault.adapters.postgres_store import PostgresReelStore
from reel_vault.adapters.transcribe import AudioTranscriber
from reel_vault.adapters.vision import VisionFrameAnalyzer
from reel_vault.bot import build_bot
from reel_vault.config import Config, load_config
from reel_vault.ports import MediaExtractor
from reel_vault.vault import Vault

logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    config = load_config()

    logger.info(
        "Text model: %s at %s", config.llm.model, config.llm.base_url
    )
    llm = chat_client(config.llm)

    vault = Vault(
        caption_fetcher=CompositeCaptionFetcher(
            [OEmbedCaptionFetcher(), YtDlpCaptionFetcher()]
        ),
        tagger=ChatTagger(client=llm, model=config.llm.model),
        collection_assigner=ChatCollectionAssigner(client=llm, model=config.llm.model),
        embedder=LocalEmbedder(),
        store=PostgresReelStore(config.database_url),
        query_intent=ChatQueryIntent(client=llm, model=config.llm.model),
        summarizer=ChatSummarizer(client=llm, model=config.llm.model),
        comparer=ChatComparer(client=llm, model=config.llm.model),
        item_extractor=ChatItemExtractor(client=llm, model=config.llm.model),
        condenser=ChatContentCondenser(client=llm, model=config.llm.model),
        media_extractor=_build_media_extractor(config),
    )

    bot = build_bot(vault, config.telegram_bot_token)
    bot.run()


def _build_media_extractor(config: Config) -> MediaExtractor:
    """The video-reading pipeline, assembled from its four steps.

    With no vision endpoint configured the frames are simply not read:
    transcription is the larger half of what a video adds, and refusing to
    start the bot over an optional setting would trade a working vault for a
    complete one.
    """
    frame_analyzer: FrameAnalyzer
    if config.vision is not None:
        logger.info(
            "Vision model: %s at %s", config.vision.model, config.vision.base_url
        )
        frame_analyzer = VisionFrameAnalyzer(
            client=chat_client(config.vision), model=config.vision.model
        )
    else:
        logger.warning(
            "No VISION_API_KEY is set — reels will be transcribed, but "
            "on-screen text will not be read."
        )
        frame_analyzer = _NoFrameAnalysis()

    return VideoMediaExtractor(
        downloader=YtDlpVideoDownloader(),
        transcriber=AudioTranscriber(
            client=chat_client(config.transcription), model=config.transcription.model
        ),
        frame_sampler=SceneDetectFrameSampler(),
        frame_analyzer=frame_analyzer,
    )


class _NoFrameAnalysis:
    """Stands in when no vision endpoint is configured. Returning nothing is
    already how the pipeline reports "the frames could not be read", so this
    needs no special handling anywhere downstream."""

    def analyze(self, frames: list[bytes]) -> str:
        return ""


if __name__ == "__main__":
    main()
