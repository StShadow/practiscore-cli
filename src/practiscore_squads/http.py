"""HTTP transport (implementation.md §3.3): session, headers, CSRF, retry, auth/throttle detection.

Knows nothing about squads/slots/shooters — that's `client.py`'s job.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import requests

from .errors import SessionExpiredError, ThrottledError, TransportError
from .pacing import Pacer

BASE_URL = "https://practiscore.com"

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_THROTTLE_STATUSES = (429, 503)


def _read_at_file(value: str) -> str:
    """Supports the NF1 `@path` convention for pasting a cookie via a file."""
    if value.startswith("@"):
        with open(value[1:], encoding="utf-8") as fh:
            return fh.read().strip()
    return value


def _parse_cookie_header(value: str) -> dict[str, str]:
    """Split a pasted `Cookie:` header value into individual name/value pairs."""
    pairs: dict[str, str] = {}
    for part in value.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, _, val = part.partition("=")
        pairs[name.strip()] = val.strip()
    return pairs


@dataclass(frozen=True)
class Parsed:
    """Body/status wrapper that never trusts Content-Type (spec §5.5)."""
    status: int
    json: Any
    text: str


def _to_parsed(resp: requests.Response) -> Parsed:
    text = resp.text
    data = None
    if text:
        try:
            data = json.loads(text)
        except ValueError:
            data = None
    return Parsed(status=resp.status_code, json=data, text=text)


def _looks_like_login_redirect(resp: requests.Response) -> bool:
    """True if a followed redirect landed on /login, or — with `allow_redirects=False`,
    where `resp.url` is still the *request* URL — the `Location` header points there.
    Both are the same NF2 signal: session expired mid-request (§3.6)."""
    target = resp.url
    if 300 <= resp.status_code < 400:
        location = resp.headers.get("Location")
        if location:
            target = location
    return target.split("?", 1)[0].rstrip("/").endswith("/login")


class HttpClient:
    def __init__(self, session: requests.Session, base: str = BASE_URL,
                 pacer: Pacer | None = None):
        self.session = session
        self.base = base.rstrip("/")
        self.pacer = pacer or Pacer()

    def __repr__(self) -> str:
        # NF1/NF9: never leak the session cookie via repr.
        return f"HttpClient(base={self.base!r})"

    @classmethod
    def from_cookie(cls, cookie: str, base: str = BASE_URL,
                    pacer: Pacer | None = None) -> HttpClient:
        session = requests.Session()
        session.headers.update({
            "User-Agent": _BROWSER_UA,
            "X-Requested-With": "XMLHttpRequest",
        })
        # Parsed into the cookie jar (not a static "Cookie" header) so a
        # `Set-Cookie` the server sends back — e.g. a rotated session id —
        # updates the jar and is carried on the next request (C5). The domain
        # must match the host a Set-Cookie response will be scoped to, or the
        # rotated cookie lands as a second, distinct jar entry instead of
        # replacing this one — both would then be sent, stale one included.
        domain = urlparse(base).hostname or ""
        for name, val in _parse_cookie_header(_read_at_file(cookie)).items():
            session.cookies.set(name, val, domain=domain)
        return cls(session, base=base, pacer=pacer)

    def _url(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        return f"{self.base}{path}"

    def _send(self, method: str, path: str, *, data=None, headers=None,
              allow_redirects: bool = True, max_attempts: int = 4,
              retry_throttle: bool = True) -> requests.Response:
        url = self._url(path)
        attempt = 0
        while True:
            attempt += 1
            self.pacer.wait()
            try:
                resp = self.session.request(
                    method, url, data=data, headers=headers,
                    allow_redirects=allow_redirects, timeout=30,
                )
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
                # implementation.md §3.3: connection error/timeout is retryable on the
                # same budget as 429/503; exhausting it must not escape the hierarchy.
                if attempt < max_attempts:
                    self.pacer.penalize(attempt)
                    continue
                raise TransportError(
                    f"{method} {path} failed after {attempt} attempts"
                ) from exc
            # requests defaults to Latin-1 for text/* bodies with no charset param
            # (RFC 2616 default); the site is UTF-8 throughout (NF11 — Cyrillic,
            # Polish diacritics), so force decoding accordingly.
            resp.encoding = "utf-8"
            if retry_throttle and resp.status_code in _THROTTLE_STATUSES:
                if attempt < max_attempts:
                    self.pacer.penalize(attempt)
                    continue
                raise ThrottledError(
                    f"{method} {path} exhausted retries after {attempt} attempts "
                    f"(status {resp.status_code})"
                )
            return resp

    def get(self, path: str, *, headers: dict | None = None) -> Parsed:
        resp = self._send("GET", path, headers=headers)
        self._detect_auth(resp)
        return _to_parsed(resp)

    def post(self, path: str, *, data: dict | None = None, csrf: str | None = None,
             headers: dict | None = None, allow_redirects: bool = True,
             retry_throttle: bool = True) -> Parsed:
        """`retry_throttle=False` returns a 429/503 to the caller instead of retrying.

        The default is right for `check`/`save`, whose replays are harmless (a repeat
        lands on `same`/`moved`). It is wrong for `removeshooter`, where a 503 has been
        observed *on a successful* removal (§3.6) — retrying there re-POSTs a mutation
        against a status that never meant failure.
        """
        hdrs = dict(headers or {})
        if csrf:
            hdrs["X-CSRF-TOKEN"] = csrf
        resp = self._send("POST", path, data=data, headers=hdrs,
                          allow_redirects=allow_redirects, retry_throttle=retry_throttle)
        # Auth detection must run before the early-return below: with allow_redirects=False
        # a 3xx to /login (dead session) looks identical to a 3xx success redirect unless
        # we inspect it here (§3.6).
        self._detect_auth(resp)
        if not allow_redirects and 300 <= resp.status_code < 400:
            return Parsed(status=resp.status_code, json=None, text=resp.text)
        return _to_parsed(resp)

    def get_bootstrap(self, slug: str) -> str:
        resp = self._send("GET", f"/{slug}/squadding")
        self._detect_auth(resp)
        return resp.text

    def _detect_auth(self, resp: requests.Response) -> None:
        if _looks_like_login_redirect(resp):
            raise SessionExpiredError("session expired — redirected to /login")
        if resp.status_code in (403,) and "cloudflare" in resp.text.lower():
            raise ThrottledError("blocked by Cloudflare")
