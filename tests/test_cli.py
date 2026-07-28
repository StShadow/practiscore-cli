"""CLI layer (U4, §5/§6): option parsing, dry-run/confirm gating, --json shape, exit codes."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import responses
from click.testing import CliRunner

import practiscore_squads.pacing as pacing_mod
from practiscore_squads.cli.main import cli

from tests._data import (
    ANATOLI, BASE, COOKIE, GRZEGORZ, SLUG, SQUAD3, bootstrap_url, build_bootstrap,
    check_re, registered_re, ROSTER,
)


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Every on-disk default (config/checkpoint/audit) lives under `Path.home()` —
    isolate each test so runs never touch the real user's `~/.practiscore-squads`."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    return tmp_path


@pytest.fixture(autouse=True)
def no_real_pacing(monkeypatch):
    """The CLI builds a `SquadClient` with the production `Pacer` (near-human 0.8-1.6s
    jitter, NF6) — fine live, but it would make every CLI test pay real wall-clock
    time for no added coverage."""
    monkeypatch.setattr(pacing_mod.random, "uniform", lambda a, b: 0)
    monkeypatch.setattr(pacing_mod.time, "sleep", lambda s: None)


def _register_bootstrap_and_roster(locked=False, roster=None):
    responses.add(responses.GET, bootstrap_url(), body=build_bootstrap(locked),
                  content_type="text/html")
    responses.add(responses.GET, registered_re(), json=roster if roster is not None else ROSTER,
                  content_type="application/json")


def _runner() -> CliRunner:
    return CliRunner()


# ------------------------- global options need no cookie ------------------- #
def test_help_works_without_cookie():
    result = _runner().invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "Commands:" in result.output


def test_version_works_without_cookie():
    result = _runner().invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert "practiscore-squads" in result.output


# --------------------------------- config ------------------------------------ #
def test_config_set_default_persists_normalized_slug(isolated_home):
    result = _runner().invoke(cli, ["config", "set-default", "--match",
                                    f"{BASE}/{SLUG}/squadding"])
    assert result.exit_code == 0, result.output
    from practiscore_squads import config as config_mod
    assert config_mod.load().default_match == SLUG


def test_move_without_match_or_default_exits_usage_error(isolated_home):
    result = _runner().invoke(cli, ["--cookie", COOKIE, "move", "1", "--to", "3"])
    assert result.exit_code == 2


# --------------------------------- squads ------------------------------------ #
@responses.activate
def test_squads_json_shape():
    _register_bootstrap_and_roster()
    result = _runner().invoke(
        cli, ["--match", SLUG, "--cookie", COOKIE, "--json", "squads"]
    )
    assert result.exit_code == 0, result.output
    rows = json.loads(result.output)
    assert {r["squad_no"] for r in rows} == {1, 2, 3}


@responses.activate
def test_squads_table_output():
    _register_bootstrap_and_roster()
    result = _runner().invoke(cli, ["--match", SLUG, "--cookie", COOKIE, "squads"])
    assert result.exit_code == 0, result.output
    assert "Squad 1" in result.output


# -------------------------------- shooters ------------------------------------ #
@responses.activate
def test_shooters_json_never_includes_email():
    _register_bootstrap_and_roster()
    result = _runner().invoke(
        cli, ["--match", SLUG, "--cookie", COOKIE, "--json", "shooters"]
    )
    assert result.exit_code == 0, result.output
    assert "email" not in result.output
    assert "example.invalid" not in result.output
    rows = json.loads(result.output)
    assert {r["id"] for r in rows} == {GRZEGORZ, ANATOLI}


@responses.activate
def test_shooters_squad_filter():
    _register_bootstrap_and_roster()
    result = _runner().invoke(
        cli, ["--match", SLUG, "--cookie", COOKIE, "--json", "shooters", "--squad", "1"]
    )
    assert result.exit_code == 0, result.output
    rows = json.loads(result.output)
    assert [r["id"] for r in rows] == [GRZEGORZ]


# ---------------------------------- move --------------------------------------- #
@responses.activate
def test_move_dry_run_does_not_execute():
    _register_bootstrap_and_roster()
    responses.add(responses.POST, f"{BASE}/matches/{SLUG}/lock",
                  json={"success": True}, content_type="application/json")
    result = _runner().invoke(
        cli, ["--match", SLUG, "--cookie", COOKIE, "move", str(GRZEGORZ),
              "--to", "3", "--dry-run"]
    )
    assert result.exit_code == 0, result.output
    assert not any("/squads/check/" in c.request.url for c in responses.calls)


@responses.activate
def test_move_declining_confirm_exits_130():
    _register_bootstrap_and_roster()
    responses.add(responses.POST, f"{BASE}/matches/{SLUG}/lock",
                  json={"success": True}, content_type="application/json")
    result = _runner().invoke(
        cli, ["--match", SLUG, "--cookie", COOKIE, "move", str(GRZEGORZ), "--to", "3"],
        input="n\n",
    )
    assert result.exit_code == 130


@responses.activate
def test_move_yes_executes_and_exits_zero_on_success():
    _register_bootstrap_and_roster()
    responses.add(responses.POST, f"{BASE}/matches/{SLUG}/lock",
                  json={"success": True}, content_type="application/json")
    responses.add(responses.POST, check_re(1458605, GRZEGORZ),
                  body='{"cmd":"added","num":3}', content_type="text/html")
    result = _runner().invoke(
        cli, ["--match", SLUG, "--cookie", COOKIE, "move", str(GRZEGORZ),
              "--to", "3", "--yes"]
    )
    assert result.exit_code == 0, result.output


@responses.activate
def test_move_taken_exits_4():
    _register_bootstrap_and_roster()
    responses.add(responses.POST, f"{BASE}/matches/{SLUG}/lock",
                  json={"success": True}, content_type="application/json")
    # Grzegorz already occupies Squad 1 position 1 — moving him there again with
    # an explicit occupied position must be refused without a network probe.
    result = _runner().invoke(
        cli, ["--match", SLUG, "--cookie", COOKIE, "move", str(ANATOLI),
              "--to", "1", "--position", "1", "--yes"]
    )
    assert result.exit_code == 4, result.output


@responses.activate
def test_move_json_dry_run_emits_plan():
    _register_bootstrap_and_roster()
    responses.add(responses.POST, f"{BASE}/matches/{SLUG}/lock",
                  json={"success": True}, content_type="application/json")
    result = _runner().invoke(
        cli, ["--match", SLUG, "--cookie", COOKIE, "--json", "move", str(GRZEGORZ),
              "--to", "3", "--dry-run"]
    )
    assert result.exit_code == 0, result.output
    lines = [ln for ln in result.output.splitlines() if ln.strip()]
    plan_data = json.loads(lines[0])
    assert plan_data["target_squad"] == 3


@responses.activate
def test_move_session_expired_exits_3():
    responses.add(responses.GET, bootstrap_url(), status=302,
                  headers={"Location": f"{BASE}/login"})
    responses.add(responses.GET, f"{BASE}/login", body="<html>login</html>", status=200)
    result = _runner().invoke(
        cli, ["--match", SLUG, "--cookie", COOKIE, "move", str(GRZEGORZ), "--to", "3"]
    )
    assert result.exit_code == 3


# -------------------------------- move-bulk ------------------------------------ #
@responses.activate
def test_move_bulk_requires_exactly_one_of_ids_or_ids_file():
    _register_bootstrap_and_roster()
    result = _runner().invoke(
        cli, ["--match", SLUG, "--cookie", COOKIE, "move-bulk", "--to", "3"]
    )
    assert result.exit_code == 2


@responses.activate
def test_move_bulk_dry_run_json_shape():
    _register_bootstrap_and_roster()
    responses.add(responses.POST, f"{BASE}/matches/{SLUG}/lock",
                  json={"success": True}, content_type="application/json")
    result = _runner().invoke(
        cli, ["--match", SLUG, "--cookie", COOKIE, "--json", "move-bulk", "--to", "3",
              "--ids", f"{GRZEGORZ},{ANATOLI}", "--dry-run"]
    )
    assert result.exit_code == 0, result.output
    lines = [ln for ln in result.output.splitlines() if ln.strip()]
    plan_data = json.loads(lines[0])
    assert plan_data["target_squad"] == 3
    assert len(plan_data["moves"]) == 2


@responses.activate
def test_move_bulk_ids_file(tmp_path):
    _register_bootstrap_and_roster()
    responses.add(responses.POST, f"{BASE}/matches/{SLUG}/lock",
                  json={"success": True}, content_type="application/json")
    ids_file = tmp_path / "ids.txt"
    ids_file.write_text(f"# a comment\n{GRZEGORZ}\n{ANATOLI}\n", encoding="utf-8")
    result = _runner().invoke(
        cli, ["--match", SLUG, "--cookie", COOKIE, "--json", "move-bulk", "--to", "3",
              "--ids-file", str(ids_file), "--dry-run"]
    )
    assert result.exit_code == 0, result.output
    plan_data = json.loads(result.output.splitlines()[0])
    assert len(plan_data["moves"]) == 2


@responses.activate
def test_move_bulk_yes_clean_finish_clears_checkpoint(isolated_home):
    _register_bootstrap_and_roster()
    responses.add(responses.POST, f"{BASE}/matches/{SLUG}/lock",
                  json={"success": True}, content_type="application/json")
    responses.add(responses.POST, check_re(SQUAD3, GRZEGORZ),
                  body='{"cmd":"added","num":3}', content_type="text/html")
    responses.add(responses.POST, check_re(SQUAD3, ANATOLI),
                  body='{"cmd":"added","num":3}', content_type="text/html")
    result = _runner().invoke(
        cli, ["--match", SLUG, "--cookie", COOKIE, "--quiet", "move-bulk", "--to", "3",
              "--ids", f"{GRZEGORZ},{ANATOLI}", "--yes"]
    )
    assert result.exit_code == 0, result.output
    checkpoint_dir = isolated_home / ".practiscore-squads" / "checkpoints"
    assert not any(checkpoint_dir.glob("*.json"))
    audit_dir = isolated_home / ".practiscore-squads" / "audit"
    assert (audit_dir / f"{SLUG}.jsonl").exists()


@responses.activate
def test_move_bulk_partial_failure_exits_4(isolated_home):
    _register_bootstrap_and_roster()
    responses.add(responses.POST, f"{BASE}/matches/{SLUG}/lock",
                  json={"success": True}, content_type="application/json")
    responses.add(responses.POST, check_re(SQUAD3, GRZEGORZ),
                  body='{"cmd":"added","num":3}', content_type="text/html")
    responses.add(responses.POST, check_re(SQUAD3, ANATOLI),
                  json={"message": "Server Error"}, status=500)
    result = _runner().invoke(
        cli, ["--match", SLUG, "--cookie", COOKIE, "--quiet", "move-bulk", "--to", "3",
              "--ids", f"{GRZEGORZ},{ANATOLI}", "--yes"]
    )
    assert result.exit_code == 4, result.output


@responses.activate
def test_move_bulk_session_expiry_exits_3_and_keeps_checkpoint(isolated_home):
    _register_bootstrap_and_roster()
    responses.add(responses.POST, f"{BASE}/matches/{SLUG}/lock",
                  json={"success": True}, content_type="application/json")
    responses.add(responses.POST, check_re(SQUAD3, GRZEGORZ),
                  body='{"cmd":"added","num":3}', content_type="text/html")
    responses.add(responses.POST, check_re(SQUAD3, ANATOLI), status=302,
                  headers={"Location": f"{BASE}/login"})
    responses.add(responses.GET, f"{BASE}/login", body="<html>login</html>", status=200)
    result = _runner().invoke(
        cli, ["--match", SLUG, "--cookie", COOKIE, "--quiet", "move-bulk", "--to", "3",
              "--ids", f"{GRZEGORZ},{ANATOLI}", "--yes"]
    )
    assert result.exit_code == 3, result.output
    checkpoint_dir = isolated_home / ".practiscore-squads" / "checkpoints"
    assert any(checkpoint_dir.glob("*.json"))


@responses.activate
def test_move_bulk_declining_confirm_exits_130():
    _register_bootstrap_and_roster()
    responses.add(responses.POST, f"{BASE}/matches/{SLUG}/lock",
                  json={"success": True}, content_type="application/json")
    result = _runner().invoke(
        cli, ["--match", SLUG, "--cookie", COOKIE, "move-bulk", "--to", "3",
              "--ids", f"{GRZEGORZ},{ANATOLI}"],
        input="n\n",
    )
    assert result.exit_code == 130
