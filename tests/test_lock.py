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


def test_report_does_not_toggle_the_lock(make_client):
    """`--dry-run` is documented as printing the plan without executing; toggling
    the lock is a real mutation the tool never undoes, so report() must not."""
    c, rsps = make_client(locked=False)
    _add_lock(rsps)
    report = LockManager().report(c)
    assert report.final is LockState.UNLOCKED
    assert report.locked_by_this_run is False
    assert not any("/lock" in call.request.url for call in rsps.calls)


def test_report_passes_through_an_existing_lock(make_client):
    c, rsps = make_client(locked=True)
    report = LockManager().report(c)
    assert report.final is LockState.LOCKED
    assert report.locked_by_this_run is False
