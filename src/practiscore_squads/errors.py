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


class SlotTakenError(SquaddingError):
    """cmd == 'taken' — the target slot is already occupied."""

    def __init__(self, num: int):
        super().__init__(f"slot already taken (squad {num})")
        self.num = num


class AlreadyInSquadError(SquaddingError):
    """cmd == 'same' — shooter is already in the requested squad."""

    def __init__(self, num: int):
        super().__init__(f"shooter already in squad {num}")
        self.num = num


class MoveRequiresConfirmationError(SquaddingError):
    """cmd == 'move' and the caller disabled the confirming save()."""

    def __init__(self, origin: int):
        super().__init__(f"move requires confirmation (currently in squad {origin})")
        self.origin = origin


class SlotNotFoundError(SquaddingError):
    """squad_no/position not present in the scraped slot set (guards §6.8)."""


class SlotUnavailableError(SquaddingError):
    """Target slot is reserved or disabled."""


class ServerError(SquaddingError):
    """500 {"message": "Server Error"}."""


class UnexpectedResponseError(SquaddingError):
    """A response body didn't match the documented contract (e.g. save() != 'moved')."""
