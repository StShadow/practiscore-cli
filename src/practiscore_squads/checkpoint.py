"""Resumable bulk-move checkpoint (NF6, implementation.md §3.6/§7).

Pure filesystem — no network, no knowledge of `SquadClient`. Distinct from the
audit log (`audit.py`): the checkpoint exists only to make an interrupted
`move-bulk` resumable and is deleted on a clean finish, while the audit log is
a permanent record of every attempted move.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path


def default_checkpoint_dir() -> Path:
    """`~/.practiscore-squads/checkpoints`, falling back to the CWD if the home
    directory isn't writable (e.g. a locked-down service account)."""
    home_dir = Path.home() / ".practiscore-squads" / "checkpoints"
    try:
        home_dir.mkdir(parents=True, exist_ok=True)
        return home_dir
    except OSError:
        cwd_dir = Path.cwd() / ".practiscore-squads-checkpoints"
        cwd_dir.mkdir(parents=True, exist_ok=True)
        return cwd_dir


class Checkpoint:
    def __init__(self, slug: str, target_squad: int, notify: bool = False, *,
                 dir: Path | None = None):
        self.slug = slug
        self.target_squad = target_squad
        self.notify = notify
        self.dir = dir if dir is not None else default_checkpoint_dir()
        self.path = self.dir / f"{slug}-to{target_squad}.json"
        self._done: set[int] | None = None

    def _read(self) -> set[int]:
        if not self.path.exists():
            return set()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return set()
        # Guard (§7): only honour a checkpoint whose slug/target/notify match
        # this run — otherwise it belongs to a different batch and resuming
        # from it would silently skip shooters that were never moved here.
        if (data.get("slug") != self.slug
                or data.get("target_squad") != self.target_squad
                or data.get("notify") != self.notify):
            return set()
        return set(data.get("done", []))

    def load(self) -> set[int]:
        if self._done is None:
            self._done = self._read()
        return set(self._done)

    def record(self, shooter_id: int) -> None:
        done = self.load()
        self._done = done | {shooter_id}
        self.dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "slug": self.slug,
            "target_squad": self.target_squad,
            "notify": self.notify,
            "done": sorted(self._done),
            "updated": datetime.now(UTC).isoformat(),
        }
        self.path.write_text(json.dumps(payload), encoding="utf-8")

    def clear(self) -> None:
        self._done = set()
        self.path.unlink(missing_ok=True)
