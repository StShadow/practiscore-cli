"""Lock orchestration (NF7, implementation.md §3.6).

Wraps `SquadClient.ensure_locked()` into a reportable result for the CLI.
Never auto-unlocks — that decision is left entirely to the operator.
"""
from __future__ import annotations

from dataclasses import dataclass

from .client import SquadClient
from .models import LockState


@dataclass(frozen=True)
class LockReport:
    final: LockState
    locked_by_this_run: bool


class LockManager:
    def ensure(self, client: SquadClient) -> LockReport:
        locked_now = client.ensure_locked()
        return LockReport(final=LockState.LOCKED, locked_by_this_run=locked_now)
