"""TableFormatter / JsonFormatter (U2, NF3/NF9, implementation.md §3.7)."""
from __future__ import annotations

import io
import json

from rich.console import Console

from practiscore_squads.formatting import JsonFormatter, ShooterRow, TableFormatter
from practiscore_squads.lock import LockReport
from practiscore_squads.models import LockState, MoveOutcome, Shooter
from practiscore_squads.parsing import BootstrapParser
from practiscore_squads.planner import ADD, MOVE, MovePlan, NOOP, PlannedMove

from tests._data import ANATOLI, GRZEGORZ, SLUG, SQUAD1, build_bootstrap, build_squad

SHOOTER_WITH_EMAIL = Shooter(id=GRZEGORZ, name="Grzegorz Brzęczyszczykiewicz",
                              email="grzegorz@example.invalid", division="Production", klass=None)
ANATOLI_SHOOTER = Shooter(id=ANATOLI, name="Anatoli Putseyeu", email="anatoli@example.invalid",
                           division="Standard", klass=None)


def _snapshot():
    return BootstrapParser().parse(build_bootstrap(), SLUG)


def _table_output(fn) -> str:
    buf = io.StringIO()
    console = Console(file=buf, no_color=True, width=200)
    fn(TableFormatter(console))
    return buf.getvalue()


def _json_output(fn) -> str:
    buf = io.StringIO()
    fn(JsonFormatter(buf))
    return buf.getvalue()


# --------------------------------- squads() -------------------------------- #
def test_squads_json_shape():
    snapshot = _snapshot()
    out = _json_output(lambda f: f.squads(snapshot))
    rows = json.loads(out)
    assert {r["squad_no"] for r in rows} == {1, 2, 3}
    row1 = next(r for r in rows if r["squad_no"] == 1)
    assert row1 == {"squad_no": 1, "name": "Squad 1", "capacity": 5, "occupied": 1, "free": 4}


def test_squads_free_count_excludes_reserved_and_disabled_slots():
    """`free` must agree with `Slot.free` / `SquadClient.free_slots()`. Deriving it
    as `capacity - occupied` counted reserved and disabled slots as available and
    invited a bulk move that `move()` then refused as "squad full"."""
    html = build_bootstrap(extra_squads="")
    html = html.replace(
        build_squad(SQUAD1, {1: ("Grzegorz Brzęczyszczykiewicz ", "Production")}),
        build_squad(SQUAD1, {1: ("Grzegorz Brzęczyszczykiewicz ", "Production")},
                    reserved={2}, disabled={3}),
    )
    snapshot = BootstrapParser().parse(html, SLUG)
    row1 = next(r for r in json.loads(_json_output(lambda f: f.squads(snapshot)))
                if r["squad_no"] == 1)
    assert row1["capacity"] == 5
    assert row1["occupied"] == 1
    assert row1["free"] == 2  # positions 4 and 5 only — not 2 (reserved) or 3 (disabled)


def test_squads_table_contains_expected_values():
    snapshot = _snapshot()
    out = _table_output(lambda f: f.squads(snapshot))
    assert "Squad 1" in out
    assert "1/5" in out
    assert "4" in out


# -------------------------------- shooters() ------------------------------- #
def test_shooters_json_shape():
    rows = [ShooterRow(SHOOTER_WITH_EMAIL, 1), ShooterRow(ANATOLI_SHOOTER, None)]
    out = _json_output(lambda f: f.shooters(rows))
    data = json.loads(out)
    assert data == [
        {"id": GRZEGORZ, "name": "Grzegorz Brzęczyszczykiewicz", "division": "Production",
         "class": None, "squad_no": 1},
        {"id": ANATOLI, "name": "Anatoli Putseyeu", "division": "Standard",
         "class": None, "squad_no": None},
    ]


def test_shooters_json_never_includes_email():
    rows = [ShooterRow(SHOOTER_WITH_EMAIL, 1)]
    out = _json_output(lambda f: f.shooters(rows))
    assert "example.invalid" not in out
    assert "email" not in out


def test_shooters_table_never_includes_email():
    rows = [ShooterRow(SHOOTER_WITH_EMAIL, 1)]
    out = _table_output(lambda f: f.shooters(rows))
    assert "example.invalid" not in out
    assert "Grzegorz" in out


# ---------------------------------- plan() --------------------------------- #
def _sample_plan() -> MovePlan:
    return MovePlan(target_squad=3, moves=[
        PlannedMove(GRZEGORZ, "Grzegorz", 1, 3, MOVE),
        PlannedMove(9808999, "Nova", None, 3, ADD),
        PlannedMove(ANATOLI, "Anatoli", 2, 2, NOOP),
    ])


def test_plan_json_shape():
    plan = _sample_plan()
    out = _json_output(lambda f: f.plan(plan))
    data = json.loads(out)
    assert data["target_squad"] == 3
    assert len(data["moves"]) == 3
    assert data["moves"][0] == {
        "shooter_id": GRZEGORZ, "shooter_name": "Grzegorz",
        "from_squad": 1, "to_squad": 3, "kind": MOVE,
    }


def test_plan_table_mentions_each_move():
    plan = _sample_plan()
    out = _table_output(lambda f: f.plan(plan))
    assert "Grzegorz" in out
    assert "Nova" in out
    assert "Anatoli" in out


# -------------------------------- outcomes() ------------------------------- #
def _sample_outcomes() -> list[MoveOutcome]:
    return [
        MoveOutcome(GRZEGORZ, True, 1, 3, "moved"),
        MoveOutcome(ANATOLI, False, None, 3, "taken"),
    ]


def test_outcomes_json_shape():
    out = _json_output(lambda f: f.outcomes(_sample_outcomes()))
    data = json.loads(out)
    assert data[0] == {"shooter_id": GRZEGORZ, "ok": True, "from_squad": 1,
                       "to_squad": 3, "detail": "moved", "error": None}
    assert data[1]["ok"] is False


def test_outcomes_table_summary_line():
    out = _table_output(lambda f: f.outcomes(_sample_outcomes()))
    assert "Moved 1" in out
    assert "Failed 0" in out


# ---------------------------------- lock() --------------------------------- #
def test_lock_json_shape():
    report = LockReport(final=LockState.LOCKED, locked_by_this_run=True)
    out = _json_output(lambda f: f.lock(report))
    data = json.loads(out)
    assert data == {"final": "locked", "locked_by_this_run": True}


def test_lock_table_mentions_locked_by_this_run():
    report = LockReport(final=LockState.LOCKED, locked_by_this_run=True)
    out = _table_output(lambda f: f.lock(report))
    assert "LOCKED" in out
    assert "locked by this run" in out


def test_lock_table_mentions_already_locked():
    report = LockReport(final=LockState.LOCKED, locked_by_this_run=False)
    out = _table_output(lambda f: f.lock(report))
    assert "already locked" in out


def test_lock_table_does_not_claim_locked_when_unlocked():
    """LockManager.report() (dry run) can hand back UNLOCKED. The old suffix logic
    printed "UNLOCKED (already locked)" — self-contradictory, and it read as though
    the run had left the match protected when it had not."""
    report = LockReport(final=LockState.UNLOCKED, locked_by_this_run=False)
    out = _table_output(lambda f: f.lock(report))
    assert "UNLOCKED" in out
    assert "already locked" not in out
