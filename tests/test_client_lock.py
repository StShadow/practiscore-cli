"""Lock toggle & ensure-locked orchestration (NF7, §3.7)."""
from __future__ import annotations

import pytest
import responses

from practiscore_squads.errors import ServerError, UnexpectedResponseError

from tests._data import MATCH_ID, bodies_for, lock_url, path_called


def _add_lock(rsps):
    rsps.add(responses.POST, lock_url(), json={"success": True}, content_type="application/json")


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
