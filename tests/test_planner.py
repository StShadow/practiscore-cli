"""MovePlanner classification: move/add/noop/blocked (O3, NF5, implementation.md §3.6)."""
from __future__ import annotations

import pytest
import responses

from practiscore_squads.errors import SlotNotFoundError
from practiscore_squads.planner import ADD, BLOCKED, MOVE, MovePlanner, NOOP

from tests._data import (
    ANATOLI, GRZEGORZ, SQUAD1, SQUAD3, bootstrap_url, build_bootstrap, build_squad,
)

NEWCOMER = 9808999


def test_plan_classifies_move(client):
    """Grzegorz is in Squad 1; planning him into Squad 3 (which has room) is a move."""
    plan = MovePlanner(client).plan([GRZEGORZ], 3)
    assert plan.target_squad == 3
    m = plan.moves[0]
    assert m.kind == MOVE
    assert m.from_squad == 1
    assert m.to_squad == 3
    assert m.shooter_id == GRZEGORZ
    assert plan.actionable() == [m]


def test_plan_classifies_noop_already_there(client):
    """Anatoli is already in Squad 2; planning him there again is a no-op."""
    plan = MovePlanner(client).plan([ANATOLI], 2)
    m = plan.moves[0]
    assert m.kind == NOOP
    assert m.from_squad == 2
    assert plan.actionable() == []


def test_plan_classifies_add_for_unsquadded_shooter(make_client):
    """A roster shooter with no occupied slot anywhere is an add, not a move."""
    roster = [
        {"id": GRZEGORZ, "name": "Grzegorz Brzęczyszczykiewicz ", "email": "g@example.invalid",
         "shDiv": "Production", "shClass": ""},
        {"id": ANATOLI, "name": "Anatoli Putseyeu ", "email": "a@example.invalid",
         "shDiv": "Standard", "shClass": ""},
        {"id": NEWCOMER, "name": "Nova Newcomer", "email": "n@example.invalid",
         "shDiv": "Open", "shClass": ""},
    ]
    c, rsps = make_client(roster=roster)
    plan = MovePlanner(c).plan([NEWCOMER], 3)
    m = plan.moves[0]
    assert m.kind == ADD
    assert m.from_squad is None
    assert m.shooter_id == NEWCOMER
    assert plan.actionable() == [m]


def test_plan_classifies_blocked_when_target_squad_full(make_client):
    """A target squad with zero free slots blocks a shooter who isn't already there."""
    c, rsps = make_client()
    full_squad1 = build_bootstrap().replace(
        build_squad(SQUAD1, {1: ("Grzegorz Brzęczyszczykiewicz ", "Production")}),
        build_squad(SQUAD1, {
            1: ("Grzegorz Brzęczyszczykiewicz ", "Production"),
            2: ("Filler Two", None), 3: ("Filler Three", None),
            4: ("Filler Four", None), 5: ("Filler Five", None),
        }),
    )
    rsps.add(responses.GET, bootstrap_url(), body=full_squad1, content_type="text/html")
    plan = MovePlanner(c).plan([ANATOLI], 1)
    m = plan.moves[0]
    assert m.kind == BLOCKED
    assert plan.actionable() == []


def test_plan_rejects_unknown_squad(client):
    with pytest.raises(SlotNotFoundError):
        MovePlanner(client).plan([GRZEGORZ], 99)


def test_plan_refreshes_before_classifying(make_client):
    """Occupancy changed externally since construction; plan() must refresh first."""
    c, rsps = make_client()
    moved = build_bootstrap().replace(
        build_squad(SQUAD3),
        build_squad(SQUAD3, occupants={1: ("Grzegorz Brzęczyszczykiewicz ", "Production")}),
    ).replace(
        build_squad(SQUAD1, {1: ("Grzegorz Brzęczyszczykiewicz ", "Production")}),
        build_squad(SQUAD1),
    )
    rsps.add(responses.GET, bootstrap_url(), body=moved, content_type="text/html")
    plan = MovePlanner(c).plan([GRZEGORZ], 3)
    assert plan.moves[0].kind == NOOP
