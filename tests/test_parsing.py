"""HTML/JSON parsing (implementation.md §3.4)."""
from __future__ import annotations

import pytest

from practiscore_squads import LockState
from practiscore_squads.errors import ServerError, SquaddingError
from practiscore_squads.parsing import BootstrapParser, SearchParser
from practiscore_squads.http import Parsed

from tests._data import (
    CSRF, MATCH_ID, ROSTER, SCHEDULE_ID, SLUG, SQUAD1, SQUAD2, SQUAD3,
    build_bootstrap, build_squad,
)


# --------------------------- BootstrapParser ------------------------------ #
def test_parse_core_identifiers():
    snap = BootstrapParser().parse(build_bootstrap(), SLUG)
    assert snap.match_id == MATCH_ID
    assert snap.csrf == CSRF
    assert snap.lock is LockState.UNLOCKED
    assert SCHEDULE_ID in snap.schedule_ids


def test_parse_slots_count_and_squad_numbers():
    snap = BootstrapParser().parse(build_bootstrap(), SLUG)
    assert len(snap.slots) == 15  # 3 squads x 5
    assert snap.squad_ids() == {1: SQUAD1, 2: SQUAD2, 3: SQUAD3}


def test_parse_strips_trailing_whitespace_in_names():
    """§3.2: occupant display names may carry trailing whitespace."""
    snap = BootstrapParser().parse(build_bootstrap(), SLUG)
    occ = snap.slot(1, 1).occupant
    assert occ == "Grzegorz Brzęczyszczykiewicz"  # no trailing space


def test_parse_empty_slot_is_free():
    snap = BootstrapParser().parse(build_bootstrap(), SLUG)
    assert snap.slot(3, 1).occupant is None
    assert snap.slot(3, 1).free is True


def test_parse_locked_button():
    snap = BootstrapParser().parse(build_bootstrap(locked=True), SLUG)
    assert snap.lock is LockState.LOCKED


def test_parse_reserved_and_disabled_slots():
    """Reserved/disabled slots must be flagged and treated as not-free (§2.4)."""
    extra = "\n" + build_squad(SQUAD3, reserved={2}, disabled={3})
    # Rebuild a page whose Squad 3 carries a reserved + a disabled slot.
    html = build_bootstrap().replace(build_squad(SQUAD3), build_squad(SQUAD3, reserved={2}, disabled={3}))
    snap = BootstrapParser().parse(html, SLUG)
    assert snap.slot(3, 2).reserved is True
    assert snap.slot(3, 2).free is False
    assert snap.slot(3, 3).disabled is True
    assert snap.slot(3, 3).free is False


# --------------------------- SearchParser --------------------------------- #
def test_search_parse_roster():
    shooters = SearchParser().parse(Parsed(status=200, json=ROSTER, text=""))
    assert [s.id for s in shooters] == [ROSTER[0]["id"], ROSTER[1]["id"]]
    assert shooters[0].name == "Grzegorz Brzęczyszczykiewicz"  # stripped
    assert shooters[0].email == "grzegorz@example.invalid"
    assert shooters[0].division == "Production"


def test_search_parse_empty_array():
    assert SearchParser().parse(Parsed(status=200, json=[], text="[]")) == []


def test_search_parse_server_error():
    """§3.2: wrong matchId / malformed slot → 500 {"message":"Server Error"}."""
    p = Parsed(status=500, json={"message": "Server Error"}, text='{"message":"Server Error"}')
    with pytest.raises(ServerError):
        SearchParser().parse(p)


def test_search_parse_404_raises():
    """§3.2: empty query segment → 404."""
    with pytest.raises(SquaddingError):
        SearchParser().parse(Parsed(status=404, json=None, text="Not Found"))
