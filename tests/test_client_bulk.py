"""Bulk move: continue-and-report, resume-skip, progress, expiry (F4/NF2/NF5/NF6)."""
from __future__ import annotations

import pytest
import requests
import responses

import practiscore_squads.pacing as pacing_mod
from practiscore_squads.errors import SessionExpiredError, ThrottledError

from tests._data import (
    ANATOLI, BASE, GRZEGORZ, SLUG, SQUAD3, bootstrap_url, build_bootstrap, build_squad, check_re,
    called_urls, path_called, save_re,
)

THIRD = 9808999  # a third shooter, used to prove a batch stopped early
FOURTH = 9808998


def _added(rsps, shooter, num=3):
    rsps.add(responses.POST, check_re(SQUAD3, shooter),
             body=f'{{"cmd":"added","num":{num}}}', content_type="text/html")


def test_move_many_returns_outcome_per_shooter(make_client):
    c, rsps = make_client()
    _added(rsps, GRZEGORZ)
    _added(rsps, ANATOLI)
    outcomes = c.move_many([GRZEGORZ, ANATOLI], 3)
    assert [o.shooter_id for o in outcomes] == [GRZEGORZ, ANATOLI]
    assert all(o.ok for o in outcomes)


def test_move_many_continue_and_report_on_failure(make_client):
    """NF5: one shooter's hard error must NOT abort the batch."""
    c, rsps = make_client()
    _added(rsps, GRZEGORZ)
    rsps.add(responses.POST, check_re(SQUAD3, ANATOLI),
             json={"message": "Server Error"}, status=500)   # ANATOLI fails
    outcomes = c.move_many([GRZEGORZ, ANATOLI], 3)
    assert len(outcomes) == 2
    by = {o.shooter_id: o for o in outcomes}
    assert by[GRZEGORZ].ok is True
    assert by[ANATOLI].ok is False
    assert by[ANATOLI].error is not None


def test_move_many_skips_checkpointed(make_client):
    """NF6: `skip` (resume) means finished shooters are not re-requested, and the
    remaining shooter is assigned whatever slot the live snapshot actually shows
    free (here, position 1 — Squad 3 is genuinely empty in this fixture) rather
    than a slot picked by its position in the original, pre-skip list."""
    c, rsps = make_client()
    _added(rsps, ANATOLI)
    outcomes = c.move_many([GRZEGORZ, ANATOLI], 3, skip={GRZEGORZ})
    assert not any(str(GRZEGORZ) in c_.request.url for c_ in rsps.calls if "/squads/check/" in c_.request.url)
    assert {o.shooter_id for o in outcomes if o.ok} == {ANATOLI}
    assert path_called(rsps, f"/squads/check/squad_{SQUAD3}_1_")


def test_move_many_resume_after_partial_fill_does_not_falsely_block(make_client):
    """Regression: a resumed run must assign slots by each remaining shooter's
    position among the *outstanding* work, not by its position in the original
    `shooter_ids` list.

    Squad 3 has 3 of 5 slots already filled (as if an earlier partial run
    already moved two of the four shooters below). Only GRZEGORZ/ANATOLI are
    in `skip` — their target-squad occupancy is irrelevant to the bug; what
    matters is that their *original indices* (0, 1) are lower than the 2
    remaining free slots. The old original-index scheme indexed into the
    (correctly shorter) `free` list using THIRD/FOURTH's original indices
    (2, 3), which fell outside `free` and produced a false
    "blocked: squad full" despite two slots being genuinely open.
    """
    c, rsps = make_client()
    filled = build_bootstrap().replace(
        build_squad(SQUAD3),
        build_squad(SQUAD3, occupants={
            1: ("Filler One", None), 2: ("Filler Two", None), 3: ("Filler Three", None),
        }),
    )
    rsps.add(responses.GET, bootstrap_url(), body=filled, content_type="text/html")
    c.refresh()

    _added(rsps, THIRD)
    _added(rsps, FOURTH)
    outcomes = c.move_many([GRZEGORZ, ANATOLI, THIRD, FOURTH], 3, skip={GRZEGORZ, ANATOLI})

    assert {o.shooter_id for o in outcomes} == {THIRD, FOURTH}
    assert all(o.ok for o in outcomes), outcomes
    assert all(o.detail == "added" for o in outcomes)


