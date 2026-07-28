"""BulkMover: checkpoint+audit layered over move_many (O5, F4/NF5/NF6, implementation.md §3.6)."""
from __future__ import annotations

import json

import pytest
import responses

from practiscore_squads.audit import AuditLog
from practiscore_squads.bulk import BulkMover
from practiscore_squads.checkpoint import Checkpoint
from practiscore_squads.errors import SessionExpiredError
from practiscore_squads.planner import ADD, MovePlan, PlannedMove

from tests._data import ANATOLI, BASE, GRZEGORZ, SQUAD3, check_re

THIRD = 9808999


def _added(rsps, shooter, num=3):
    rsps.add(responses.POST, check_re(SQUAD3, shooter),
             body=f'{{"cmd":"added","num":{num}}}', content_type="text/html")


def _plan(*shooter_ids: int) -> MovePlan:
    return MovePlan(target_squad=3, moves=[
        PlannedMove(sid, f"#{sid}", None, 3, ADD) for sid in shooter_ids
    ])


def _mover(client, tmp_path, *, notify=False):
    checkpoint = Checkpoint("test-reverse-engineer", 3, notify=notify, dir=tmp_path / "ck")
    audit = AuditLog("test-reverse-engineer", client.roster(), notify=notify,
                     dir=tmp_path / "audit")
    return BulkMover(client, checkpoint, audit), checkpoint, audit


def test_clean_finish_clears_checkpoint_and_writes_audit(make_client, tmp_path):
    c, rsps = make_client()
    _added(rsps, GRZEGORZ)
    _added(rsps, ANATOLI)
    mover, checkpoint, audit = _mover(c, tmp_path)
    outcomes = mover.run(_plan(GRZEGORZ, ANATOLI))
    assert len(outcomes) == 2
    assert all(o.ok for o in outcomes)
    assert not checkpoint.path.exists(), "clean finish must clear the checkpoint"
    assert len(audit.path.read_text(encoding="utf-8").splitlines()) == 2


def test_batch_fatal_raise_leaves_checkpoint_intact(make_client, tmp_path):
    """NF2/NF6: a session-expiry mid-run must not clear the checkpoint, and prior
    successes must already be recorded in it so a resume can skip them."""
    c, rsps = make_client()
    _added(rsps, GRZEGORZ)
    rsps.add(responses.POST, check_re(SQUAD3, ANATOLI), status=302,
             headers={"Location": f"{BASE}/login"})
    rsps.add(responses.GET, f"{BASE}/login", body="<html>login</html>", status=200)
    mover, checkpoint, audit = _mover(c, tmp_path)

    with pytest.raises(SessionExpiredError):
        mover.run(_plan(GRZEGORZ, ANATOLI))

    assert checkpoint.path.exists(), "batch-fatal must NOT clear the checkpoint"
    reloaded = Checkpoint("test-reverse-engineer", 3, dir=tmp_path / "ck")
    assert reloaded.load() == {GRZEGORZ}
    # The audit trail covers the attempt that happened before the abort.
    lines = audit.path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["shooter_id"] == GRZEGORZ


def test_resume_skips_checkpointed_shooters(make_client, tmp_path):
    """A second run reusing the same checkpoint must not re-request an already-done shooter."""
    c, rsps = make_client()
    checkpoint = Checkpoint("test-reverse-engineer", 3, dir=tmp_path / "ck")
    checkpoint.record(GRZEGORZ)
    _added(rsps, ANATOLI)
    audit = AuditLog("test-reverse-engineer", c.roster(), dir=tmp_path / "audit")
    mover = BulkMover(c, checkpoint, audit)

    outcomes = mover.run(_plan(GRZEGORZ, ANATOLI))
    assert {o.shooter_id for o in outcomes} == {ANATOLI}
    assert not any(str(GRZEGORZ) in call.request.url
                   for call in rsps.calls if "/squads/check/" in call.request.url)
    assert not checkpoint.path.exists()


def test_on_progress_callback_forwarded(make_client, tmp_path):
    c, rsps = make_client()
    _added(rsps, GRZEGORZ)
    seen = []
    checkpoint = Checkpoint("test-reverse-engineer", 3, dir=tmp_path / "ck")
    audit = AuditLog("test-reverse-engineer", c.roster(), dir=tmp_path / "audit")
    mover = BulkMover(c, checkpoint, audit,
                      on_progress=lambda oc, i, total: seen.append((oc.shooter_id, i, total)))
    mover.run(_plan(GRZEGORZ))
    assert seen == [(GRZEGORZ, 1, 1)]
