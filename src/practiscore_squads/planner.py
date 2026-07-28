"""MovePlanner — reviewable dry-run plan for move-bulk (NF5, implementation.md §3.6).

Pure aside from the reads it triggers on `client` (`refresh()`, `roster()`,
`free_slots()`); never mutates squadding state.
"""
from __future__ import annotations

from dataclasses import dataclass

from .client import SquadClient
from .errors import SlotNotFoundError

MOVE = "move"
ADD = "add"
NOOP = "noop(already there)"
BLOCKED = "blocked(no free slot)"


@dataclass(frozen=True)
class PlannedMove:
    shooter_id: int
    shooter_name: str
    from_squad: int | None
    to_squad: int
    kind: str  # "move" | "add" | "noop(already there)" | "blocked(no free slot)"


@dataclass(frozen=True)
class MovePlan:
    target_squad: int
    moves: list[PlannedMove]

    def actionable(self) -> list[PlannedMove]:
        return [m for m in self.moves if m.kind in (MOVE, ADD)]


def name_to_squad_map(client: SquadClient) -> dict[str, int]:
    """§3.5/D6: a shooter's current squad, correlated by OCCUPANT NAME — the only
    signal the bootstrap page exposes. Same-named shooters mis-attribute."""
    mapping: dict[str, int] = {}
    for slot in client.snapshot.slots:
        if slot.occupant:
            mapping.setdefault(slot.occupant, slot.squad_no)
    return mapping


class MovePlanner:
    def __init__(self, client: SquadClient):
        self.client = client

    def plan(self, shooter_ids: list[int], squad_no: int) -> MovePlan:
        self.client.refresh()
        if squad_no not in self.client.snapshot.squad_ids():
            raise SlotNotFoundError(f"squad {squad_no} not found")

        roster = {s.id: s for s in self.client.roster()}
        name_to_squad = name_to_squad_map(self.client)

        # Free-slot budget decremented as actionable moves are provisionally
        # assigned, mirroring `move_many`'s pre-assignment so the plan's
        # move/blocked split matches what a real run would do.
        free_budget = len(self.client.free_slots(squad_no))

        moves: list[PlannedMove] = []
        for sid in shooter_ids:
            shooter = roster.get(sid)
            name = shooter.name if shooter else f"#{sid}"
            current = name_to_squad.get(shooter.name) if shooter else None

            if current == squad_no:
                moves.append(PlannedMove(sid, name, current, squad_no, NOOP))
                continue

            if free_budget <= 0:
                moves.append(PlannedMove(sid, name, current, squad_no, BLOCKED))
                continue

            free_budget -= 1
            kind = MOVE if current is not None else ADD
            moves.append(PlannedMove(sid, name, current, squad_no, kind))

        return MovePlan(target_squad=squad_no, moves=moves)
