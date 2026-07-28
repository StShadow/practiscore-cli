"""Append-only audit log of every attempted move (NF8, implementation.md §3.6/§7).

Distinct from `checkpoint.py`: the checkpoint exists only to make a bulk run
resumable and is deleted on success; the audit log is a permanent record and
is never deleted by this library. Emails are included here **by the owner's
explicit choice** (NF8) — this is the one place in the whole codebase that is
allowed to persist a shooter's email (see `models.Shooter.to_audit_dict`).
"""
from __future__ import annotations

import csv
import io
import json
import os
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from .models import MoveOutcome, Shooter

_FIELDS = ["ts", "shooter_id", "name", "email", "from_squad", "to_squad", "outcome", "notify"]


def default_audit_dir() -> Path:
    audit_dir = Path.home() / ".practiscore-squads" / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    return audit_dir


def _chmod_owner_only(path: Path) -> None:
    """`chmod 600` on POSIX (NF8) — a no-op on platforms without POSIX permission bits."""
    if os.name == "posix":
        os.chmod(path, 0o600)


class AuditLog:
    def __init__(self, slug: str, roster: Iterable[Shooter] = (), *,
                 notify: bool = False, fmt: str = "jsonl", dir: Path | None = None):
        if fmt not in ("jsonl", "csv"):
            raise ValueError(f"unsupported audit format: {fmt!r}")
        self.slug = slug
        self.notify = notify
        self.format = fmt
        self.dir = dir if dir is not None else default_audit_dir()
        self.path = self.dir / f"{slug}.{fmt}"
        self._roster = {s.id: s for s in roster}

    def _record(self, outcome: MoveOutcome) -> dict:
        shooter = self._roster.get(outcome.shooter_id)
        return {
            "ts": datetime.now(UTC).isoformat(),
            "shooter_id": outcome.shooter_id,
            "name": shooter.name if shooter else None,
            "email": shooter.email if shooter else None,
            "from_squad": outcome.from_squad,
            "to_squad": outcome.to_squad,
            "outcome": outcome.detail,
            "notify": self.notify,
        }

    def write(self, outcome: MoveOutcome) -> None:
        record = self._record(outcome)
        self.dir.mkdir(parents=True, exist_ok=True)
        if self.format == "jsonl":
            self._append_jsonl(record)
        else:
            self._append_csv(record)
        _chmod_owner_only(self.path)

    def _append_jsonl(self, record: dict) -> None:
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _append_csv(self, record: dict) -> None:
        write_header = not self.path.exists() or self.path.stat().st_size == 0
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=_FIELDS)
        if write_header:
            writer.writeheader()
        writer.writerow(record)
        with self.path.open("a", encoding="utf-8", newline="") as fh:
            fh.write(buf.getvalue())
