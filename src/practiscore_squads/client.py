"""SquadClient — library core (spec §5.2, implementation.md §3.5)."""
from __future__ import annotations

import dataclasses
import re
import time
from collections.abc import Callable
from urllib.parse import quote

from .errors import (
    AuthError,
    InvalidMatchError,
    NotAuthorizedError,
    ServerError,
    SlotNotFoundError,
    SquaddingError,
    ThrottledError,
    UnexpectedResponseError,
)
from .http import HttpClient
from .models import Cmd, LockState, MatchSnapshot, MoveOutcome, Shooter, Slot
from .pacing import Pacer
from .parsing import BootstrapParser, SearchParser

_MATCH_URL_RE = re.compile(r"^https?://[^/]+/([^/?#]+)/squadding/?.*$", re.IGNORECASE)
_URL_RE = re.compile(r"^https?://", re.IGNORECASE)

# Local claims (Slot.claimed) keep auto-pick honest about this process's own writes,
# but they can't see another admin re-squadding concurrently. The squadding UI polls
# at 120s (§3.8), so matching that bounds how stale our view can get without paying a
# bootstrap fetch per move (~300 shooters would double the request count).
SNAPSHOT_TTL = 120.0


def parse_match_slug(value: str) -> str:
    """Accept a bare slug or a full squadding URL (F0); reject anything else URL-shaped.

    A malformed URL (e.g. missing `/squadding`) must not be passed through as a
    literal "slug" — that would silently become a nonsense request path like
    `/https://practiscore.com/my-match/squadding` (C3).
    """
    value = value.strip()
    m = _MATCH_URL_RE.match(value)
    if m:
        return m.group(1)
    if _URL_RE.match(value):
        raise InvalidMatchError(
            f"{value!r} looks like a URL but doesn't match "
            "https://practiscore.com/{slug}/squadding"
        )
    return value


