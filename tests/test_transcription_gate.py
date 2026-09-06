"""Whisper invents speech for videos that have none, and the gate that stops it.

Two real examples from the live vault, both music-only videos with nobody
talking:

    "... ... Sous-titrage Société Radio-Canada"   (a silent chakna recipe)
    "I'm going to go to the next video."          (a silent sandwich video)

Neither was said. The first is a caption-credit line Whisper memorised from
training data; the second is the shape of thing it produces over silence.
Both are well-formed sentences, so `substance.has_substance` passes them
straight through, and both were only discarded because the condenser
happened to judge them worthless. That is a guard two layers downstream,
working by luck.

The numbers below are measured, 2026-09-06, `whisper-large-v3-turbo`, on the
six reels the vault had at the time. They are pinned here because the two
thresholds in `transcribe.py` mean nothing without them:

    reel                mean logprob   chars/sec   what it was
    chakna                    -0.922        0.68   hallucinated
    sandwich                  -1.374        1.14   hallucinated
    Hinglish workout          -0.509       11.90   real, badly transcribed
    narrated workout          -0.134       21.58   real
    ramen restaurant          -0.107       20.48   real
    pants combinations        -0.131       17.70   real

The Hinglish reel is the one that makes this hard. Whisper mangled it, but
"5 sets", "biceps" and "5 kg dumbbells" really are in the audio, so throwing
it away is the expensive mistake — and it is the reel closest to the line on
confidence. It survives because the gate also asks how *much* was said, and
on that count it is nowhere near the hallucinations.

Hermetic: a stub client returns the shapes a real provider returns. No audio,
no network, no key.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from openai import BadRequestError

from reel_vault.adapters.transcribe import (
    MIN_CHARS_PER_SECOND,
    MIN_MEAN_LOGPROB,
    AudioTranscriber,
)

# Verbatim from the live vault. Lengths matter -- they are half of what the
# gate measures -- so these are the real strings, not stand-ins.
CHAKNA_HALLUCINATION = "... ... Sous-titrage Société Radio-Canada"
SANDWICH_HALLUCINATION = "I'm going to go to the next video."


class _Segment:
    def __init__(self, avg_logprob: float | None) -> None:
        if avg_logprob is not None:
            self.avg_logprob = avg_logprob


class _Response:
    def __init__(self, text: str, duration: float, logprobs: list[float | None]) -> None:
        self.text = text
        self.duration = duration
        self.segments = [_Segment(value) for value in logprobs]


class _StubClient:
    """The one call these adapters make, and a record of how it was asked."""

    def __init__(self, response: Any) -> None:
        self._response = response
        self.calls: list[dict[str, Any]] = []
        self.audio = self
        self.transcriptions = self

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self._response


def _transcriber(client: Any) -> AudioTranscriber:
    return AudioTranscriber(
        client=client,  # type: ignore[arg-type]
        model="test-model",
    )


def _audio(tmp_path: Path) -> Path:
    """A file the size check will accept. Its bytes never reach a model."""
    path = tmp_path / "reel.mp4"
    path.write_bytes(b"not really an mp4")
    return path


# --- the mistake that keeps invented speech ----------------------------------


@pytest.mark.parametrize(
    "name, text, duration, logprob",
    [
        ("chakna (live vault)", CHAKNA_HALLUCINATION, 60.3, -0.922),
        ("sandwich (live vault)", SANDWICH_HALLUCINATION, 29.8, -1.374),
    ],
)
def test_invented_speech_is_discarded(
    tmp_path: Path, name: str, text: str, duration: float, logprob: float
) -> None:
    """Both real hallucinations, with the numbers they actually measured."""
    client = _StubClient(_Response(text, duration, [logprob]))

    assert _transcriber(client).transcribe(_audio(tmp_path)) == "", name


# --- the mistake that costs real content -------------------------------------


@pytest.mark.parametrize(
    "name, chars, duration, logprob",
    [
        ("Hinglish workout, badly transcribed", 365, 30.7, -0.509),
        ("narrated workout", 1644, 76.2, -0.134),
        ("ramen restaurant", 961, 46.9, -0.107),
        ("pants combinations", 367, 20.7, -0.131),
    ],
)
def test_real_speech_survives(
    tmp_path: Path, name: str, chars: int, duration: float, logprob: float
) -> None:
    """The half that matters. The Hinglish reel is the close one -- it is
    genuinely hard to transcribe, and the gate has to keep it anyway."""
    text = "x" * chars
    client = _StubClient(_Response(text, duration, [logprob]))

    assert _transcriber(client).transcribe(_audio(tmp_path)) == text, name


def test_low_confidence_alone_does_not_discard(tmp_path: Path) -> None:
    """The conjunction, from the side that protects real content.

    A reel can be hard to transcribe and still be full of speech. Confidence
    drifts between runs on identical audio -- the Hinglish reel measured
    -0.509 once and -0.677 another time -- so a gate that emptied on
    confidence alone would eventually throw away a real transcript for
    having had a bad run.
    """
    text = "x" * 900
    client = _StubClient(_Response(text, 45.0, [-1.4]))

    assert _transcriber(client).transcribe(_audio(tmp_path)) == text


def test_sparse_speech_alone_does_not_discard(tmp_path: Path) -> None:
    """The conjunction from the other side: a short, confidently-heard line
    is kept, however little of it there is."""
    client = _StubClient(_Response("Add salt.", 60.0, [-0.12]))

    assert _transcriber(client).transcribe(_audio(tmp_path)) == "Add salt."


# --- what happens when the provider gives less than this needs ---------------


def test_a_provider_without_confidence_data_keeps_the_transcript(
    tmp_path: Path,
) -> None:
    """No segments means nothing to judge on. This gate removes words that
    were never spoken; it must not remove words it merely cannot measure."""
    client = _StubClient(_Response(CHAKNA_HALLUCINATION, 60.3, []))

    assert _transcriber(client).transcribe(_audio(tmp_path)) == CHAKNA_HALLUCINATION


def test_a_missing_score_is_not_read_as_perfect_confidence(tmp_path: Path) -> None:
    """Zero is the top of the log-probability scale, so a missing score
    coerced to 0.0 would read as certainty and keep exactly the transcripts
    this weighs. Absent scores are absent, not perfect."""
    client = _StubClient(_Response(SANDWICH_HALLUCINATION, 29.8, [None, -1.374]))

    assert _transcriber(client).transcribe(_audio(tmp_path)) == ""


def test_a_missing_duration_keeps_the_transcript(tmp_path: Path) -> None:
    """Without a duration there is no density to compute, and half the
    evidence is not enough to throw words away."""
    client = _StubClient(_Response(SANDWICH_HALLUCINATION, 0.0, [-1.374]))

    assert _transcriber(client).transcribe(_audio(tmp_path)) == SANDWICH_HALLUCINATION


def test_verbose_json_is_requested(tmp_path: Path) -> None:
    """The confidence data has to be asked for; the default response carries
    only the text, which is what the app read for months."""
    client = _StubClient(_Response("x" * 500, 30.0, [-0.12]))

    _transcriber(client).transcribe(_audio(tmp_path))

    assert client.calls[0]["response_format"] == "verbose_json"


def test_a_provider_that_rejects_verbose_json_still_transcribes(
    tmp_path: Path,
) -> None:
    """Losing the gate is worse than nothing. Losing transcription entirely,
    on a provider that simply does not serve this format, would be much
    worse -- and this codebase talks to whatever the operator configures."""
    client = _Picky(_Response("real speech here", 30.0, []))

    assert _transcriber(client).transcribe(_audio(tmp_path)) == "real speech here"
    assert "response_format" in client.calls[0]
    assert "response_format" not in client.calls[1]


def test_the_dropped_format_is_remembered(tmp_path: Path) -> None:
    """Otherwise every reel pays a rejected request to rediscover the same
    fact about the same endpoint."""
    client = _Picky(_Response("real speech here", 30.0, []))
    transcriber = _transcriber(client)

    transcriber.transcribe(_audio(tmp_path))
    transcriber.transcribe(_audio(tmp_path))

    # Rejected, retried, then asked plainly -- not rejected a second time.
    assert len(client.calls) == 3
    assert "response_format" not in client.calls[2]


def test_the_thresholds_are_where_the_measurements_put_them() -> None:
    """Both sit in the gap between the worst real reel and the best
    hallucination. If either moves, the table in this file's docstring is
    the evidence it has to move against."""
    assert MIN_MEAN_LOGPROB == -0.7  # between -0.509 (real) and -0.922 (invented)
    assert MIN_CHARS_PER_SECOND == 4.0  # between 1.14 (invented) and 11.90 (real)


class _Picky(_StubClient):
    """A provider that refuses `verbose_json` and names it when refusing."""

    def create(self, **kwargs: Any) -> Any:
        if "response_format" in kwargs:
            self.calls.append(kwargs)
            raise BadRequestError(
                message="unknown response_format: verbose_json",
                response=_FakeResponse(),  # type: ignore[arg-type]
                body=None,
            )
        return super().create(**kwargs)


class _FakeResponse:
    status_code = 400
    headers: dict[str, str] = {}
    request = None

    def json(self) -> dict[str, Any]:
        return {"error": {"message": "unknown response_format"}}
