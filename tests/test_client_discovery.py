"""Read/discovery surface of SquadClient (F0/F1/F2, spec §5.2)."""
from __future__ import annotations

import pytest

from practiscore_squads import SquadClient, Slot
from practiscore_squads.client import parse_match_slug
from practiscore_squads.errors import InvalidMatchError

from tests._data import (
    ANATOLI, BASE, COOKIE, GRZEGORZ, MATCH_ID, SLUG, called_urls,
)


def test_match_id_autodiscovered(client):
    """F0: matchId is scraped from the bootstrap page, not supplied by the user."""
    assert client.match_id == MATCH_ID


def test_from_cookie_stores_slug(make_client):
    c, _ = make_client()
    assert c.snapshot.slug == SLUG


def test_squads_shape(client):
    """F1: dict keyed by DISPLAYED squad number, 5 slots each."""
    squads = client.squads()
    assert set(squads) == {1, 2, 3}
    assert all(len(slots) == 5 for slots in squads.values())
    assert all(isinstance(s, Slot) for s in squads[1])


def test_free_slots_overall_and_per_squad(client):
    assert len(client.free_slots()) == 13          # 15 total - 2 occupied
    assert len(client.free_slots(3)) == 5          # squad 3 empty
    assert len(client.free_slots(1)) == 4          # squad 1 has 1 occupant


def test_roster_returns_all_shooters(client):
    """F2: roster() lists every registered shooter as (name, ID)."""
    roster = client.roster()
    assert {s.id for s in roster} == {GRZEGORZ, ANATOLI}


def test_squad_members(client):
    """F2: shooters within one squad."""
    members = client.squad_members(1)
    assert [s.id for s in members] == [GRZEGORZ]
    assert client.squad_members(3) == []


def test_is_locked_reflects_state(make_client):
    unlocked, _ = make_client(locked=False)
    assert unlocked.is_locked() is False
    locked, _ = make_client(locked=True)
    assert locked.is_locked() is True


def test_search_escapes_wildcards_when_literal(make_client):
    """§3.2: literal search must escape SQL LIKE wildcards `_` and `%`."""
    c, rsps = make_client()
    c.search("An_toli", literal=True)
    literal_url = [u for u in called_urls(rsps) if "/squads/registered/" in u][-1]
    # escaped underscore appears as a backslash (possibly percent-encoded as %5C)
    assert ("%5C_" in literal_url) or (r"\_" in literal_url)


def test_search_passes_wildcards_when_not_literal(make_client):
    c, rsps = make_client()
    c.search("An_toli", literal=False)
    wildcard_url = [u for u in called_urls(rsps) if "/squads/registered/" in u][-1]
    assert ("%5C" not in wildcard_url) and (r"\_" not in wildcard_url)


def test_roster_uses_list_all_query(make_client):
    """roster() lists everyone via the `%20` (space) 'list all' query (§3.2)."""
    c, rsps = make_client()
    c.roster()
    url = [u for u in called_urls(rsps) if "/squads/registered/" in u][-1]
    assert ("%20" in url) or url.rstrip("/").endswith("/ ")


# --------------------------- match slug/URL parsing (C3) ------------------- #
def test_parse_match_slug_accepts_bare_slug():
    assert parse_match_slug(SLUG) == SLUG


def test_parse_match_slug_accepts_full_url():
    assert parse_match_slug(f"{BASE}/{SLUG}/squadding") == SLUG


def test_parse_match_slug_accepts_full_url_with_trailing_slash():
    assert parse_match_slug(f"{BASE}/{SLUG}/squadding/") == SLUG


def test_parse_match_slug_rejects_malformed_url():
    """A URL-shaped value missing `/squadding` must raise, not become a literal slug."""
    with pytest.raises(InvalidMatchError):
        parse_match_slug(f"{BASE}/{SLUG}")


def test_parse_match_slug_rejects_url_to_other_path():
    with pytest.raises(InvalidMatchError):
        parse_match_slug(f"{BASE}/{SLUG}/results")


def test_from_cookie_rejects_malformed_match_url():
    """Raises before any network call — `parse_match_slug` runs first in `from_cookie`."""
    with pytest.raises(InvalidMatchError):
        SquadClient.from_cookie(COOKIE, f"{BASE}/{SLUG}")
