"""Config load/save + match/cookie resolution precedence (U1, F0/NF1, implementation.md §4.3)."""
from __future__ import annotations

import pytest

from practiscore_squads.config import (
    Config, NoDefaultMatchError, load, parse_match, resolve_cookie, resolve_match, save,
    set_default_match,
)

BASE = "https://practiscore.com"
SLUG = "test-reverse-engineer"


# --------------------------------- load/save ------------------------------- #
def test_load_missing_file_returns_defaults(tmp_path):
    cfg = load(tmp_path / "config.toml")
    assert cfg.default_match is None
    assert cfg.cookie is None
    assert cfg.audit_format == "jsonl"


def test_save_then_load_round_trips(tmp_path):
    path = tmp_path / "config.toml"
    save(Config(default_match=SLUG, audit_format="csv"), path)
    reloaded = load(path)
    assert reloaded.default_match == SLUG
    assert reloaded.audit_format == "csv"


def test_save_omits_cookie_by_default(tmp_path):
    """NF1: a cookie is discouraged in the file — save() must not invent one."""
    path = tmp_path / "config.toml"
    save(Config(default_match=SLUG), path)
    assert "cookie" not in path.read_text(encoding="utf-8")


def test_save_writes_explicit_cookie_if_set(tmp_path):
    path = tmp_path / "config.toml"
    save(Config(default_match=SLUG, cookie="laravel_session=abc"), path)
    reloaded = load(path)
    assert reloaded.cookie == "laravel_session=abc"


def test_set_default_match_persists_normalized_slug(tmp_path):
    path = tmp_path / "config.toml"
    cfg = set_default_match(f"{BASE}/{SLUG}/squadding", path)
    assert cfg.default_match == SLUG
    assert load(path).default_match == SLUG


# ------------------------------- resolve_match ----------------------------- #
def test_resolve_match_prefers_cli_value_over_default():
    cfg = Config(default_match="other-match")
    assert resolve_match(SLUG, cfg) == SLUG


def test_resolve_match_falls_back_to_config_default():
    cfg = Config(default_match=SLUG)
    assert resolve_match(None, cfg) == SLUG


def test_resolve_match_normalizes_full_url():
    cfg = Config()
    assert resolve_match(f"{BASE}/{SLUG}/squadding", cfg) == SLUG


def test_resolve_match_raises_when_nothing_selected():
    cfg = Config()
    with pytest.raises(NoDefaultMatchError):
        resolve_match(None, cfg)


# ------------------------------- parse_match ------------------------------- #
def test_parse_match_is_reexported_from_client():
    assert parse_match(SLUG) == SLUG
    assert parse_match(f"{BASE}/{SLUG}/squadding") == SLUG


# ------------------------------- resolve_cookie ---------------------------- #
def test_resolve_cookie_prefers_cli_value():
    cfg = Config(cookie="from-config")
    got = resolve_cookie("from-cli", cfg, env={"PRACTISCORE_COOKIE": "from-env"})
    assert got == "from-cli"


def test_resolve_cookie_falls_back_to_env():
    cfg = Config(cookie="from-config")
    got = resolve_cookie(None, cfg, env={"PRACTISCORE_COOKIE": "from-env"})
    assert got == "from-env"


def test_resolve_cookie_falls_back_to_config():
    cfg = Config(cookie="from-config")
    got = resolve_cookie(None, cfg, env={})
    assert got == "from-config"


def test_resolve_cookie_falls_back_to_prompt():
    cfg = Config()
    got = resolve_cookie(None, cfg, env={}, prompt=lambda: "from-prompt")
    assert got == "from-prompt"


def test_resolve_cookie_reads_at_file(tmp_path):
    cookie_file = tmp_path / "cookie.txt"
    cookie_file.write_text("laravel_session=filedata\n", encoding="utf-8")
    cfg = Config()
    got = resolve_cookie(f"@{cookie_file}", cfg, env={})
    assert got == "laravel_session=filedata"
