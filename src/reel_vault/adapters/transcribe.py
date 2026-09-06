"""Speech-to-text for a downloaded reel.

One call to `/audio/transcriptions` — the same OpenAI-compatible shape the
chat adapters use, so which provider hears the reel is a base URL, a key and
a model name, not a code path.

The downloaded mp4 is handed over whole rather than having its audio split
out first. The endpoint accepts mp4 directly, so a separate extraction step
would buy nothing and would put ffmpeg — a system binary, not a Python
dependency — between a saved reel and its transcript.

**Whisper invents speech for videos that have none.** A reel with only
background music comes back with a confident-looking sentence that was never
said: measured on this vault, a silent chakna recipe transcribed as
"Sous-titrage Société Radio-Canada" (a caption-credit line memorised from
training data) and a silent sandwich video as "I'm going to go to the next
video." Nothing downstream can tell those from real speech — they are
well-formed sentences, so `substance.has_substance` passes them, and only the
condenser's own judgement happened to throw them away. That is two layers
deep and working by luck.

The API already reports how sure it was, per segment, and the app was
discarding it. Asking for `verbose_json` and reading it back is the fix.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from openai import BadRequestError, OpenAI

logger = logging.getLogger(__name__)

# Providers reject an oversized upload outright. A reel that large is not a
# reel; saying so in the log beats an opaque API error.
MAX_UPLOAD_BYTES = 24 * 1024 * 1024

# Measured on six real reels, 2026-09-06, `whisper-large-v3-turbo`:
#
#   reel                mean logprob   chars/sec   what it was
#   chakna                    -0.922        0.68   hallucinated
#   sandwich                  -1.374        1.14   hallucinated
#   Hinglish workout          -0.509       11.90   real, badly transcribed
#   narrated workout          -0.134       21.58   real
#   ramen restaurant          -0.107       20.48   real
#   pants combinations        -0.131       17.70   real
#
# Both thresholds sit in the gap, and a transcript must fall below BOTH to be
# discarded — see `_is_hallucinated` for why that conjunction matters.
MIN_MEAN_LOGPROB = -0.7
MIN_CHARS_PER_SECOND = 4.0


class AudioTranscriber:
    def __init__(self, *, client: OpenAI, model: str) -> None:
        self._client = client
        self._model = model
        # Discovered on first use, like `reasoning_effort` in the chat
        # adapter: whether a provider serves `verbose_json` is a fact about
        # the endpoint, and one wasted request per process is cheaper than
        # asking the operator to know it.
        self._verbose_unsupported = False

    def transcribe(self, media_path: Path) -> str:
        size = media_path.stat().st_size
        if size > MAX_UPLOAD_BYTES:
            logger.info(
                "Skipping transcription of %s: %d bytes exceeds the upload limit",
                media_path.name,
                size,
            )
            return ""

        response = self._request(media_path)
        text = (getattr(response, "text", "") or "").strip()
        if not text:
            return ""

        if _is_hallucinated(response, text):
            logger.info(
                "Discarding the transcript of %s: the model was unsure and said "
                "almost nothing for the length of the audio, which is what it "
                "does with music and no speech (%r)",
                media_path.name,
                text[:80],
            )
            return ""
        return text

    def _request(self, media_path: Path) -> Any:
        """The transcription itself, asking for the confidence data unless
        this provider has already refused it."""
        with media_path.open("rb") as media:
            payload = media.read()

        if self._verbose_unsupported:
            return self._create(media_path.name, payload, verbose=False)
        try:
            return self._create(media_path.name, payload, verbose=True)
        except BadRequestError:
            # Not every provider serves `verbose_json`. Losing the gate is
            # worse than nothing but far better than losing transcription.
            logger.info(
                "%s does not accept verbose_json; transcribing without the "
                "confidence data, and without the hallucination gate that "
                "reads it",
                self._model,
            )
            self._verbose_unsupported = True
            return self._create(media_path.name, payload, verbose=False)

    def _create(self, name: str, payload: bytes, *, verbose: bool) -> Any:
        """Two spelled-out calls rather than one with an unpacked dict: the
        SDK types `response_format` as a literal and picks its return type
        from it, so a `dict[str, str]` splatted in matches no overload."""
        if verbose:
            return self._client.audio.transcriptions.create(
                file=(name, payload),
                model=self._model,
                response_format="verbose_json",
            )
        return self._client.audio.transcriptions.create(
            file=(name, payload), model=self._model
        )


def _is_hallucinated(response: Any, text: str) -> bool:
    """Whether this looks like speech invented for audio that had none.

    Two signals, and **both** must fire, because each alone is wrong in a
    way the other covers:

    - **How sure the model was.** Real speech scores around -0.13; the two
      known hallucinations scored -0.92 and -1.37. But this number is not
      stable: the same Hinglish reel measured -0.509 on one run and -0.677 on
      another. A threshold thin enough to catch every hallucination on its
      own would eventually catch a badly-transcribed real reel on a bad run.

    - **How much was said, per second of audio.** This is the stronger
      signal and the more stable one: hallucinations produce one stock phrase
      stretched over a whole minute (0.68 and 1.14 characters per second),
      while the *worst* real transcript in the vault still ran at 11.90 — a
      tenfold gap, against the 0.41 that separates them on confidence.

    Requiring both means a real reel has to fail on two independent counts
    before its words are thrown away, and the vault's one badly-transcribed
    real reel clears each of them with room to spare.

    **Known blind spots**, stated rather than discovered later:

    - A genuinely sparse reel — one short sentence in a minute of silence —
      is low on both counts and would be discarded. `transcript_raw` is
      never written for a discarded transcript, so unlike a bad summary this
      is not recoverable without re-downloading. No such reel exists in the
      vault today; if one turns up, density is the threshold to revisit.
    - Whisper's *other* hallucination mode — repeating one phrase dozens of
      times — is dense, so this passes it through. `compression_ratio` in the
      same response is the signal for that one, unread here because no reel
      in this vault has done it.
    - A provider that cannot serve `verbose_json` gets no gate at all.
    """
    duration = _as_float(getattr(response, "duration", None))
    segments = getattr(response, "segments", None) or []

    logprobs = [
        value
        for value in (_segment_logprob(segment) for segment in segments)
        if value is not None
    ]
    # Missing either signal means the provider did not give enough to judge
    # on. Keeping the words is the answer then: this gate exists to remove
    # text that was never spoken, not to remove text it cannot measure.
    if not logprobs or duration <= 0:
        return False

    mean_logprob = sum(logprobs) / len(logprobs)
    density = len(text) / duration
    return mean_logprob < MIN_MEAN_LOGPROB and density < MIN_CHARS_PER_SECOND


def _segment_logprob(segment: Any) -> float | None:
    """One segment's average log-probability, from either shape the SDK
    hands back — a model object on the typed path, a plain dict when a
    provider returns fields the SDK does not model.

    `None` for a segment that carries no score, and deliberately not 0.0:
    zero is the top of this scale, so a missing value coerced to it would
    read as perfect confidence and keep exactly the transcripts this is
    meant to weigh.
    """
    value = (
        segment.get("avg_logprob")
        if isinstance(segment, dict)
        else getattr(segment, "avg_logprob", None)
    )
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
