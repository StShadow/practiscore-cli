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

    def report(self, client: SquadClient) -> LockReport:
        """Current lock state without touching it — for `--dry-run`, which is
        documented as printing the plan and exiting without executing. Toggling the
        lock is a real mutation (and one this tool never undoes), so a dry run
        reports what it found instead of locking the match on the operator's behalf.
        """
        return LockReport(final=client.snapshot.lock, locked_by_this_run=False)
