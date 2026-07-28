"""Domain model behavior (spec §5.1, implementation.md §3.1)."""
from __future__ import annotations

import pytest

from practiscore_squads import Cmd, LockState, MoveOutcome, Shooter, Slot
from practiscore_squads.models import MatchSnapshot

from tests._data import MATCH_ID, SQUAD1, SQUAD3


# --------------------------- Slot ----------------------------------------- #
def _slot(pos=1, squad_id=SQUAD1, squad_no=1, occupant=None, reserved=False, disabled=False):
    return Slot(squad_id=squad_id, position=pos, match_id=MATCH_ID, squad_no=squad_no,
                occupant=occupant, reserved=reserved, disabled=disabled)


def test_slot_prefix_rendering():
    """Same slot renders three different prefixes per endpoint (§2.2)."""
    s = _slot(pos=1)
    assert s.as_squad() == f"squad_{SQUAD1}_1_{MATCH_ID}"
    assert s.as_spot() == f"spot_{SQUAD1}_1_{MATCH_ID}"
    assert s.as_clear() == f"clearSpot_{SQUAD1}_1_{MATCH_ID}"


def test_slot_free_when_empty():
    assert _slot(occupant=None).free is True


@pytest.mark.parametrize("kwargs", [
    {"occupant": "Someone"},
    {"reserved": True},
    {"disabled": True},
])
def test_slot_not_free(kwargs):
    assert _slot(**kwargs).free is False


# --------------------------- Shooter -------------------------------------- #
def test_shooter_repr_hides_email():
    """NF9: email must never leak through repr/str."""
    sh = Shooter(id=1, name="Jane Doe", email="jane@example.invalid",
                 division="Open", klass="A")
    assert "example.invalid" not in repr(sh)
    assert "example.invalid" not in str(sh)
    assert "Jane Doe" in repr(sh)


def test_shooter_audit_dict_includes_email():
    """The audit path (NF8) is the ONLY place email is exposed."""
    sh = Shooter(id=1, name="Jane Doe", email="jane@example.invalid",
                 division="Open", klass="A")
    d = sh.to_audit_dict()
    assert d["email"] == "jane@example.invalid"
    assert d["id"] == 1


# --------------------------- Enums ---------------------------------------- #
def test_cmd_values():
    assert {c.value for c in Cmd} == {"added", "taken", "same", "move"}


def test_lockstate_values():
    assert LockState.LOCKED.value == "locked"
    assert LockState.UNLOCKED.value == "unlocked"


# --------------------------- MoveOutcome ---------------------------------- #
def test_move_outcome_fields():
    oc = MoveOutcome(shooter_id=1, ok=True, from_squad=2, to_squad=3, detail="moved")
    assert oc.ok and oc.from_squad == 2 and oc.to_squad == 3 and oc.error is None


# --------------------------- MatchSnapshot -------------------------------- #
def _snapshot():
    slots = tuple(
        Slot(squad_id=sid, position=p, match_id=MATCH_ID, squad_no=no, occupant=None)
        for sid, no in ((SQUAD1, 1), (SQUAD3, 3))
        for p in range(1, 6)
    )
    return MatchSnapshot(slug="s", match_id=MATCH_ID, csrf="c", lock=LockState.UNLOCKED,
                         slots=slots, schedule_ids=(1,), fetched_at=0.0)


def test_snapshot_by_squad_and_ids():
    snap = _snapshot()
    by = snap.by_squad()
    assert set(by) == {1, 3}
    assert len(by[1]) == 5
    assert snap.squad_ids() == {1: SQUAD1, 3: SQUAD3}


def test_snapshot_slot_lookup():
    snap = _snapshot()
    assert snap.slot(1, 3).position == 3
    assert snap.slot(1, 99) is None
