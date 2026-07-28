"""Checkpoint store (O1, NF6, implementation.md §3.6/§7)."""
from __future__ import annotations

import json

from practiscore_squads.checkpoint import Checkpoint


def test_load_empty_when_no_file(tmp_path):
    ck = Checkpoint("test-reverse-engineer", 3, dir=tmp_path)
    assert ck.load() == set()


def test_record_then_load_round_trips(tmp_path):
    ck = Checkpoint("test-reverse-engineer", 3, dir=tmp_path)
    ck.record(9808574)
    ck.record(9808577)
    reloaded = Checkpoint("test-reverse-engineer", 3, dir=tmp_path)
    assert reloaded.load() == {9808574, 9808577}


def test_record_writes_expected_file_shape(tmp_path):
    ck = Checkpoint("test-reverse-engineer", 3, notify=False, dir=tmp_path)
    ck.record(9808574)
    data = json.loads(ck.path.read_text(encoding="utf-8"))
    assert data["slug"] == "test-reverse-engineer"
    assert data["target_squad"] == 3
    assert data["notify"] is False
    assert data["done"] == [9808574]
    assert "updated" in data


def test_clear_deletes_file_and_resets_state(tmp_path):
    ck = Checkpoint("test-reverse-engineer", 3, dir=tmp_path)
    ck.record(9808574)
    assert ck.path.exists()
    ck.clear()
    assert not ck.path.exists()
    assert ck.load() == set()


def test_clear_is_idempotent_when_no_file_exists(tmp_path):
    ck = Checkpoint("test-reverse-engineer", 3, dir=tmp_path)
    ck.clear()  # must not raise


def test_mismatched_slug_is_ignored(tmp_path):
    """§7 guard: a checkpoint for a different slug must not be treated as done."""
    Checkpoint("other-match", 3, dir=tmp_path).record(9808574)
    ck = Checkpoint("test-reverse-engineer", 3, dir=tmp_path)
    assert ck.load() == set()


def test_mismatched_target_squad_is_ignored(tmp_path):
    Checkpoint("test-reverse-engineer", 2, dir=tmp_path).record(9808574)
    ck = Checkpoint("test-reverse-engineer", 3, dir=tmp_path)
    assert ck.load() == set()


def test_mismatched_notify_is_ignored(tmp_path):
    """A checkpoint from a notify=True run must not be reused by a notify=False run."""
    ck_notify = Checkpoint("test-reverse-engineer", 3, notify=True, dir=tmp_path)
    ck_notify.record(9808574)
    ck_silent = Checkpoint("test-reverse-engineer", 3, notify=False, dir=tmp_path)
    assert ck_silent.load() == set()


def test_corrupt_json_is_treated_as_empty(tmp_path):
    path = tmp_path / "test-reverse-engineer-to3.json"
    path.write_text("not json{", encoding="utf-8")
    ck = Checkpoint("test-reverse-engineer", 3, dir=tmp_path)
    assert ck.load() == set()


def test_default_dir_used_when_none_given(tmp_path, monkeypatch):
    monkeypatch.setattr("practiscore_squads.checkpoint.Path.home", lambda: tmp_path)
    ck = Checkpoint("test-reverse-engineer", 3)
    assert ck.dir == tmp_path / ".practiscore-squads" / "checkpoints"
    assert ck.dir.is_dir()
