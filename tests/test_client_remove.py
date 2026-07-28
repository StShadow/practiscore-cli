"""Removal path: removeask permission probe + removeshooter (§3.5/§3.6).

`remove` is not a v1 CLI command but is part of the library core surface.
"""
from __future__ import annotations

import pytest
import responses

from practiscore_squads.errors import NotAuthorizedError, ServerError, SessionExpiredError

from tests._data import (
    BASE, SLUG, SQUAD1, bodies_for, path_called, removeask_re, removeshooter_url,
)


def test_can_remove_true_on_ask(make_client):
    c, rsps = make_client()
    rsps.add(responses.GET, removeask_re(), body="ask", content_type="text/html")
    assert c.can_remove() is True


def test_can_remove_false_on_noauth(make_client):
    c, rsps = make_client()
    rsps.add(responses.GET, removeask_re(), body="noAuth", content_type="text/html")
    assert c.can_remove() is False


def test_remove_issues_removeshooter_with_spot_prefix(make_client):
    """§3.6: removeshooter uses the `spot_` prefix and posts _token + page."""
    c, rsps = make_client()
    rsps.add(responses.GET, removeask_re(), body="ask", content_type="text/html")
    rsps.add(responses.POST, removeshooter_url(), status=302,
             headers={"Location": f"{BASE}/{SLUG}/squadding"})
    c.remove(1, 1)   # squad 1, position 1
    body = bodies_for(rsps, "/squads/removeshooter")[0]
    assert f"spot_{SQUAD1}_1_" in body
    assert "_token=" in body
    assert "page=" in body


def test_remove_refuses_when_not_authorized(make_client):
    """removeask == noAuth → NotAuthorizedError, and NO removeshooter call."""
    c, rsps = make_client()
    rsps.add(responses.GET, removeask_re(), body="noAuth", content_type="text/html")
    with pytest.raises(NotAuthorizedError):
        c.remove(1, 1)
    assert not path_called(rsps, "/squads/removeshooter")


# ------------- the removeshooter response is never inspected -------------- #
# `remove()` discards the POST result entirely, and `HttpClient.post()` returns
# early on any 3xx without running auth detection — so every outcome below is
# currently indistinguishable from a completed removal.
def test_remove_raises_when_redirected_to_login(make_client):
    """§3.6 says treat any 3xx as success — but a 302 to /login is a dead session,
    not a completed removal (NF2). The success redirect targets the squadding
    page, so the Location is what separates the two."""
    c, rsps = make_client()
    rsps.add(responses.GET, removeask_re(), body="ask", content_type="text/html")
    rsps.add(responses.POST, removeshooter_url(), status=302,
             headers={"Location": f"{BASE}/login"})
    with pytest.raises(SessionExpiredError):
        c.remove(1, 1)


def test_remove_raises_on_server_error(make_client):
    """A 500 is not a 3xx and must never be reported as a successful removal."""
    c, rsps = make_client()
    rsps.add(responses.GET, removeask_re(), body="ask", content_type="text/html")
    rsps.add(responses.POST, removeshooter_url(),
             json={"message": "Server Error"}, status=500)
    with pytest.raises(ServerError):
        c.remove(1, 1)
