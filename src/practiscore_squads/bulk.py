"""BulkMover — thin checkpoint+audit wrapper over `SquadClient.move_many` (F4/NF5/NF6,
implementation.md §3.6).

The loop, pacing, and continue-and-report semantics live in the core
(`SquadClient.move_many`); this layer only adds the two disk-backed concerns
the core refuses to know about.
"""
from __future__ import annotations

from collections.abc import Callable

from .audit import AuditLog
from .checkpoint import Checkpoint
from .client import SquadClient
from .models import MoveOutcome
from .planner import MovePlan


class BulkMover:
    def __init__(self, client: SquadClient, checkpoint: Checkpoint, audit: AuditLog,
                 on_progress: Callable[[MoveOutcome, int, int], None] | None = None):
        self.client = client
        self.checkpoint = checkpoint
        self.audit = audit
        self.on_progress = on_progress

    def run(self, plan: MovePlan, *, notify: bool = False) -> list[MoveOutcome]:
        done = self.checkpoint.load()  # resume (NF6)
        ids = [pm.shooter_id for pm in plan.actionable()]

        def _progress(oc: MoveOutcome, i: int, total: int) -> None:
            # Runs per attempt, BEFORE any batch-fatal raise from move_many — so a
            # run that aborts still leaves a complete checkpoint + audit trail.
            self.audit.write(oc)  # emails included (NF8)
            if oc.ok:
                self.checkpoint.record(oc.shooter_id)
            if self.on_progress:
                self.on_progress(oc, i, total)

        outcomes = self.client.move_many(
            ids, plan.target_squad, notify=notify, skip=done, on_progress=_progress,
        )
        self.checkpoint.clear()  # clean finish only
        return outcomes
