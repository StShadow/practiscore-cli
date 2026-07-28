"""Opt-in integration test against the live sandbox match (P2, implementation.md §8/§8.2).

Deselected by default (`addopts = "-m 'not sandbox'"` in pyproject.toml). Run
explicitly with a real admin cookie for `test-reverse-engineer`:

    PRACTISCORE_COOKIE="XSRF-TOKEN=...; laravel_session=...; cf_clearance=..." \\
        pytest -m sandbox tests/test_sandbox.py

Read-only by design — no move/lock/remove call is made, so there is nothing to
restore afterwards (unlike the mutating discovery log in spec.md §8.2).
"""
from __future__ import annotations

import os

import pytest

from practiscore_squads import SquadClient

SANDBOX_SLUG = "test-reverse-engineer"
SANDBOX_MATCH_ID = 351459


pytestmark = pytest.mark.sandbox


@pytest.fixture
def sandbox_client() -> SquadClient:
    cookie = os.environ.get("PRACTISCORE_COOKIE")
    if not cookie:
        pytest.skip("PRACTISCORE_COOKIE not set — see this file's docstring")
    return SquadClient.from_cookie(cookie, SANDBOX_SLUG)


def test_match_id_matches_known_sandbox_value(sandbox_client):
    assert sandbox_client.match_id == SANDBOX_MATCH_ID


def test_squads_returns_three_squads_of_five(sandbox_client):
    squads = sandbox_client.squads()
    assert set(squads) == {1, 2, 3}
    assert all(len(slots) == 5 for slots in squads.values())


def test_roster_contains_the_two_known_shooters(sandbox_client):
    ids = {s.id for s in sandbox_client.roster()}
    assert {9808574, 9808577} <= ids
