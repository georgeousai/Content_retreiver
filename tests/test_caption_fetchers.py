"""Regression tests for the oEmbed caption fetcher's HTTP handling.

Both failures here were measured against the live `api.instagram.com/oembed`
endpoint on 2026-08-31, and the transport below replays exactly what it
served: a 301 to the trailing-slash form, a 302 after that, and finally a 200
carrying Instagram's HTML login wall rather than JSON.

The transport is driven through a real `httpx.Client`, so httpx itself
decides what following a redirect means and what `raise_for_status` does with
an unfollowed one. That matters: the bug was precisely that httpx does not
follow redirects unless asked and rejects the 3xx it did not follow, and a
fake that branched on the keyword argument would assert the call's signature
while never exercising the behaviour the signature buys.
"""

from __future__ import annotations

import httpx
import pytest

from reel_vault.adapters.caption import OEMBED_URL, OEmbedCaptionFetcher

REEL_URL = "https://www.instagram.com/reel/DcoQRJKguIZ/"

# Truncated stand-in for the ~619KB page the redirect chain lands on.
LOGIN_WALL_HTML = "<!DOCTYPE html><html><head><title>Instagram</title></head></html>"


def _instagram_today(request: httpx.Request) -> httpx.Response:
    """The live endpoint's three hops, keyed on the path httpx asks for."""
    if request.url.path == "/oembed":
        return httpx.Response(301, headers={"location": "/oembed/"})
    return httpx.Response(
        200,
        headers={"content-type": 'text/html; charset="utf-8"'},
        text=LOGIN_WALL_HTML,
    )


def _serving(handler, *, force_no_redirects: bool = False):
    """A replacement for `httpx.get` that routes through a real client.

    `force_no_redirects` ignores what the caller asked for, which is how the
    pre-fix behaviour is reproduced: it is the only way to assert that the
    flag is load-bearing rather than decorative.
    """
    calls: list[httpx.Request] = []

    def fake_get(url, **kwargs):
        if force_no_redirects:
            kwargs["follow_redirects"] = False
        with httpx.Client(
            transport=httpx.MockTransport(handler),
            follow_redirects=kwargs.pop("follow_redirects", False),
        ) as client:
            response = client.get(url, **kwargs)
        calls.append(response.request)
        return response

    fake_get.calls = calls
    return fake_get


def test_without_following_redirects_every_call_failed(monkeypatch) -> None:
    """The bug, reproduced: Instagram 301s this endpoint, httpx does not
    follow by default, and `raise_for_status` rejects the 3xx it did not
    follow — so the fetcher never reached the endpoint at all."""
    monkeypatch.setattr(
        httpx, "get", _serving(_instagram_today, force_no_redirects=True)
    )

    assert OEmbedCaptionFetcher().fetch(REEL_URL) is None


def test_following_the_redirect_reaches_the_endpoint(monkeypatch) -> None:
    """With the fix the chain is walked to its end — the final request is for
    the trailing-slash path, not the one the fetcher first asked for."""
    fake_get = _serving(_instagram_today)
    monkeypatch.setattr(httpx, "get", fake_get)

    OEmbedCaptionFetcher().fetch(REEL_URL)

    assert fake_get.calls, "the fetcher made no HTTP call"
    assert fake_get.calls[-1].url.path == "/oembed/"


def test_the_html_login_wall_is_a_miss_rather_than_a_crash(monkeypatch) -> None:
    """What following the redirect actually reaches today is a 200 carrying
    HTML: the legacy unauthenticated endpoint is retired. Nothing upstream
    catches an exception from the caption fetcher — `Vault.save_reel` calls it
    bare — so a JSONDecodeError here would abort the whole save instead of
    falling through to the scraper."""
    monkeypatch.setattr(httpx, "get", _serving(_instagram_today))

    assert OEmbedCaptionFetcher().fetch(REEL_URL) is None


def test_a_json_payload_that_is_not_an_object_is_a_miss(monkeypatch) -> None:
    monkeypatch.setattr(
        httpx,
        "get",
        _serving(lambda request: httpx.Response(200, json=["not", "an", "object"])),
    )

    assert OEmbedCaptionFetcher().fetch(REEL_URL) is None


def test_a_real_oembed_payload_is_still_read(monkeypatch) -> None:
    """The parsing path the endpoint served before it was retired, kept so the
    redirect and non-JSON guards cannot quietly break the success case."""
    payload = {
        "title": "The crispiest and stickiest Honey Chicken Tenders ever!",
        "author_name": "buzzfeedtasty",
        "thumbnail_url": "https://example.test/thumb.jpg",
    }
    monkeypatch.setattr(
        httpx, "get", _serving(lambda request: httpx.Response(200, json=payload))
    )

    post = OEmbedCaptionFetcher().fetch(REEL_URL)

    assert post is not None
    assert post.caption.startswith("The crispiest")
    assert post.author_handle == "buzzfeedtasty"
    assert post.thumbnail_url == "https://example.test/thumb.jpg"


def test_the_endpoint_it_asks_is_the_documented_one(monkeypatch) -> None:
    fake_get = _serving(lambda request: httpx.Response(200, json={}))
    monkeypatch.setattr(httpx, "get", fake_get)

    OEmbedCaptionFetcher().fetch(REEL_URL)

    request = fake_get.calls[0]
    assert str(request.url).startswith(OEMBED_URL)
    assert request.url.params["url"] == REEL_URL


@pytest.mark.parametrize("status", [404, 500])
def test_an_http_error_is_still_a_miss(monkeypatch, status: int) -> None:
    monkeypatch.setattr(
        httpx, "get", _serving(lambda request: httpx.Response(status))
    )

    assert OEmbedCaptionFetcher().fetch(REEL_URL) is None
