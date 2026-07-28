"""Shared test constants, fixtures HTML/JSON, and URL matchers.

Deliberately imports NOTHING from ``practiscore_squads`` so it can be loaded even
before the package exists. All values mirror the live sandbox documented in
``spec.md`` (match ``test-reverse-engineer``, ``matchId=351459``), with emails
replaced by ``@example.invalid`` so this file is safe to commit.
"""
from __future__ import annotations

import re

BASE = "https://practiscore.com"
SLUG = "test-reverse-engineer"
MATCH_ID = 351459

SQUAD1 = 1458603  # displayed "Squad 1"
SQUAD2 = 1458604  # displayed "Squad 2"
SQUAD3 = 1458605  # displayed "Squad 3"
SQUAD_NO = {SQUAD1: 1, SQUAD2: 2, SQUAD3: 3}
NO_SQUAD = {v: k for k, v in SQUAD_NO.items()}

GRZEGORZ = 9808574  # Squad 1, Production
ANATOLI = 9808577  # Squad 2, Standard

CSRF = "TESTCSRF0000000000000000000000000000TEST"
SCHEDULE_ID = 340383
COOKIE = "XSRF-TOKEN=tok; laravel_session=sess; cf_clearance=cf"

# Roster as returned by GET /squads/registered (§3.2). Names carry TRAILING
# whitespace on purpose (§3.2) — the parser must strip it.
ROSTER = [
    {"id": GRZEGORZ, "name": "Grzegorz Brzęczyszczykiewicz ", "email": "grzegorz@example.invalid",
     "shDiv": "Production", "shClass": ""},
    {"id": ANATOLI, "name": "Anatoli Putseyeu ", "email": "anatoli@example.invalid",
     "shDiv": "Standard", "shClass": ""},
]


# --------------------------------------------------------------------------- #
# Bootstrap HTML builder (§3.1)                                                #
# --------------------------------------------------------------------------- #
def _slot(squad_id: int, pos: int, name: str = "", div: str | None = None,
          reserved: bool = False, disabled: bool = False) -> str:
    title = ""
    if name.strip():
        title = f"{name.strip()} ({div})" if div else name.strip()
    attrs = [
        f'id="squad_{squad_id}_{pos}_{MATCH_ID}"',
        f'rel="{SQUAD_NO[squad_id]}"',
        f'value="{name}"',
        f'data-original-title="{title}"',
    ]
    if reserved:
        attrs.append('placeholder="reserved"')
    if disabled:
        attrs.append("disabled")
    return f"    <input {' '.join(attrs)}>"


def build_squad(squad_id: int, occupants: dict[int, tuple[str, str]] | None = None,
                reserved: set[int] | None = None, disabled: set[int] | None = None,
                slots: int = 5) -> str:
    occupants = occupants or {}
    reserved = reserved or set()
    disabled = disabled or set()
    rows = [f'  <div class="squadBox"><strong id="squadBox_{squad_id}">Squad {SQUAD_NO[squad_id]}</strong>']
    for pos in range(1, slots + 1):
        name, div = occupants.get(pos, ("", None))
        rows.append(_slot(squad_id, pos, name, div, pos in reserved, pos in disabled))
    rows.append("  </div>")
    return "\n".join(rows)


def build_bootstrap(locked: bool = False, *, extra_squads: str = "") -> str:
    """Render a realistic squadding page. Default = live sandbox initial layout."""
    if locked:
        lock_btn = '<button id="lockSquadding" class="btn btn-xs btn-danger">Unlock Squadding</button>'
    else:
        lock_btn = '<button id="lockSquadding" class="btn btn-xs btn-primary">Lock Squadding</button>'
    squads = "\n".join([
        build_squad(SQUAD1, {1: ("Grzegorz Brzęczyszczykiewicz ", "Production")}),
        build_squad(SQUAD2, {1: ("Anatoli Putseyeu ", "Standard")}),
        build_squad(SQUAD3),
    ]) + extra_squads
    return f"""<!doctype html>
<html><head>
  <meta name="csrf-token" content="{CSRF}">
</head><body>
  <input type="hidden" name="_token" value="{CSRF}">
  {lock_btn}
  <div id="toggle_schedule_{SCHEDULE_ID}" class="squadding">
{squads}
  </div>
</body></html>"""


# --------------------------------------------------------------------------- #
# URL helpers / matchers for the `responses` library                          #
# --------------------------------------------------------------------------- #
def bootstrap_url() -> str:
    return f"{BASE}/{SLUG}/squadding"


def lock_url() -> str:
    return f"{BASE}/matches/{SLUG}/lock"


def removeshooter_url() -> str:
    return f"{BASE}/squads/removeshooter"


def registered_re() -> re.Pattern:
    return re.compile(rf"{re.escape(BASE)}/squads/registered/.+")


def removeask_re() -> re.Pattern:
    return re.compile(rf"{re.escape(BASE)}/squads/removeask\b.*")


def check_re(squad_id: int, shooter: int, pos: str = r"\d+") -> re.Pattern:
    return re.compile(rf"{re.escape(BASE)}/squads/check/squad_{squad_id}_{pos}_{MATCH_ID}/{shooter}\b")


def save_re(squad_id: int, shooter: int, pos: str = r"\d+") -> re.Pattern:
    return re.compile(rf"{re.escape(BASE)}/squads/save/squad_{squad_id}_{pos}_{MATCH_ID}/{shooter}\b")


# --------------------------------------------------------------------------- #
# Assertion helpers over responses.calls                                       #
# --------------------------------------------------------------------------- #
def called_urls(rsps) -> list[str]:
    return [c.request.url for c in rsps.calls]


def path_called(rsps, needle: str) -> bool:
    return any(needle in u for u in called_urls(rsps))


def bodies_for(rsps, needle: str) -> list[str]:
    return [(c.request.body or "") for c in rsps.calls if needle in c.request.url]
