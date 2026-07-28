"""CLI package: click group (`main.py`) + command handlers (`commands.py`, §5)."""
from __future__ import annotations

from . import commands  # noqa: F401  (registers the commands on `cli`)
from .main import cli

__all__ = ["cli"]
