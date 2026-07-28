"""Output rendering (NF3, implementation.md §3.7): rich tables by default, `--json` for machines.

Every renderer omits `Shooter.email` (NF9) — nothing in this module ever reads
that attribute; only `id`/`name`/`division`/`klass` are surfaced.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from typing import Protocol, TextIO

from rich.console import Console
from rich.table import Table

from .lock import LockReport
from .models import MatchSnapshot, MoveOutcome, Shooter
from .planner import MovePlan


@dataclass(frozen=True)
class ShooterRow:
    """A roster shooter enriched with its current displayed squad number.

    `Formatter.shooters` needs this per-row correlation for the `squads`
    column (§5.3 sample table / `--json` shape), which plain `Shooter` doesn't
    carry. Correlated by occupant name, same best-effort limits as
    `SquadClient.squad_members()` (D6) — same-named shooters can mis-attribute.
    """
    shooter: Shooter
    squad_no: int | None


class Formatter(Protocol):
    def squads(self, snapshot: MatchSnapshot) -> None: ...
    def shooters(self, rows: list[ShooterRow], squad_no: int | None) -> None: ...
    def plan(self, plan: MovePlan) -> None: ...
    def outcomes(self, outcomes: list[MoveOutcome]) -> None: ...
    def lock(self, report: LockReport) -> None: ...


def squad_dicts(snapshot: MatchSnapshot) -> list[dict]:
    rows = []
    for squad_no, slots in sorted(snapshot.by_squad().items()):
        occupied = sum(1 for s in slots if s.occupant is not None)
        capacity = len(slots)
        rows.append({
            "squad_no": squad_no,
            "name": f"Squad {squad_no}",
            "capacity": capacity,
            "occupied": occupied,
            "free": capacity - occupied,
        })
    return rows


def shooter_dicts(rows: list[ShooterRow]) -> list[dict]:
    return [
        {
            "id": row.shooter.id,
            "name": row.shooter.name,
            "division": row.shooter.division,
            "class": row.shooter.klass,
            "squad_no": row.squad_no,
        }
        for row in rows
    ]


def plan_dict(plan: MovePlan) -> dict:
    return {
        "target_squad": plan.target_squad,
        "moves": [
            {
                "shooter_id": m.shooter_id,
                "shooter_name": m.shooter_name,
                "from_squad": m.from_squad,
                "to_squad": m.to_squad,
                "kind": m.kind,
            }
            for m in plan.moves
        ],
    }


def outcome_dicts(outcomes: list[MoveOutcome]) -> list[dict]:
    return [
        {
            "shooter_id": o.shooter_id,
            "ok": o.ok,
            "from_squad": o.from_squad,
            "to_squad": o.to_squad,
            "detail": o.detail,
            "error": str(o.error) if o.error else None,
        }
        for o in outcomes
    ]


def lock_dict(report: LockReport) -> dict:
    return {"final": str(report.final), "locked_by_this_run": report.locked_by_this_run}


class TableFormatter:
    """Human-readable rich tables (NF3 default)."""

    def __init__(self, console: Console | None = None):
        self.console = console or Console()

    def squads(self, snapshot: MatchSnapshot) -> None:
        table = Table()
        table.add_column("Squad")
        table.add_column("Name")
        table.add_column("Occupied")
        table.add_column("Free")
        for row in squad_dicts(snapshot):
            table.add_row(str(row["squad_no"]), row["name"],
                          f"{row['occupied']}/{row['capacity']}", str(row["free"]))
        self.console.print(table)

    def shooters(self, rows: list[ShooterRow], squad_no: int | None) -> None:
        table = Table()
        table.add_column("ID")
        table.add_column("Name")
        table.add_column("Div")
        table.add_column("Squad")
        for row in rows:
            table.add_row(str(row.shooter.id), row.shooter.name,
                          row.shooter.division or "", str(row.squad_no or ""))
        self.console.print(table)

    def plan(self, plan: MovePlan) -> None:
        for m in plan.moves:
            origin = f"Squad {m.from_squad}" if m.from_squad is not None else "unsquadded"
            self.console.print(
                f"#{m.shooter_id} {m.shooter_name}: {origin} -> Squad {m.to_squad} ({m.kind})"
            )
        actionable = len(plan.actionable())
        self.console.print(f"{actionable} of {len(plan.moves)} shooter(s) will be moved/added")

    def outcomes(self, outcomes: list[MoveOutcome]) -> None:
        moved = sum(1 for o in outcomes if o.ok and o.detail in ("moved", "added"))
        already = sum(1 for o in outcomes if o.ok and o.detail == "already there")
        blocked = sum(1 for o in outcomes if not o.ok and o.error is None)
        failed = sum(1 for o in outcomes if not o.ok and o.error is not None)
        self.console.print(
            f"Moved {moved}  •  Already there {already}  •  "
            f"Blocked/taken {blocked}  •  Failed {failed}"
        )
        for o in outcomes:
            if not o.ok:
                self.console.print(f"  #{o.shooter_id}: {o.detail}")

    def lock(self, report: LockReport) -> None:
        suffix = "(locked by this run)" if report.locked_by_this_run else "(already locked)"
        self.console.print(f"Lock: {report.final.value.upper()} {suffix}")


class JsonFormatter:
    """Machine-readable `--json` output (NF3): one `json.dump` per call."""

    def __init__(self, stream: TextIO | None = None):
        self.stream = stream or sys.stdout

    def _dump(self, data) -> None:
        json.dump(data, self.stream)
        self.stream.write("\n")

    def squads(self, snapshot: MatchSnapshot) -> None:
        self._dump(squad_dicts(snapshot))

    def shooters(self, rows: list[ShooterRow], squad_no: int | None) -> None:
        self._dump(shooter_dicts(rows))

    def plan(self, plan: MovePlan) -> None:
        self._dump(plan_dict(plan))

    def outcomes(self, outcomes: list[MoveOutcome]) -> None:
        self._dump(outcome_dicts(outcomes))

    def lock(self, report: LockReport) -> None:
        self._dump(lock_dict(report))
