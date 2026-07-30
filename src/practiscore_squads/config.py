"""Config load/save and match/cookie resolution (F0/NF1, implementation.md §3.7/§4.4).

TOML on disk (`tomllib` to read, `tomli-w` to write); match/cookie precedence
chains are pure functions so the CLI layer can unit-test them without a
filesystem or a real prompt.
"""
from __future__ import annotations

import os
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path

import tomli_w

from .client import parse_match_slug as parse_match  # noqa: F401  (re-exported, §3.7 signature)

__all__ = ["Config", "ConfigError", "NoDefaultMatchError", "load", "save", "resolve_match",
           "parse_match", "resolve_cookie"]


class ConfigError(ValueError):
    """A config file or `@file` cookie exists but couldn't be read or parsed.

    Distinct from a library fault: nothing is wrong with the API or the session, the
    inputs on disk are bad. The CLI maps it to the usage exit code rather than letting
    a raw `TOMLDecodeError`/`OSError` traceback reach the operator.
    """


class NoDefaultMatchError(ValueError):
    """No `--match` given and no default saved (F0) — a CLI usage error, not a library fault."""


def default_config_path() -> Path:
    return Path.home() / ".practiscore-squads" / "config.toml"


def _default_audit_dir() -> Path:
    return Path.home() / ".practiscore-squads" / "audit"


@dataclass
class Config:
    default_match: str | None = None
    cookie: str | None = None  # discouraged in the file; prefer env/flag (NF1)
    audit_dir: Path = None  # type: ignore[assignment]  # filled in __post_init__
    audit_format: str = "jsonl"

    def __post_init__(self) -> None:
        if self.audit_dir is None:
            self.audit_dir = _default_audit_dir()
        elif isinstance(self.audit_dir, str):
            self.audit_dir = Path(self.audit_dir).expanduser()


def load(path: Path | None = None) -> Config:
    path = path if path is not None else default_config_path()
    if not path.exists():
        return Config()
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path} is not valid TOML: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"could not read {path}: {exc}") from exc
    return Config(
        default_match=data.get("default_match"),
        cookie=data.get("cookie"),
        audit_dir=data.get("audit_dir"),
        audit_format=data.get("audit_format", "jsonl"),
    )


def save(cfg: Config, path: Path | None = None) -> None:
    path = path if path is not None else default_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict = {
        "audit_dir": str(cfg.audit_dir),
        "audit_format": cfg.audit_format,
    }
    if cfg.default_match:
        data["default_match"] = cfg.default_match
    if cfg.cookie:
        data["cookie"] = cfg.cookie  # only if the caller explicitly set one (discouraged, NF1)
    with path.open("wb") as fh:
        tomli_w.dump(data, fh)


def set_default_match(match: str, path: Path | None = None) -> Config:
    """`config set-default --match <slug|url>` (§5.1): normalize to slug and persist."""
    path = path if path is not None else default_config_path()
    cfg = load(path)
    cfg = replace(cfg, default_match=parse_match(match))
    save(cfg, path)
    return cfg


def resolve_match(cli_value: str | None, cfg: Config) -> str:
    """F0: `--match` > saved default > error."""
    raw = cli_value or cfg.default_match
    if not raw:
        raise NoDefaultMatchError(
            "no match selected; pass --match <slug|url> or run "
            "`config set-default --match <slug|url>`"
        )
    return parse_match(raw)


def _read_cookie_value(value: str) -> str:
    """Supports the NF1 `@path` convention for pasting a cookie via a file."""
    if value.startswith("@"):
        path = Path(value[1:]).expanduser()
        try:
            return path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ConfigError(f"could not read cookie file {path}: {exc}") from exc
    return value


def resolve_cookie(cli_value: str | None, cfg: Config, *,
                    env: Mapping[str, str] | None = None,
                    prompt: Callable[[], str] | None = None) -> str:
    """NF1: `--cookie` (value or `@file`) > env `PRACTISCORE_COOKIE` > config > prompt."""
    if cli_value:
        return _read_cookie_value(cli_value)
    env = env if env is not None else os.environ
    if env.get("PRACTISCORE_COOKIE"):
        return _read_cookie_value(env["PRACTISCORE_COOKIE"])
    if cfg.cookie:
        return _read_cookie_value(cfg.cookie)
    if prompt is None:
        import click
        prompt = lambda: click.prompt("Session cookie", hide_input=True)  # noqa: E731
    return prompt()
