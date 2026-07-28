"""Single-move safety — the highest-value tests (NF10, guards §3.4 & §3.3/§6.8)."""
from __future__ import annotations

import pytest
import responses

from practiscore_squads.errors import ServerError, SlotNotFoundError, UnexpectedResponseError

from tests._data import (
    ANATOLI, CSRF, GRZEGORZ, SQUAD1, SQUAD2, SQUAD3, bodies_for, check_re, path_called, save_re,
)


def _add_check(rsps, squad_id, shooter, cmd, num, status=200):
    rsps.add(responses.POST, check_re(squad_id, shooter),
             body=f'{{"cmd":"{cmd}","num":{num}}}', status=status,
             content_type="text/html")  # §8.2: check success is text/html holding JSON


def _add_save(rsps, squad_id, shooter, body="moved"):
    rsps.add(responses.POST, save_re(squad_id, shooter), body=body, content_type="text/html")


# --------------------------- the four check branches ---------------------- #
def test_move_added(make_client):
    """cmd=added → placed; no save call (§3.3)."""
    c, rsps = make_client()
    _add_check(rsps, SQUAD3, GRZEGORZ, "added", 3)
    oc = c.move(GRZEGORZ, 3)
    assert oc.ok and oc.to_squad == 3
    assert "added" in oc.detail
    assert not path_called(rsps, "/squads/save/")


def test_move_same_is_noop(make_client):
    """cmd=same → idempotent no-op; no save call."""
    c, rsps = make_client()
    _add_check(rsps, SQUAD1, GRZEGORZ, "same", 1)
    oc = c.move(GRZEGORZ, 1)
    assert oc.ok
    assert not path_called(rsps, "/squads/save/")


def test_move_server_taken(make_client):
    """A slot free in the snapshot but 'taken' at the server → ok=False, no save."""
    c, rsps = make_client()
    _add_check(rsps, SQUAD3, GRZEGORZ, "taken", 3)
    oc = c.move(GRZEGORZ, 3, position=2)   # pos 2 is free in the snapshot
    assert oc.ok is False
    assert "taken" in oc.detail
    assert not path_called(rsps, "/squads/save/")


def test_move_commits_with_save(make_client):
    """cmd=move → save is issued and must return exactly 'moved' (§3.4)."""
    c, rsps = make_client()
    _add_check(rsps, SQUAD3, GRZEGORZ, "move", 1)   # origin squad = 1
    _add_save(rsps, SQUAD3, GRZEGORZ)
    oc = c.move(GRZEGORZ, 3)
    assert oc.ok and oc.to_squad == 3 and oc.from_squad == 1
    assert path_called(rsps, "/squads/save/")


# --------------------------- safety invariants ---------------------------- #
def test_never_saves_onto_occupied_target(make_client):
    """NF10 / §3.4: refuse an occupied target slot WITHOUT probing the server."""
    c, rsps = make_client()
    oc = c.move(GRZEGORZ, 2, position=1)   # squad 2 pos 1 is occupied by Anatoli
    assert oc.ok is False
    assert not path_called(rsps, "/squads/check/")
    assert not path_called(rsps, "/squads/save/")


def test_rejects_out_of_range_position(make_client):
    """NF10 / §6.8: an out-of-range position must never reach the API."""
    c, rsps = make_client()
    with pytest.raises(SlotNotFoundError):
        c.move(GRZEGORZ, 1, position=7)    # squad renders only 1..5
    assert not path_called(rsps, "/squads/check/")
    assert not path_called(rsps, "/squads/save/")


def test_never_saves_unless_check_said_move(make_client):
    """The core invariant: save only after cmd=='move'."""
    c, rsps = make_client()
    _add_check(rsps, SQUAD3, GRZEGORZ, "added", 3)
    # Register a save too; the client must NOT call it for an 'added' result.
    _add_save(rsps, SQUAD3, GRZEGORZ)
    c.move(GRZEGORZ, 3)
    assert not path_called(rsps, "/squads/save/")


def test_save_non_moved_body_raises(make_client):
    """A save body other than 'moved' means the unvalidated path misbehaved (§3.4)."""
    c, rsps = make_client()
    _add_check(rsps, SQUAD3, GRZEGORZ, "move", 1)
    _add_save(rsps, SQUAD3, GRZEGORZ, body="oops")
    with pytest.raises(UnexpectedResponseError):
        c.move(GRZEGORZ, 3)


def test_check_server_error_raises(make_client):
    """§3.3: unknown shooter / bad slot → 500 → ServerError."""
    c, rsps = make_client()
    rsps.add(responses.POST, check_re(SQUAD3, GRZEGORZ),
             json={"message": "Server Error"}, status=500)
    with pytest.raises(ServerError):
        c.move(GRZEGORZ, 3)