def test_move_many_progress_callback(make_client):
    """NF6: on_progress(outcome, done, total) drives the CLI bar."""
    c, rsps = make_client()
    _added(rsps, GRZEGORZ)
    _added(rsps, ANATOLI)
    seen = []
    c.move_many([GRZEGORZ, ANATOLI], 3,
                on_progress=lambda oc, done, total: seen.append((oc.shooter_id, done, total)))
    assert seen == [(GRZEGORZ, 1, 2), (ANATOLI, 2, 2)]


def test_move_many_session_expiry_bubbles(make_client):
    """NF2: a mid-run session expiry stops the loop so the CLI can pause & resume."""
    c, rsps = make_client()
    _added(rsps, GRZEGORZ)
    # ANATOLI's check redirects to /login → SessionExpiredError
    rsps.add(responses.POST, check_re(SQUAD3, ANATOLI), status=302,
             headers={"Location": f"{BASE}/login"})
    rsps.add(responses.GET, f"{BASE}/login", body="<html>login</html>", status=200)
    with pytest.raises(SessionExpiredError):
        c.move_many([GRZEGORZ, ANATOLI], 3)


def test_move_many_aborts_on_throttle(make_client, monkeypatch):
    """NF6: rate limiting is batch-fatal, not a per-item failure.

    `ThrottledError` is a SquaddingError, so continue-and-report (NF5) swallows it
    and grinds on — each remaining shooter burning a full retry budget with backoff
    against a server already saying stop (~15s each, ~75min over the spec's 300).
    Stop instead and let the caller resume from its checkpoint.
    """
    monkeypatch.setattr(pacing_mod.time, "sleep", lambda s: None)  # no real backoff
    c, rsps = make_client()
    _added(rsps, GRZEGORZ)
    rsps.add(responses.POST, check_re(SQUAD3, ANATOLI), body="rate limited", status=429)
    _added(rsps, THIRD)
    with pytest.raises(ThrottledError):
        c.move_many([GRZEGORZ, ANATOLI, THIRD], 3)
    checks = [u for u in called_urls(rsps) if "/squads/check/" in u]
    assert not any(str(THIRD) in u for u in checks), "batch must stop at the throttle"


def test_move_many_throttle_abort_keeps_earlier_progress(make_client, monkeypatch):
    """Aborting must not discard work already done — the CLI's resume checkpoint is
    built from on_progress, so prior successes have to be reported before the raise
    (same contract the NF2 session-expiry path relies on)."""
    monkeypatch.setattr(pacing_mod.time, "sleep", lambda s: None)
    c, rsps = make_client()
    _added(rsps, GRZEGORZ)
    rsps.add(responses.POST, check_re(SQUAD3, ANATOLI), body="rate limited", status=429)
    seen = []
    with pytest.raises(ThrottledError):
        c.move_many([GRZEGORZ, ANATOLI], 3,
                    on_progress=lambda oc, done, total: seen.append((oc.shooter_id, oc.ok)))
    assert seen == [(GRZEGORZ, True)]


def test_move_many_records_transport_failure_instead_of_aborting(make_client, monkeypatch):
    """NF5: only AuthError may abort a batch — everything else is reported.

    A `requests.ConnectionError` is not a SquaddingError, so the `except
    SquaddingError` guard doesn't catch it and one network blip at shooter 250
    destroys the whole run. Resume would soften this, but the checkpoint lives in
    the CLI layer, which doesn't exist yet.
    """
    monkeypatch.setattr(pacing_mod.time, "sleep", lambda s: None)  # no real backoff
    c, rsps = make_client()
    rsps.add(responses.POST, check_re(SQUAD3, GRZEGORZ),
             body=requests.exceptions.ConnectionError())
    _added(rsps, ANATOLI)
    outcomes = c.move_many([GRZEGORZ, ANATOLI], 3)
    assert [o.shooter_id for o in outcomes] == [GRZEGORZ, ANATOLI]
    by = {o.shooter_id: o for o in outcomes}
    assert by[GRZEGORZ].ok is False and by[GRZEGORZ].error is not None
    assert by[ANATOLI].ok is True, "a later shooter must still be attempted"
