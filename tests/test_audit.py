"""Audit log writer (O2, NF8, implementation.md §3.6/§7)."""
from __future__ import annotations

import csv
import json
import os

import pytest

from practiscore_squads.audit import AuditLog
from practiscore_squads.models import MoveOutcome, Shooter

GRZEGORZ = Shooter(id=9808574, name="Grzegorz Brzęczyszczykiewicz",
                   email="grzegorz@example.invalid", division="Production", klass=None)
ANATOLI = Shooter(id=9808577, name="Anatoli Putseyeu", email="anatoli@example.invalid",
                   division="Standard", klass=None)

MOVED = MoveOutcome(shooter_id=GRZEGORZ.id, ok=True, from_squad=2, to_squad=3, detail="moved")
TAKEN = MoveOutcome(shooter_id=ANATOLI.id, ok=False, from_squad=None, to_squad=3, detail="taken")


def test_jsonl_write_appends_one_line_per_call(tmp_path):
    log = AuditLog("test-reverse-engineer", [GRZEGORZ, ANATOLI], dir=tmp_path)
    log.write(MOVED)
    log.write(TAKEN)
    lines = log.path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    row = json.loads(lines[0])
    assert row["shooter_id"] == GRZEGORZ.id
    assert row["name"] == GRZEGORZ.name
    assert row["email"] == GRZEGORZ.email
    assert row["from_squad"] == 2
    assert row["to_squad"] == 3
    assert row["outcome"] == "moved"
    assert row["notify"] is False
    assert "ts" in row


def test_jsonl_is_the_default_format(tmp_path):
    log = AuditLog("test-reverse-engineer", [GRZEGORZ], dir=tmp_path)
    assert log.path.suffix == ".jsonl"


def test_csv_format_writes_header_once(tmp_path):
    log = AuditLog("test-reverse-engineer", [GRZEGORZ, ANATOLI], fmt="csv", dir=tmp_path)
    log.write(MOVED)
    log.write(TAKEN)
    with log.path.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 2
    assert rows[0]["shooter_id"] == str(GRZEGORZ.id)
    assert rows[0]["email"] == GRZEGORZ.email
    assert rows[1]["outcome"] == "taken"


def test_notify_flag_is_recorded(tmp_path):
    log = AuditLog("test-reverse-engineer", [GRZEGORZ], notify=True, dir=tmp_path)
    log.write(MOVED)
    row = json.loads(log.path.read_text(encoding="utf-8").splitlines()[0])
    assert row["notify"] is True


def test_unknown_shooter_writes_null_name_and_email(tmp_path):
    log = AuditLog("test-reverse-engineer", [], dir=tmp_path)
    log.write(MOVED)
    row = json.loads(log.path.read_text(encoding="utf-8").splitlines()[0])
    assert row["name"] is None
    assert row["email"] is None


def test_invalid_format_rejected(tmp_path):
    with pytest.raises(ValueError):
        AuditLog("test-reverse-engineer", [], fmt="xml", dir=tmp_path)


@pytest.mark.skipif(os.name != "posix", reason="chmod 600 is a POSIX-only guarantee (NF8)")
def test_file_is_chmod_600_on_posix(tmp_path):
    log = AuditLog("test-reverse-engineer", [GRZEGORZ], dir=tmp_path)
    log.write(MOVED)
    mode = log.path.stat().st_mode & 0o777
    assert mode == 0o600
