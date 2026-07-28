"""Pytest fixtures wiring a real `SquadClient` to mocked PractiScore endpoints.

Importing `practiscore_squads` here means the whole suite errors out until the
package exists — that is intentional for the initial (red) TDD state.
"""
from __future__ import annotations

import pytest
import responses

from practiscore_squads import SquadClient  # noqa: F401  (drives the red state)
from practiscore_squads.pacing import Pacer

from tests._data import (
    COOKIE,
    ROSTER,
    SLUG,
    bootstrap_url,
    build_bootstrap,
    registered_re,
)


def fast_pacer() -> Pacer:
    """A Pacer with the inter-request gap removed.

    The production default is 0.8–1.6s per request (NF6: ~300 shooters over
    10–20 min), which would turn this suite into a ~70s wait for no added
    coverage. Backoff is left at its real value — tests that exercise the retry
    path monkeypatch `pacing.time.sleep` instead.
    """
    return Pacer(min_gap=0, max_gap=0)


@pytest.fixture
def make_client():
    """Factory → (client, rsps).

    `rsps` is an *active* RequestsMock with the bootstrap page and the roster
    search pre-registered; tests add check/save/lock/etc. responses to it and
    inspect `rsps.calls`.
    """
    started: list[responses.RequestsMock] = []

    def _make(locked: bool = False, roster=None):
        rsps = responses.RequestsMock(assert_all_requests_are_fired=False)
        rsps.start()
        started.append(rsps)
        rsps.add(responses.GET, bootstrap_url(),
                 body=build_bootstrap(locked), content_type="text/html")
        rsps.add(responses.GET, registered_re(),
                 json=ROSTER if roster is None else roster,
                 content_type="application/json")
        client = SquadClient.from_cookie(COOKIE, SLUG, pacer=fast_pacer())
        return client, rsps

    yield _make

    for rsps in started:
        try:
            rsps.stop()
        except Exception:
            pass
        rsps.reset()


@pytest.fixture
def client(make_client):
    """Convenience: an unlocked client at the sandbox initial layout."""
    c, _ = make_client()
    return c
