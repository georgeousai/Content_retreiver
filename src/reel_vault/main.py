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
    bot = build_bot(build_vault(config), config.telegram_bot_token)
    bot.run()


def build_vault(config: Config) -> Vault:
    """Every adapter this app runs on, wired to whatever configuration names.

    Public, and separate from `main`, because the bot is not the only thing
    that wants a real vault: the debugger walkthrough under `scripts/` wants
    the same one. Building its own copy is how that script came to be
    constructing a `Groq` client, importing an `adapters.groq_llm` module and
    reading a `config.groq_api_key` — three things that had all been gone for
    months without anything noticing, because nothing it duplicated was ever
    run or type-checked alongside the wiring it was a copy of.
    """
    logger.info(
        "Text model: %s at %s", config.llm.model, config.llm.base_url
    )
    llm = chat_client(config.llm)

    # The condenser gets its own client even when it is configured identically
    # to the chat one. Sharing the `llm` client would have made pointing it
    # elsewhere a code change; a second client built from its own endpoint
    # makes it an `.env` edit, which is what the rest of this file already
    # assumes about every model choice.
    logger.info(
        "Condenser model: %s at %s",
        config.condenser.model,
        config.condenser.base_url,
    )
    condenser_client = chat_client(config.condenser)

    return Vault(
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
        condenser=ChatContentCondenser(
            client=condenser_client, model=config.condenser.model
        ),
        media_extractor=_build_media_extractor(config),
    )


def _build_media_extractor(config: Config) -> MediaExtractor:
    """The video-reading pipeline, assembled from its four steps.

    With no vision endpoint configured the frames are simply not read:
    transcription is the larger half of what a video adds, and refusing to
    start the bot over an optional setting would trade a working vault for a
    complete one.

    The analyzer is left as None rather than stood in for by one that returns
    nothing. A do-nothing analyzer made an unset `VISION_API_KEY` — a
    forgotten line in an `.env` — indistinguishable from a video with no text
    on screen: every such reel was filed as fully read, and adding the key
    later would never have brought any of them back. Those reels are now
    marked `frames_unread` and can be found again.
    """
    frame_analyzer: FrameAnalyzer | None = None
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
            "on-screen text will not be read. They are recorded as "
            "'frames_unread' rather than done, so setting a key later can "
            "pick them up."
        )

    return VideoMediaExtractor(
        downloader=YtDlpVideoDownloader(),
        transcriber=AudioTranscriber(
            client=chat_client(config.transcription), model=config.transcription.model
        ),
        frame_sampler=SceneDetectFrameSampler(),
        frame_analyzer=frame_analyzer,
    )


if __name__ == "__main__":
    main()
