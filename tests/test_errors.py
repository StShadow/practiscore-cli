"""Exception hierarchy (spec §5.4)."""
from __future__ import annotations

from practiscore_squads.errors import (
    AlreadyInSquadError,
    AuthError,
    NotAuthorizedError,
    ServerError,
    SessionExpiredError,
    SlotNotFoundError,
    SlotTakenError,
    SlotUnavailableError,
    SquaddingError,
    UnexpectedResponseError,
)


def test_all_inherit_base():
    for exc in (AuthError, NotAuthorizedError, SlotTakenError, AlreadyInSquadError,
                SlotNotFoundError, SlotUnavailableError, ServerError, UnexpectedResponseError):
        assert issubclass(exc, SquaddingError)


def test_session_expired_is_auth_error():
    """NF2: expiry is a specialization of AuthError so callers can catch either."""
    assert issubclass(SessionExpiredError, AuthError)
    assert issubclass(SessionExpiredError, SquaddingError)


def test_slot_taken_carries_squad_number():
    err = SlotTakenError(2)
    assert err.num == 2
