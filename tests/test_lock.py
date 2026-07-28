"""LockManager (O4, NF7, implementation.md §3.6)."""
from __future__ import annotations

import responses

from practiscore_squads.lock import LockManager
from practiscore_squads.models import LockState

from tests._data import lock_url


def _add_lock(rsps):
    rsps.add(responses.POST, lock_url(), json={"success": True}, content_type="application/json")


def test_ensure_locks_when_unlocked(make_client):
    c, rsps = make_client(locked=False)
    _add_lock(rsps)
    report = LockManager().ensure(c)
    assert report.final is LockState.LOCKED
    assert report.locked_by_this_run is True


def test_ensure_reports_already_locked(make_client):
    c, rsps = make_client(locked=True)
    _add_lock(rsps)
    report = LockManager().ensure(c)
    assert report.final is LockState.LOCKED
    assert report.locked_by_this_run is False
