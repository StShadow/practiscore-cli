"""Lock toggle & ensure-locked orchestration (NF7, §3.7)."""
from __future__ import annotations

import pytest
import responses

from practiscore_squads.errors import ServerError, UnexpectedResponseError

from tests._data import (
    CSRF, MATCH_ID, bodies_for, bootstrap_url, build_bootstrap, lock_url, path_called,
)

NEW_CSRF = "REFRESHEDCSRF0000000000000000000000TEST"


def _add_lock(rsps):
    rsps.add(responses.POST, lock_url(), json={"success": True}, content_type="application/json")


def _lock_calls(rsps):
    return [c for c in rsps.calls if "/lock" in c.request.url]


def _bootstrap_call_count(rsps) -> int:
    return sum(1 for c in rsps.calls if c.request.url.rstrip("/").endswith("/squadding"))


def test_toggle_lock_returns_new_state(make_client):
    """From unlocked, toggling reports the new (locked) state; body carries matchId."""
    c, rsps = make_client(locked=False)
    _add_lock(rsps)
    new_state = c.toggle_lock()
    assert new_state is True
    assert f"matchId={MATCH_ID}" in bodies_for(rsps, "/lock")[0]


def test_ensure_locked_locks_when_unlocked(make_client):
    c, rsps = make_client(locked=False)
    _add_lock(rsps)
    locked_now = c.ensure_locked()
    assert locked_now is True
    assert path_called(rsps, "/lock")


def test_ensure_locked_noop_when_already_locked(make_client):
    """Idempotent guard: never toggle an already-locked match (toggle is not a setter)."""
    c, rsps = make_client(locked=True)
    _add_lock(rsps)
    locked_now = c.ensure_locked()
    assert locked_now is False
    assert not path_called(rsps, "/lock")


# ---------------- believe the toggle only when it actually succeeded ------- #
# Local lock state is flipped optimistically today, so a rejected toggle leaves
# the client convinced the match is locked when it is not.
def test_toggle_lock_raises_on_server_error(make_client):
    """A 500 must not be reported as a successful lock, and must not flip state."""
    c, rsps = make_client(locked=False)
    rsps.add(responses.POST, lock_url(), json={"message": "Server Error"}, status=500)
    with pytest.raises(ServerError):
        c.toggle_lock()
    assert c.is_locked() is False


def test_toggle_lock_requires_success_payload(make_client):
    """§3.7/A12: the endpoint answers {"success":true}; anything else means the
    toggle did not happen, so local state must not flip."""
    c, rsps = make_client(locked=False)
    rsps.add(responses.POST, lock_url(), json={"success": False},
             content_type="application/json")
    with pytest.raises(UnexpectedResponseError):
        c.toggle_lock()
    assert c.is_locked() is False


def test_ensure_locked_never_claims_a_lock_it_did_not_take(make_client):
    """NF7: the run's lock-status line is printed from this call — reporting
    LOCKED over an unlocked match is the worst available outcome."""
    c, rsps = make_client(locked=False)
    rsps.add(responses.POST, lock_url(), json={"message": "Server Error"}, status=500)
    with pytest.raises(ServerError):
        c.ensure_locked()
    assert c.is_locked() is False


# -------------------- B4: 419 refresh-and-retry, mirroring _check_and_save -- #
def test_toggle_lock_retries_once_on_419(make_client):
    """§3.3: a stale CSRF token (419) triggers exactly one re-refresh + retry.

    The retried POST must carry the NEW token scraped by that refresh, not the
    stale one from the original snapshot — a naive retry that resends the old
    `self.snapshot.csrf` captured before the refresh would just 419 again.
    """
    c, rsps = make_client(locked=False)
    rsps.add(responses.POST, lock_url(), status=419, body="")
    rsps.add(responses.GET, bootstrap_url(),
             body=build_bootstrap(locked=False).replace(CSRF, NEW_CSRF),
             content_type="text/html")
    _add_lock(rsps)

    new_state = c.toggle_lock()

    assert new_state is True
    assert _bootstrap_call_count(rsps) == 2, "the stale token must force exactly one re-scrape"
    calls = _lock_calls(rsps)
    assert len(calls) == 2, "expected the original 419 attempt plus one retry"
    assert calls[1].request.headers.get("X-CSRF-TOKEN") == NEW_CSRF


def test_toggle_lock_does_not_retry_a_second_419(make_client):
    """Guarded by the same one-shot flag as _check_and_save: a second consecutive
    419 (token still bad, or some other persistent fault) must raise rather than
    loop forever re-refreshing."""
    c, rsps = make_client(locked=False)
    rsps.add(responses.POST, lock_url(), status=419, body="")
    rsps.add(responses.GET, bootstrap_url(), body=build_bootstrap(locked=False),
             content_type="text/html")
    rsps.add(responses.POST, lock_url(), status=419, body="")

    with pytest.raises(UnexpectedResponseError, match="419"):
        c.toggle_lock()
    assert len(_lock_calls(rsps)) == 2, "must not retry past the second 419"
    assert c.is_locked() is False
