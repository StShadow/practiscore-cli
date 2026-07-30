"""MovePlanner classification: move/add/noop/blocked (O3, NF5, implementation.md §3.6)."""
from __future__ import annotations

import pytest
import responses

from practiscore_squads.errors import SlotNotFoundError
from practiscore_squads.planner import ADD, BLOCKED, MOVE, MovePlanner, NOOP, POSITION_TAKEN

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


def test_plan_position_classifies_move_against_the_scraped_slot(client):
    """Grzegorz is in Squad 1; Squad 3 position 2 is free, so an explicit
    `--position 2` classifies exactly like the auto-picked path would (B1)."""
    plan = MovePlanner(client).plan([GRZEGORZ], 3, position=2)
    m = plan.moves[0]
    assert m.kind == MOVE
    assert m.from_squad == 1
    assert plan.actionable() == [m]


def test_plan_position_classifies_add_for_unsquadded_shooter(make_client):
    roster = [
        {"id": GRZEGORZ, "name": "Grzegorz Brzęczyszczykiewicz ", "email": "g@example.invalid",
         "shDiv": "Production", "shClass": ""},
        {"id": NEWCOMER, "name": "Nova Newcomer", "email": "n@example.invalid",
         "shDiv": "Open", "shClass": ""},
    ]
    c, rsps = make_client(roster=roster)
    plan = MovePlanner(c).plan([NEWCOMER], 3, position=2)
    m = plan.moves[0]
    assert m.kind == ADD
    assert m.from_squad is None


def test_plan_position_blocks_on_an_occupied_explicit_slot(client):
    """B1's headline bug: previously the plan ignored `position` entirely and
    classified this as a plain `MOVE`, while `client.move(position=1)` — which
    does check occupancy on the explicit slot — came back `taken`. The preview
    must call this a blocked position, not promise a move it can't deliver."""
    plan = MovePlanner(client).plan([ANATOLI], 1, position=1)  # Squad 1 pos 1 = Grzegorz
    m = plan.moves[0]
    assert m.kind == POSITION_TAKEN
    assert plan.actionable() == []


def test_plan_position_taken_is_not_reclassified_as_noop_for_the_occupant(client):
    """Mirrors `SquadClient.move()`'s own local free-check (client.py): it never
    asks whether an occupied slot's occupant is this same shooter, so pointing
    a shooter at their own current position is still `POSITION_TAKEN`, not a
    `NOOP` the planner invented that the real write would never produce."""
    plan = MovePlanner(client).plan([GRZEGORZ], 1, position=1)  # Grzegorz's own slot
    m = plan.moves[0]
    assert m.kind == POSITION_TAKEN


def test_plan_position_raises_for_an_unscraped_position(client):
    """Squad 1 only renders 5 slots (§6.8); an explicit position past that must
    raise the same `SlotNotFoundError` `client.move()` raises rather than
    silently falling back to auto-pick."""
    with pytest.raises(SlotNotFoundError):
        MovePlanner(client).plan([ANATOLI], 1, position=99)


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


def test_explicit_position_in_the_shooters_own_squad_is_a_noop(make_client):
    """A free explicit slot inside the shooter's CURRENT squad previews as a noop.

    `move()` reaches `check`, which answers `same`, and the outcome reads "already
    there" — so classifying this as MOVE would reintroduce exactly the preview/outcome
    mismatch B1 removed, just via a different branch. Occupancy is still checked first:
    an occupied slot is POSITION_TAKEN even in your own squad, because move()'s local
    free-check short-circuits before the server is ever asked.
    """
    c, _ = make_client()
    # Grzegorz occupies Squad 1 position 1; position 3 is free in that same squad.
    plan = MovePlanner(c).plan([GRZEGORZ], 1, position=3)
    assert plan.moves[0].kind == NOOP
    assert plan.actionable() == []


def test_occupied_explicit_position_beats_the_noop_check(make_client):
    """Ordering guard: Grzegorz's own occupied slot is POSITION_TAKEN, not NOOP —
    move() returns "taken (slot occupied)" locally without contacting the server."""
    c, _ = make_client()
    plan = MovePlanner(c).plan([GRZEGORZ], 1, position=1)
    assert plan.moves[0].kind == POSITION_TAKEN
