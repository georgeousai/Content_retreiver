"""An empty reply is not an answer until `finish_reason` has been checked.

This is the bug that cost this project the most, and it never looked like a
bug in code. `openai/gpt-oss-20b` is a reasoning model: it spends completion
tokens thinking before it writes. On a 2048-token budget it spent 2046
reasoning about a chicken recipe and had none left to answer with, so the
reply arrived as `finish_reason="length"` with `content=""` — indistinguishable
from a model deliberately returning nothing, which is a meaningful answer
here (the condenser empties a transcript that carries nothing).

Read as an answer, that produced a "the model empties real content 9 times in
10" measurement, prompt rewrites, a counter-example added and later removed,
and a two-provider comparison. All of it downstream of a truncated response
being mistaken for a considered one.

These tests are hermetic: a stub client returns the shapes a real provider
returns, so the distinction is pinned without spending a call.
"""

from __future__ import annotations

from typing import Any

import pytest
from openai import BadRequestError

from reel_vault.adapters.llm import ChatContentCondenser, TruncatedResponse


class _StubClient:
    """The two-attribute slice of the OpenAI client these adapters use."""

    def __init__(self, content: str | None, finish_reason: str) -> None:
        self._content = content
        self._finish_reason = finish_reason
        self.calls: list[dict[str, Any]] = []
        self.chat = self  # type: ignore[assignment]
        self.completions = self  # type: ignore[assignment]

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        message = type("Message", (), {"content": self._content})()
        choice = type(
            "Choice", (), {"message": message, "finish_reason": self._finish_reason}
        )()
        return type("Response", (), {"choices": [choice]})()


def _condenser(content: str | None, finish_reason: str) -> tuple:
    """The stub stands in for an `OpenAI` client across the two attributes
    these adapters touch, which is all the seam needs and far less than the
    real type declares."""
    client = _StubClient(content, finish_reason)
    condenser = ChatContentCondenser(
        client=client,  # type: ignore[arg-type]
        model="test-model",
    )
    return condenser, client


def test_a_reply_cut_off_before_it_started_is_not_an_empty_answer() -> None:
    """The measured failure, in the shape the API actually returns it."""
    condenser, _ = _condenser("", "length")

    with pytest.raises(TruncatedResponse):
        condenser.condense("a transcript with plenty in it")


def test_a_deliberate_empty_answer_is_still_an_answer() -> None:
    """The other side of the same distinction, and the reason this cannot
    simply treat every empty string as a failure: emptying a transcript that
    carries nothing is the condenser doing its job."""
    condenser, _ = _condenser("", "stop")

    assert condenser.condense("comment BELOW for my list") == ""


def test_a_truncated_reply_that_still_said_something_is_kept() -> None:
    """Cut off mid-sentence is a partial answer, not a non-answer. Losing it
    would throw away content over a technicality."""
    condenser, _ = _condenser("wake at five, cold shower", "length")

    assert condenser.condense("...") == "wake at five, cold shower"


def test_the_condenser_asks_for_shallow_reasoning() -> None:
    """The fix for the truncation rather than the detection of it: the same
    answer in 101 reasoning tokens instead of 2046, on a call this pipeline
    makes twice per reel against a free tier."""
    condenser, client = _condenser("a summary", "stop")

    condenser.condense("something worth condensing")

    assert client.calls[0]["reasoning_effort"] == "low"


def test_a_provider_that_rejects_reasoning_effort_still_works() -> None:
    """`reasoning_effort` is standard where it exists and simply absent
    elsewhere. A provider that has never heard of it must not become a
    provider this vault cannot use — the whole point of talking to everything
    over one wire format."""
    client = _Rejecting("a summary", "stop", "unknown parameter: reasoning_effort")
    condenser = ChatContentCondenser(
        client=client,  # type: ignore[arg-type]
        model="picky-model",
    )

    assert condenser.condense("something worth condensing") == "a summary"
    assert "reasoning_effort" in client.calls[0]
    assert "reasoning_effort" not in client.calls[1]


def test_the_dropped_parameter_is_remembered_for_the_rest_of_the_run() -> None:
    """Otherwise every call pays a wasted request to rediscover the same
    fact, on an adapter used twice per reel."""
    client = _Rejecting("a summary", "stop", "unknown parameter: reasoning_effort")
    condenser = ChatContentCondenser(
        client=client,  # type: ignore[arg-type]
        model="picky-model",
    )

    condenser.condense("first")
    condenser.condense("second")

    # Two calls for the first condense (rejected, then retried), one for the
    # second -- not two again.
    assert len(client.calls) == 3
    assert "reasoning_effort" not in client.calls[2]


def test_a_bad_request_about_anything_else_is_not_swallowed() -> None:
    """A 400 has many causes -- context length, a content filter, a model
    name that does not exist. Retrying those without `reasoning_effort` would
    spend a second call to fail the same way, and log something untrue about
    why."""
    client = _Rejecting("a summary", "stop", "context_length_exceeded")
    condenser = ChatContentCondenser(
        client=client,  # type: ignore[arg-type]
        model="picky-model",
    )

    with pytest.raises(BadRequestError):
        condenser.condense("far too much text")
    assert len(client.calls) == 1


class _Rejecting(_StubClient):
    """A provider that 400s whenever `reasoning_effort` is sent, with a
    message the caller has to inspect to know what it objected to."""

    def __init__(self, content: str, finish_reason: str, message: str) -> None:
        super().__init__(content, finish_reason)
        self._message = message

    def create(self, **kwargs: Any) -> Any:
        if "reasoning_effort" in kwargs:
            self.calls.append(kwargs)
            raise BadRequestError(
                message=self._message,
                response=_FakeResponse(),  # type: ignore[arg-type]
                body=None,
            )
        return super().create(**kwargs)


class _FakeResponse:
    status_code = 400
    headers: dict[str, str] = {}
    request = None

    def json(self) -> dict[str, Any]:
        return {"error": {"message": "unknown parameter"}}

def test_a_parsing_adapter_degrades_instead_of_raising() -> None:
    """The other half of the distinction, and the reason it exists.

    `ChatTagger` parses a list out of the reply, so a truncated reply is just
    an unparseable one, and returning no tags is the long-standing graceful
    answer to that. Raising here instead would abort `save_reel` outright --
    nothing in `Vault.save_reel` or `bot.py` catches it -- turning "the reel
    saved without tags" into "the share got no reply at all". That is worse
    than the bug this change fixes, so only the condenser opts in.
    """
    from reel_vault.adapters.llm import ChatTagger

    client = _StubClient("", "length")
    tagger = ChatTagger(
        client=client,  # type: ignore[arg-type]
        model="test-model",
    )

    assert tagger.tag("a caption") == []
