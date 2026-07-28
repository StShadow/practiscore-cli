"""Exception hierarchy (spec §5.4)."""
from __future__ import annotations


class SquaddingError(Exception):
    """Base class for all library errors."""


class AuthError(SquaddingError):
    """No/invalid session on a gated route."""


class SessionExpiredError(AuthError):
    """Was authenticated, now redirected to /login mid-run (NF2)."""


class ThrottledError(SquaddingError):
    """Repeated 429/503/Cloudflare-block responses exhausted retries."""


class TransportError(SquaddingError):
    """Repeated connection errors/timeouts exhausted retries (implementation.md §3.3)."""


class NotAuthorizedError(SquaddingError):
    """removeask == 'noAuth' (unprivileged or unauthenticated session)."""


class SlotNotFoundError(SquaddingError):
    """squad_no/position not present in the scraped slot set (guards §6.8)."""


class InvalidMatchError(SquaddingError):
    """A `--match`/config value looked like a URL but didn't match the squadding pattern."""


# NOTE: `taken`, `same`, and `move` are control flow, not faults — they surface as
# MoveOutcome(ok=...) so single and bulk paths return the same objects (spec §5.2).
# The exception forms of those states were never raised and have been removed.


class ServerError(SquaddingError):
    """500 {"message": "Server Error"}."""


class UnexpectedResponseError(SquaddingError):
    """A response body didn't match the documented contract (e.g. save() != 'moved')."""
