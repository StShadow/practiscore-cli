"""Transport layer: retry, throttle exhaustion, transport-error containment.

Exercises the retry loop in `http.py` that no other test file touches. The policy
under test is implementation.md §3.3: "transient (429, 503, connection error) →
up to N attempts with pacer.penalize".
"""
from __future__ import annotations

import pytest
import requests
import responses

from practiscore_squads.errors import SquaddingError, ThrottledError
from practiscore_squads.http import HttpClient
from practiscore_squads.pacing import Pacer

from tests._data import BASE

PATH = "/squads/registered/squad_1458603_1_351459/x"
URL = f"{BASE}{PATH}"


def _client() -> HttpClient:
    """An HttpClient whose pacer never sleeps — backoff_base=0 keeps the retry
    loop instantaneous so these tests don't pay the real 2+4+8s backoff."""
    return HttpClient.from_cookie(
        "laravel_session=sess",
        pacer=Pacer(min_gap=0, max_gap=0, backoff_base=0, backoff_cap=0),
    )


# ---------------------- throttle exhaustion (NF6) ------------------------- #
@responses.activate
def test_exhausted_429_raises_throttled():
    """Retries running out must raise ThrottledError.

    Today the loop gives up and hands the 429 back as if it were a normal body,
    so it surfaces far downstream as
    `UnexpectedResponseError: unexpected check() response: 'Too Many Requests'`
    — blaming the payload for what is actually rate limiting.
    """
    responses.add(responses.GET, URL, body="Too Many Requests", status=429)
    with pytest.raises(ThrottledError):
        _client().get(PATH)


@responses.activate
def test_exhausted_503_raises_throttled():
    """503 is on the same retry path as 429 and must end the same way."""
    responses.add(responses.GET, URL, body="Service Unavailable", status=503)
    with pytest.raises(ThrottledError):
        _client().get(PATH)


# ------------- transport errors (implementation.md §3.3) ------------------ #
@responses.activate
def test_connection_error_is_retried_then_succeeds():
    """§3.3 lists connection errors alongside 429/503 as retryable, but the loop
    only inspects status codes — a single blip currently ends the request."""
    responses.add(responses.GET, URL, body=requests.exceptions.ConnectionError())
    responses.add(responses.GET, URL, json=[], status=200)
    assert _client().get(PATH).status == 200


@responses.activate
def test_exhausted_connection_error_raises_squadding_error():
    """An unrecoverable transport failure must stay inside the library's error
    hierarchy (§5.4). Asserting on the base class deliberately leaves the concrete
    name (TransportError or otherwise) to the fix.
    """
    responses.add(responses.GET, URL, body=requests.exceptions.ConnectionError())
    with pytest.raises(SquaddingError):
        _client().get(PATH)


@responses.activate
def test_exhausted_timeout_raises_squadding_error():
    """Timeouts are the same family as connection errors for retry purposes."""
    responses.add(responses.GET, URL, body=requests.exceptions.Timeout())
    with pytest.raises(SquaddingError):
        _client().get(PATH)


# ------------------------- response encoding (NF11) ----------------------- #
@responses.activate
def test_body_without_charset_is_decoded_as_utf8():
    """`_send` forces resp.encoding = "utf-8" — the single line that makes Polish and
    Cyrillic names survive (NF11).

    requests falls back to Latin-1 for text/* with no charset parameter (RFC 2616), so
    without that line these bytes come back mojibaked. Nothing else in the suite covers
    it: the other fixtures pass `str` bodies, which responses labels with a charset.
    """
    responses.add(responses.GET, URL,
                  body="Grzegorz Brzęczyszczykiewicz".encode(),
                  content_type="text/html")           # deliberately no charset
    assert _client().get(PATH).text == "Grzegorz Brzęczyszczykiewicz"
