"""Exception hierarchy (spec §5.4)."""
from __future__ import annotations

from practiscore_squads.errors import (
    AuthError,
    NotAuthorizedError,
    ServerError,
    SessionExpiredError,
    SlotNotFoundError,
    SquaddingError,
    ThrottledError,
    TransportError,
    UnexpectedResponseError,
)


def test_all_inherit_base():
    for exc in (AuthError, NotAuthorizedError, SlotNotFoundError, ServerError,
                ThrottledError, TransportError, UnexpectedResponseError):
        assert issubclass(exc, SquaddingError)


def test_session_expired_is_auth_error():
    """NF2: expiry is a specialization of AuthError so callers can catch either."""
    assert issubclass(SessionExpiredError, AuthError)
    assert issubclass(SessionExpiredError, SquaddingError)


def test_batch_fatal_errors_are_not_auth_errors():
    """`move_many` re-raises AuthError and ThrottledError but records everything else,
    so the two batch-fatal families must stay distinguishable (NF2/NF6)."""
    assert not issubclass(ThrottledError, AuthError)
    assert not issubclass(TransportError, AuthError)


def test_transport_error_is_not_throttled():
    """A dropped connection is a different failure mode from rate limiting: the first
    is recorded per item, the second is batch-fatal."""
    assert not issubclass(TransportError, ThrottledError)
