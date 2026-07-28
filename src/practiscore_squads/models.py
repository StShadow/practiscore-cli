"""Domain types (spec §5.1, implementation.md §3.1). Frozen dataclasses only."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Cmd(StrEnum):
    ADDED = "added"
    TAKEN = "taken"
    SAME = "same"
    MOVE = "move"


class LockState(StrEnum):
    LOCKED = "locked"
    UNLOCKED = "unlocked"


@dataclass(frozen=True)
class Slot:
    squad_id: int
    position: int
    match_id: int
    squad_no: int
    occupant: str | None
    reserved: bool = False
    disabled: bool = False
    # Locally set the moment our own write commits — we only have a shooter_id
    # at that point, not a name, so `occupant` (scraped display name; matched
    # by squad_members()) can't honestly carry it. Never scraped from the page.
    claimed: bool = False

    @property
    def free(self) -> bool:
        return (self.occupant is None and not self.reserved
                and not self.disabled and not self.claimed)

    def as_squad(self) -> str:
        return f"squad_{self.squad_id}_{self.position}_{self.match_id}"

    def as_spot(self) -> str:
        return f"spot_{self.squad_id}_{self.position}_{self.match_id}"

    def as_clear(self) -> str:
        return f"clearSpot_{self.squad_id}_{self.position}_{self.match_id}"


@dataclass(frozen=True)
class Shooter:
    id: int
    name: str
    email: str
    division: str | None
    klass: str | None

    def __repr__(self) -> str:
        return f"Shooter(id={self.id}, name={self.name!r})"

    def to_audit_dict(self) -> dict:
        """The ONLY place email is exposed (NF8/NF9)."""
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "division": self.division,
            "class": self.klass,
        }


@dataclass(frozen=True)
class MoveOutcome:
    shooter_id: int
    ok: bool
    from_squad: int | None
    to_squad: int | None
    detail: str
    error: Exception | None = None


@dataclass(frozen=True)
class MatchSnapshot:
    """Everything scraped from one bootstrap page load (§3.1). Replaced wholesale on refresh()."""
    slug: str
    match_id: int
    csrf: str
    lock: LockState
    slots: tuple[Slot, ...]
    schedule_ids: tuple[int, ...]
    fetched_at: float

    def by_squad(self) -> dict[int, list[Slot]]:
        out: dict[int, list[Slot]] = {}
        for s in self.slots:
            out.setdefault(s.squad_no, []).append(s)
        for lst in out.values():
            lst.sort(key=lambda s: s.position)
        return out

    def squad_ids(self) -> dict[int, int]:
        out: dict[int, int] = {}
        for s in self.slots:
            out.setdefault(s.squad_no, s.squad_id)
        return out

    def slot(self, squad_no: int, position: int) -> Slot | None:
        for s in self.slots:
            if s.squad_no == squad_no and s.position == position:
                return s
        return None
