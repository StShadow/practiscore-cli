"""click group, global options (§6.1), and the lazy `SquadClient` factory (§3.7)."""
from __future__ import annotations

from contextlib import contextmanager

import click

from .. import config as config_mod
from ..client import SquadClient
from ..errors import AuthError, InvalidMatchError, SquaddingError, ThrottledError
from ..formatting import Formatter, JsonFormatter, TableFormatter

_VERSION = "0.1.0"


def _fail(message: str, code: int) -> None:
    click.echo(f"error: {message}", err=True)
    raise SystemExit(code)


@contextmanager
def error_boundary():
    """Maps the library's exception hierarchy onto the exit codes in §5.

    Order matters: subclasses are checked before their parents (`ThrottledError`
    and `AuthError`/`SessionExpiredError` before the generic `SquaddingError`).
    """
    try:
        yield
    except config_mod.NoDefaultMatchError as exc:
        _fail(str(exc), 2)
    except InvalidMatchError as exc:
        _fail(str(exc), 2)
    except AuthError as exc:
        _fail(str(exc), 3)
    except ThrottledError as exc:
        _fail(str(exc), 5)
    except SquaddingError as exc:
        _fail(str(exc), 1)


def confirm_or_abort(message: str) -> None:
    """NF5 dry-run confirm; a decline exits 130 (§5), not click's default Abort code."""
    if not click.confirm(message):
        raise SystemExit(130)


class Context:
    """Carries resolved `Config`, the chosen `Formatter`, and a lazy `SquadClient`
    factory — the client (and its network session) is only built when a command
    actually needs one, so `--help`/`--version` never require a cookie (U3)."""

    def __init__(self, match: str | None, cookie: str | None, json_output: bool,
                 yes: bool, notify: bool, quiet: bool, verbose: bool):
        self.match_arg = match
        self.cookie_arg = cookie
        self.json_output = json_output
        self.yes = yes
        self.notify = notify
        self.quiet = quiet
        self.verbose = verbose
        self.config = config_mod.load()
        self.formatter: Formatter = JsonFormatter() if json_output else TableFormatter()
        self._client: SquadClient | None = None

    def build_client(self) -> SquadClient:
        if self._client is None:
            match = config_mod.resolve_match(self.match_arg, self.config)
            cookie = config_mod.resolve_cookie(self.cookie_arg, self.config)
            self._client = SquadClient.from_cookie(cookie, match)
        return self._client


@click.group()
@click.option("--match", default=None, help="Target match slug or full squadding URL (F0).")
@click.option("--cookie", default=None, help="Session cookie value or @file (NF1).")
@click.option("--json", "json_output", is_flag=True, default=False,
             help="Machine-readable JSON output instead of tables (NF3).")
@click.option("--yes", "-y", is_flag=True, default=False,
             help="Skip the dry-run confirmation prompt (NF5).")
@click.option("--notify", is_flag=True, default=False,
             help="Send PractiScore emails for moves (default: silent, NF4).")
@click.option("--quiet", "-q", is_flag=True, default=False, help="Suppress progress bar output.")
@click.option("--verbose", "-v", is_flag=True, default=False, help="Debug logging to stderr.")
@click.version_option(version=_VERSION, prog_name="practiscore-squads")
@click.pass_context
def cli(ctx: click.Context, match, cookie, json_output, yes, notify, quiet, verbose):
    """PractiScore squadding CLI — list, move, and bulk-move shooters between squads."""
    ctx.obj = Context(match, cookie, json_output, yes, notify, quiet, verbose)
