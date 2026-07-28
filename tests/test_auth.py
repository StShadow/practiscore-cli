"""Authentication & session handling (NF1/NF2)."""
from __future__ import annotations

import pytest
import responses

from practiscore_squads import SquadClient
from practiscore_squads.errors import SessionExpiredError

from tests._data import BASE, COOKIE, SLUG, bootstrap_url, build_bootstrap, registered_re, ROSTER


@responses.activate
def test_from_cookie_sends_cookie_header():
    """NF1: the pasted cookie is attached to every request."""
    responses.add(responses.GET, bootstrap_url(), body=build_bootstrap(), content_type="text/html")
    SquadClient.from_cookie(COOKIE, SLUG)
    sent = responses.calls[0].request.headers.get("Cookie", "")
    assert "laravel_session=sess" in sent


@responses.activate
def test_from_cookie_sends_ajax_header():
    """spec §5.5: X-Requested-With turns error pages into JSON bodies."""
    responses.add(responses.GET, bootstrap_url(), body=build_bootstrap(), content_type="text/html")
    SquadClient.from_cookie(COOKIE, SLUG)
    assert responses.calls[0].request.headers.get("X-Requested-With") == "XMLHttpRequest"


@responses.activate
def test_bootstrap_redirect_to_login_raises_expired():
    """NF2: a 302 → /login means the session is dead."""
    responses.add(responses.GET, bootstrap_url(), status=302, headers={"Location": f"{BASE}/login"})
    responses.add(responses.GET, f"{BASE}/login", body="<html>login</html>", status=200)
    with pytest.raises(SessionExpiredError):
        SquadClient.from_cookie(COOKIE, SLUG)


@responses.activate
def test_cookie_never_appears_in_repr():
    """NF1/NF9: the cookie value must not leak via repr()."""
    responses.add(responses.GET, bootstrap_url(), body=build_bootstrap(), content_type="text/html")
    c = SquadClient.from_cookie(COOKIE, SLUG)
    assert "laravel_session" not in repr(c)
    assert "cf_clearance" not in repr(c)