class SquadClient:
    def __init__(self, http: HttpClient, slug: str, *, snapshot_ttl: float = SNAPSHOT_TTL):
        self.http = http
        self.slug = slug
        self.snapshot: MatchSnapshot | None = None
        self.snapshot_ttl = snapshot_ttl

    def __repr__(self) -> str:
        return f"SquadClient(slug={self.slug!r})"

    # --- construction / auth (NF1) --------------------------------------- #
    @classmethod
    def from_cookie(cls, cookie: str, match: str, *, pacer: Pacer | None = None) -> SquadClient:
        slug = parse_match_slug(match)
        http = HttpClient.from_cookie(cookie, pacer=pacer)
        client = cls(http, slug)
        client.refresh()
        return client

    # --- discovery (F0/F1/F2) --------------------------------------------- #
    @property
    def match_id(self) -> int:
        return self.snapshot.match_id

    def refresh(self) -> None:
        html = self.http.get_bootstrap(self.slug)
        self.snapshot = BootstrapParser().parse(html, self.slug)

    def _refresh_if_stale(self) -> None:
        """Re-scrape when the snapshot has outlived its TTL (§4.1 "if snapshot stale").

        Drops accumulated `claimed` flags, which is correct — a fresh scrape is server
        truth and outranks local bookkeeping about writes the server already has.
        """
        if time.monotonic() - self.snapshot.fetched_at >= self.snapshot_ttl:
            self.refresh()

    def squads(self) -> dict[int, list[Slot]]:
        return self.snapshot.by_squad()

    def free_slots(self, squad_no: int | None = None) -> list[Slot]:
        slots = self.snapshot.slots
        if squad_no is not None:
            slots = [s for s in slots if s.squad_no == squad_no]
        return [s for s in slots if s.free]

    def is_locked(self) -> bool:
        return self.snapshot.lock is LockState.LOCKED

    def _any_slot(self) -> Slot:
        return self.snapshot.slots[0]

    def _claim_slot(self, slot: Slot) -> None:
        """Mark `slot` non-free in the snapshot after a write commits (NF10 post-state).

        Without this, auto-pick keeps re-offering a slot it just filled itself —
        the second `move()` into the same squad would come back 'taken' purely
        from a stale read, not a real server conflict.
        """
        claimed = dataclasses.replace(slot, claimed=True)
        new_slots = tuple(claimed if s.squad_no == slot.squad_no and s.position == slot.position
                           else s for s in self.snapshot.slots)
        self.snapshot = dataclasses.replace(self.snapshot, slots=new_slots)

    def search(self, q: str, literal: bool = True) -> list[Shooter]:
        if literal:
            escaped = q.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
            segment = quote(escaped, safe="")
        else:
            segment = q
        path = f"/squads/registered/{self._any_slot().as_squad()}/{segment}"
        parsed = self.http.get(path)
        return SearchParser().parse(parsed)

    def roster(self) -> list[Shooter]:
        return self.search("%20", literal=False)

    def squad_members(self, squad_no: int) -> list[Shooter]:
        occupants = {
            s.occupant for s in self.snapshot.slots
            if s.squad_no == squad_no and s.occupant
        }
        if not occupants:
            return []
        return [s for s in self.roster() if s.name in occupants]

    # --- single mutation (F3) --------------------------------------------- #
    def move(self, shooter_id: int, squad_no: int,
             position: int | None = None, notify: bool = False) -> MoveOutcome:
        self._refresh_if_stale()
        squad_ids = self.snapshot.squad_ids()
        if squad_no not in squad_ids:
            raise SlotNotFoundError(f"squad {squad_no} not found")

        if position is not None:
            slot = self.snapshot.slot(squad_no, position)
            if slot is None:
                raise SlotNotFoundError(
                    f"squad {squad_no} position {position} was not scraped from the "
                    "current page — refusing to fabricate a slot address (§6.8)"
                )
            if not slot.free:
                return MoveOutcome(shooter_id=shooter_id, ok=False, from_squad=None,
                                    to_squad=squad_no, detail="taken (slot occupied)")
        else:
            candidates = sorted(self.snapshot.by_squad()[squad_no], key=lambda s: s.position)
            slot = next((s for s in candidates if s.free), None)
            if slot is None:
                return MoveOutcome(shooter_id=shooter_id, ok=False, from_squad=None,
                                    to_squad=squad_no, detail="blocked: squad full")

        return self._check_and_save(shooter_id, slot, squad_no, notify)

    def add(self, shooter_id: int, squad_no: int,
            position: int | None = None, notify: bool = False) -> MoveOutcome:
        return self.move(shooter_id, squad_no, position=position, notify=notify)

    def _check_and_save(self, shooter_id: int, slot: Slot, squad_no: int, notify: bool,
                         _retried_419: bool = False) -> MoveOutcome:
        parsed = self.http.post(
            f"/squads/check/{slot.as_squad()}/{shooter_id}",
            data={"email": "1" if notify else "0"},
            csrf=self.snapshot.csrf,
        )

        if parsed.status == 419 and not _retried_419:
            self.refresh()
            slot = self.snapshot.slot(slot.squad_no, slot.position) or slot
            return self._check_and_save(shooter_id, slot, squad_no, notify, _retried_419=True)

        if parsed.status == 500:
            raise ServerError(f"check() failed: {parsed.text}")

        if not isinstance(parsed.json, dict) or "cmd" not in parsed.json:
            raise UnexpectedResponseError(f"unexpected check() response: {parsed.text!r}")

        cmd = parsed.json["cmd"]
        num = parsed.json.get("num")

        if cmd == Cmd.ADDED.value:
            self._claim_slot(slot)
            return MoveOutcome(shooter_id=shooter_id, ok=True, from_squad=None,
                                to_squad=squad_no, detail="added")
        if cmd == Cmd.SAME.value:
            return MoveOutcome(shooter_id=shooter_id, ok=True, from_squad=squad_no,
                                to_squad=squad_no, detail="already there")
        if cmd == Cmd.TAKEN.value:
            return MoveOutcome(shooter_id=shooter_id, ok=False, from_squad=None,
                                to_squad=num, detail="taken")
        if cmd == Cmd.MOVE.value:
            origin = num
            save_parsed = self.http.post(
                f"/squads/save/{slot.as_squad()}/{shooter_id}",
                data={"send": "yes" if notify else "no"},
                csrf=self.snapshot.csrf,
            )
            if save_parsed.text.strip() != "moved":
                raise UnexpectedResponseError(
                    f"save() returned unexpected body: {save_parsed.text!r}"
                )
            self._claim_slot(slot)
            return MoveOutcome(shooter_id=shooter_id, ok=True, from_squad=origin,
                                to_squad=squad_no, detail="moved")

        raise UnexpectedResponseError(f"unknown check() cmd: {cmd!r}")

    # --- bulk (F4, NF5/NF6) ------------------------------------------------ #
    def move_many(self, shooter_ids: list[int], squad_no: int, *,
                  notify: bool = False,
                  on_progress: Callable[[MoveOutcome, int, int], None] | None = None,
                  skip: set[int] | None = None) -> list[MoveOutcome]:
        skip = skip or set()
        squad_ids = self.snapshot.squad_ids()
        if squad_no not in squad_ids:
            raise SlotNotFoundError(f"squad {squad_no} not found")
        # `free` is scraped from the live snapshot, so it already excludes whatever
        # `skip` occupies (a resumed shooter's earlier write is server truth by the
        # time this snapshot was fetched). Slots are therefore handed out by each
        # `todo` item's own position among the *remaining* work — indexing by
        # position in the original `shooter_ids` list instead would run out of
        # range as soon as more shooters were done than slots remained, wrongly
        # reporting the rest as "blocked: squad full" on every non-trivial resume.
        free = sorted((s for s in self.snapshot.by_squad()[squad_no] if s.free),
                      key=lambda s: s.position)

        todo = [sid for sid in shooter_ids if sid not in skip]
        total = len(todo)
        outcomes: list[MoveOutcome] = []
        for i, sid in enumerate(todo):
            done = i + 1
            try:
                if i < len(free):
                    oc = self.move(sid, squad_no, position=free[i].position, notify=notify)
                else:
                    oc = MoveOutcome(shooter_id=sid, ok=False, from_squad=None,
                                      to_squad=squad_no, detail="blocked: squad full")
            except (AuthError, ThrottledError):
                # Batch-fatal, not per-item (NF5/NF6): a dead session can't recover,
                # and rate limiting only gets worse if every remaining shooter burns
                # another retry budget against it. Prior outcomes have already gone
                # to on_progress, so the caller can resume from its checkpoint.
                raise
            except SquaddingError as exc:
                oc = MoveOutcome(shooter_id=sid, ok=False, from_squad=None,
                                  to_squad=squad_no, detail=str(exc), error=exc)
            outcomes.append(oc)
            if on_progress:
                on_progress(oc, done, total)
        return outcomes

    # --- lock orchestration (NF7) ------------------------------------------ #
    def toggle_lock(self, *, _retried_419: bool = False) -> bool:
        parsed = self.http.post(
            f"/matches/{self.slug}/lock",
            data={"matchId": self.snapshot.match_id},
            csrf=self.snapshot.csrf,
        )

        if parsed.status == 419:
            # Same one-shot recovery as _check_and_save (§3.3). Safe to replay because
            # the endpoint is a *pure* toggle (§3.7) and a 419 never reached the toggle
            # logic — so state is unchanged and the retry flips whatever the server
            # holds now. Everything below reads the post-refresh snapshot, which is why
            # a concurrent admin's flip is reflected rather than reported wrongly.
            if _retried_419:
                raise UnexpectedResponseError(
                    "lock() rejected the CSRF token twice (419) — the session is no "
                    "longer usable for writes even after a re-scrape"
                )
            self.refresh()
            return self.toggle_lock(_retried_419=True)

        if parsed.status == 500:
            raise ServerError(f"lock toggle failed: {parsed.text}")
        # §3.7/A12: only {"success": true} confirms the toggle happened — anything
        # else (false, non-JSON, missing key) must not flip local state (NF7).
        if not isinstance(parsed.json, dict) or parsed.json.get("success") is not True:
            raise UnexpectedResponseError(f"unexpected lock() response: {parsed.text!r}")
        new_lock = (LockState.LOCKED if self.snapshot.lock is LockState.UNLOCKED
                    else LockState.UNLOCKED)
        self.snapshot = dataclasses.replace(self.snapshot, lock=new_lock)
        return new_lock is LockState.LOCKED

    def ensure_locked(self) -> bool:
        if self.snapshot.lock is LockState.LOCKED:
            return False
        self.toggle_lock()
        return True

    # --- removal (kept from API map; not a v1 CLI command) ------------------ #
    def can_remove(self) -> bool:
        slot = self._any_slot()
        parsed = self.http.get(f"/squads/removeask?info={slot.as_clear()}")
        return parsed.text.strip() == "ask"

    def remove(self, squad_no: int, position: int) -> None:
        squad_ids = self.snapshot.squad_ids()
        if squad_no not in squad_ids:
            raise SlotNotFoundError(f"squad {squad_no} not found")
        slot = self.snapshot.slot(squad_no, position)
        if slot is None:
            # removeshooter tolerates arbitrary/out-of-range positions — it's the
            # documented cleanup path for the hidden-overflow hazard (§3.3/§6.8/A15-A16).
            slot = Slot(squad_id=squad_ids[squad_no], position=position,
                        match_id=self.snapshot.match_id, squad_no=squad_no, occupant=None)

        parsed = self.http.get(f"/squads/removeask?info={slot.as_clear()}")
        if parsed.text.strip() != "ask":
            raise NotAuthorizedError("removeask denied removal for this session")

        page = f"{self.http.base}/{self.slug}/squadding"
        parsed = self.http.post(
            "/squads/removeshooter",
            data={"_token": self.snapshot.csrf, "info": slot.as_spot(), "page": page},
            allow_redirects=False,
            # A 503 here is ambiguous, not transient (§3.6) — resolved below by
            # re-reading, never by re-POSTing the removal.
            retry_throttle=False,
        )
        # §3.6: a 3xx is the success signal (http.post() has already turned a
        # 3xx-to-/login into SessionExpiredError).
        if 300 <= parsed.status < 400:
            return
        if parsed.status == 503:
            # The one status the spec warns about: a *successful* removal was observed
            # reported as 503 by the edge while `fetch` saw the real 3xx. The status
            # can't distinguish that artifact from a genuine failure, so ask the server
            # what actually happened (spec §4 invariant 5).
            self.refresh()
            after = self.snapshot.slot(squad_no, position)
            # `None` == an out-of-range position that the page never renders — the
            # hidden-overflow cleanup path (§6.8/A16), where absence is all we can see.
            if after is None or after.occupant is None:
                return
            raise ServerError(
                f"removeshooter returned 503 and squad {squad_no} position {position} "
                "is still occupied — the removal did not take effect"
            )
        raise ServerError(f"removeshooter failed with status {parsed.status}")