# --------------------------- notifications (NF4) -------------------------- #
def test_notify_false_suppresses_email(make_client):
    """Default silent: check body email=0, save body send=no."""
    c, rsps = make_client()
    _add_check(rsps, SQUAD3, GRZEGORZ, "move", 1)
    _add_save(rsps, SQUAD3, GRZEGORZ)
    c.move(GRZEGORZ, 3, notify=False)
    assert "email=0" in bodies_for(rsps, "/squads/check/")[0]
    assert "send=no" in bodies_for(rsps, "/squads/save/")[0]


def test_notify_true_opts_in(make_client):
    """--notify: check body email=1, save body send=yes (§3.3/§3.4)."""
    c, rsps = make_client()
    _add_check(rsps, SQUAD3, GRZEGORZ, "move", 1)
    _add_save(rsps, SQUAD3, GRZEGORZ)
    c.move(GRZEGORZ, 3, notify=True)
    assert "email=1" in bodies_for(rsps, "/squads/check/")[0]
    assert "send=yes" in bodies_for(rsps, "/squads/save/")[0]


# --------------------------- CSRF (§5.5) ---------------------------------- #
def test_mutations_carry_csrf_header(make_client):
    """§5.5: every mutating POST must send the scraped token as X-CSRF-TOKEN."""
    c, rsps = make_client()
    _add_check(rsps, SQUAD3, GRZEGORZ, "move", 1)
    _add_save(rsps, SQUAD3, GRZEGORZ)
    c.move(GRZEGORZ, 3)
    mutations = [c_ for c_ in rsps.calls
                 if "/squads/check/" in c_.request.url or "/squads/save/" in c_.request.url]
    assert mutations, "expected check + save calls"
    for call in mutations:
        assert call.request.headers.get("X-CSRF-TOKEN") == CSRF


# --------------------------- add() ---------------------------------------- #
def test_add_places_unsquadded_shooter(make_client):
    c, rsps = make_client()
    _add_check(rsps, SQUAD3, GRZEGORZ, "added", 3)
    oc = c.add(GRZEGORZ, 3)
    assert oc.ok and oc.to_squad == 3


# ------------------- snapshot freshness after a write --------------------- #
# The snapshot is the only thing auto-pick consults. If a committed write is not
# recorded in it, the client keeps offering a slot it just filled itself — the
# failure is self-inflicted, not a server race (NF10 post-state, §5.2 "concurrency").
def _checked_slots(rsps) -> list[str]:
    """Slot address (`squad_<id>_<pos>_<match>`) targeted by each check() call."""
    return [c_.request.url.split("/squads/check/")[1].rsplit("/", 1)[0]
            for c_ in rsps.calls if "/squads/check/" in c_.request.url]


def test_successful_move_marks_slot_occupied_in_snapshot(make_client):
    """A committed write must leave the target slot non-free in the snapshot."""
    c, rsps = make_client()
    _add_check(rsps, SQUAD3, GRZEGORZ, "added", 3)
    oc = c.move(GRZEGORZ, 3, position=1)
    assert oc.ok
    assert c.snapshot.slot(3, 1).free is False
    assert 1 not in [s.position for s in c.free_slots(3)]


def test_consecutive_auto_picked_moves_use_distinct_slots(make_client):
    """Two auto-picked moves into one squad must not address the same slot.

    Today the second shooter comes back 'taken' purely because the stale
    snapshot re-offered position 1 — the server never had a conflict.
    """
    c, rsps = make_client()
    _add_check(rsps, SQUAD3, GRZEGORZ, "added", 3)
    _add_check(rsps, SQUAD3, ANATOLI, "added", 3)
    c.move(GRZEGORZ, 3)
    c.move(ANATOLI, 3)
    targeted = _checked_slots(rsps)
    assert len(targeted) == 2
    assert targeted[0] != targeted[1], f"both moves addressed {targeted[0]}"


def test_consecutive_bulk_batches_do_not_reuse_slots(make_client):
    """Same defect via the bulk path: batch 2 re-issues batch 1's slot addresses.

    `move_many` pre-assigns distinct slots *within* one batch, so the collision
    only shows up across successive calls.
    """
    c, rsps = make_client()
    _add_check(rsps, SQUAD3, GRZEGORZ, "added", 3)
    _add_check(rsps, SQUAD3, ANATOLI, "added", 3)
    c.move_many([GRZEGORZ], 3)
    c.move_many([ANATOLI], 3)
    targeted = _checked_slots(rsps)
    assert len(targeted) == 2
    assert targeted[0] != targeted[1], f"both batches addressed {targeted[0]}"
