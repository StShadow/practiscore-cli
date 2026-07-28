"""HTML/JSON parsing (implementation.md §3.4)."""
from __future__ import annotations

import re
import time

from bs4 import BeautifulSoup

from .errors import ServerError, SquaddingError
from .http import Parsed
from .models import LockState, MatchSnapshot, Shooter, Slot

_SLOT_ID_RE = re.compile(r"^squad_(\d+)_(\d+)_(\d+)$")
_SCHEDULE_ID_RE = re.compile(r"^toggle_schedule_(\d+)$")


class BootstrapParser:
    def parse(self, html: str, slug: str) -> MatchSnapshot:
        soup = BeautifulSoup(html, "lxml")

        csrf_tag = soup.select_one('meta[name="csrf-token"]')
        csrf = csrf_tag["content"] if csrf_tag else ""

        slots: list[Slot] = []
        match_id = 0
        for tag in soup.select('input[id^="squad_"]'):
            m = _SLOT_ID_RE.match(tag.get("id", ""))
            if not m:
                continue
            squad_id, position, mid = (int(g) for g in m.groups())
            match_id = mid
            rel = tag.get("rel")
            squad_no = int(rel) if rel is not None else squad_id
            value = (tag.get("value") or "").strip()
            occupant = value or None
            reserved = tag.get("placeholder") == "reserved"
            disabled = tag.has_attr("disabled")
            slots.append(Slot(
                squad_id=squad_id, position=position, match_id=mid,
                squad_no=squad_no, occupant=occupant,
                reserved=reserved, disabled=disabled,
            ))

        lock_btn = soup.select_one("#lockSquadding")
        lock = LockState.UNLOCKED
        if lock_btn is not None:
            classes = lock_btn.get("class") or []
            if "btn-danger" in classes:
                lock = LockState.LOCKED
            elif "btn-primary" in classes:
                lock = LockState.UNLOCKED

        schedule_ids: list[int] = []
        for tag in soup.select('[id^="toggle_schedule_"]'):
            m = _SCHEDULE_ID_RE.match(tag.get("id", ""))
            if m:
                schedule_ids.append(int(m.group(1)))

        return MatchSnapshot(
            slug=slug, match_id=match_id, csrf=csrf, lock=lock,
            slots=tuple(slots), schedule_ids=tuple(schedule_ids),
            fetched_at=time.monotonic(),
        )


class SearchParser:
    def parse(self, parsed: Parsed) -> list[Shooter]:
        if parsed.status == 500:
            raise ServerError(f"search failed: {parsed.text}")
        if parsed.status == 404:
            raise SquaddingError(f"search route requires a query segment: {parsed.text}")
        if parsed.status != 200:
            raise SquaddingError(f"unexpected search response ({parsed.status}): {parsed.text}")
        data = parsed.json or []
        return [
            Shooter(
                id=item["id"],
                name=(item.get("name") or "").strip(),
                email=item.get("email") or "",
                division=item.get("shDiv") or None,
                klass=item.get("shClass") or None,
            )
            for item in data
        ]
