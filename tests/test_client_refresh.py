"""Snapshot lifecycle: refresh() re-scrapes; CSRF staleness self-heals (§5.5, §3.8)."""
from __future__ import annotations

import responses

from tests._data import (
    GRZEGORZ, SQUAD1, SQUAD3, bootstrap_url, build_bootstrap, build_squad, called_urls, check_re,
)


def _bootstrap_call_count(rsps) -> int:
    return sum(1 for u in called_urls(rsps) if u.rstrip("/").endswith("/squadding"))


def test_refresh_repicks_up_lock_state(make_client):
    """`refresh()` re-scrapes the bootstrap; a lock flipped externally is seen."""
    c, rsps = make_client(locked=False)
    assert c.is_locked() is False
    rsps.add(responses.GET, bootstrap_url(),
             body=build_bootstrap(locked=True), content_type="text/html")
    c.refresh()
    assert c.is_locked() is True


def test_refresh_repicks_up_occupancy(make_client):
    """§3.8/NF10: occupancy mutates externally; refresh() must reflect new members."""
    c, rsps = make_client()
    assert c.squad_members(3) == []
    # Squad 3 now has a shooter in position 1 (moved by someone else meanwhile).
    moved = build_bootstrap().replace(
        build_squad(SQUAD3),
        build_squad(SQUAD3, occupants={1: ("Grzegorz Brzęczyszczykiewicz ", "Production")}),
    )
    rsps.add(responses.GET, bootstrap_url(), body=moved, content_type="text/html")
    c.refresh()
    assert [s.id for s in c.squad_members(3)] == [GRZEGORZ]
    assert len(c.free_slots(3)) == 4


# --------------------------- TTL staleness (C1) --------------------------- #
def test_fresh_snapshot_does_not_trigger_refresh(make_client):
    """Within `snapshot_ttl` (default 120s), `move()` must not re-scrape (§4.1)."""
    c, rsps = make_client()
    assert _bootstrap_call_count(rsps) == 1
    rsps.add(responses.POST, check_re(SQUAD3, GRZEGORZ),
             body='{"cmd":"added","num":3}', content_type="text/html")
    c.move(GRZEGORZ, 3, position=1)
    assert _bootstrap_call_count(rsps) == 1, "a fresh snapshot must not trigger an extra refresh"


def test_stale_snapshot_forces_refresh(make_client):
    """Once the snapshot has outlived `snapshot_ttl`, `move()` must re-scrape first (§4.1)."""
    c, rsps = make_client()
    c.snapshot_ttl = 0   # force `_refresh_if_stale` to treat the snapshot as expired
    assert _bootstrap_call_count(rsps) == 1
    rsps.add(responses.POST, check_re(SQUAD3, GRZEGORZ),
             body='{"cmd":"added","num":3}', content_type="text/html")
    c.move(GRZEGORZ, 3, position=1)
    assert _bootstrap_call_count(rsps) == 2, "a stale snapshot must be re-scraped before the move"


def test_move_retries_once_on_419(make_client):
    """§5.5: a 419 (stale CSRF token) triggers one re-refresh + retry, transparent to caller."""
    c, rsps = make_client()
    rsps.add(responses.POST, check_re(SQUAD3, GRZEGORZ), status=419, body="")
    rsps.add(responses.GET, bootstrap_url(), body=build_bootstrap(), content_type="text/html")
    rsps.add(responses.POST, check_re(SQUAD3, GRZEGORZ),
             body='{"cmd":"added","num":3}', content_type="text/html")
    oc = c.move(GRZEGORZ, 3)
    assert oc.ok and oc.to_squad == 3
