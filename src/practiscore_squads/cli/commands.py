"""The five CLI commands (§5): config set-default, squads, shooters, move, move-bulk."""
from __future__ import annotations

import sys
from pathlib import Path

import click
from rich.progress import Progress

from .. import config as config_mod
from ..audit import AuditLog
from ..bulk import BulkMover
from ..checkpoint import Checkpoint
from ..errors import AuthError, ThrottledError
from ..formatting import ShooterRow
from ..lock import LockManager
from ..planner import MovePlanner, name_to_squad_map
from .main import cli, confirm_or_abort, error_boundary


# --------------------------------- config ---------------------------------- #
@cli.group("config")
def config_group():
    """Local config file management (F0)."""


@config_group.command("set-default")
@click.option("--match", "match_value", required=True, help="Match slug or full squadding URL.")
def config_set_default(match_value: str):
    with error_boundary():
        cfg = config_mod.set_default_match(match_value)
        click.echo(f"Default match set to {cfg.default_match}")


# --------------------------------- squads ------------------------------------ #
@cli.command("squads")
@click.pass_obj
def squads_cmd(obj):
    """List all squads with occupancy/free counts (F1)."""
    with error_boundary():
        client = obj.build_client()
        obj.formatter.squads(client.snapshot)


# -------------------------------- shooters ----------------------------------- #
@cli.command("shooters")
@click.option("--squad", "squad_no", type=int, default=None, help="Limit to one displayed squad.")
@click.pass_obj
def shooters_cmd(obj, squad_no):
    """List the roster as (name, ID), or one squad's members (F2). Email is never shown (NF9)."""
    with error_boundary():
        client = obj.build_client()
        name_to_squad = name_to_squad_map(client)
        rows = [ShooterRow(s, name_to_squad.get(s.name)) for s in client.roster()]
        if squad_no is not None:
            rows = [r for r in rows if r.squad_no == squad_no]
        obj.formatter.shooters(rows, squad_no)


# ---------------------------------- move -------------------------------------- #
@cli.command("move")
@click.argument("shooter_id", type=int)
@click.option("--to", "to_squad", type=int, required=True,
             help="Destination displayed squad number.")
@click.option("--position", type=int, default=None,
             help="Specific slot position (default: first free).")
@click.option("--yes", "-y", is_flag=True, default=False)
@click.option("--notify", is_flag=True, default=False)
@click.option("--dry-run", is_flag=True, default=False,
             help="Print the plan and exit without executing.")
@click.pass_obj
def move_cmd(obj, shooter_id, to_squad, position, yes, notify, dry_run):
    """Move one shooter to another squad (F3).

    Exit codes (§5.4): 0 on "moved"/"added"/"already there"; 4 on "taken"/blocked.
    """
    with error_boundary():
        yes = obj.yes or yes
        notify = obj.notify or notify

        client = obj.build_client()
        lock_report = LockManager().ensure(client)  # NF7: lock before mutating

        plan = MovePlanner(client).plan([shooter_id], to_squad)
        obj.formatter.plan(plan)

        if dry_run:
            obj.formatter.lock(lock_report)
            return

        if not yes:
            confirm_or_abort(f"Move shooter {shooter_id} to Squad {to_squad}?")

        outcome = client.move(shooter_id, to_squad, position=position, notify=notify)
        obj.formatter.outcomes([outcome])
        obj.formatter.lock(lock_report)

        if not outcome.ok:
            sys.exit(4)  # D4: taken/blocked


# -------------------------------- move-bulk ------------------------------------ #
def _parse_ids(ids: str | None, ids_file: str | None) -> list[int]:
    if ids:
        return [int(part.strip()) for part in ids.split(",") if part.strip()]
    text = Path(ids_file).read_text(encoding="utf-8")
    out: list[int] = []
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            out.append(int(line))
    return out


@cli.command("move-bulk")
@click.option("--to", "to_squad", type=int, required=True,
             help="Destination squad for the batch.")
@click.option("--ids", default=None, help="Comma-separated shooter IDs.")
@click.option("--ids-file", type=click.Path(exists=True, dir_okay=False), default=None,
             help="File of shooter IDs, one per line (# comments ok).")
@click.option("--dry-run", is_flag=True, default=False,
             help="Print the plan and exit without executing.")
@click.option("--fresh", is_flag=True, default=False,
             help="Ignore/clear any existing checkpoint (NF6).")
@click.option("--yes", "-y", is_flag=True, default=False)
@click.option("--notify", is_flag=True, default=False)
@click.pass_obj
def move_bulk_cmd(obj, to_squad, ids, ids_file, dry_run, fresh, yes, notify):
    """Move a list of shooters to a target squad (F4); continue-and-report on partial failure (NF5).

    Exit codes (§5): 0 clean finish; 4 partial failure (>=1 move failed);
    5 throttled (partial, resumable from checkpoint, D3); 3 session expired.
    """
    with error_boundary():
        if bool(ids) == bool(ids_file):
            _fail_usage("exactly one of --ids or --ids-file is required")

        shooter_ids = _parse_ids(ids, ids_file)
        yes = obj.yes or yes
        notify = obj.notify or notify

        client = obj.build_client()
        lock_report = LockManager().ensure(client)  # NF7: lock before mutating

        plan = MovePlanner(client).plan(shooter_ids, to_squad)
        obj.formatter.plan(plan)

        if dry_run:
            obj.formatter.lock(lock_report)
            return

        if not yes:
            confirm_or_abort(f"Move {len(plan.actionable())} shooter(s) to Squad {to_squad}?")

        checkpoint = Checkpoint(client.slug, to_squad, notify)
        if fresh:
            checkpoint.clear()
        audit = AuditLog(client.slug, client.roster(), notify=notify,
                         dir=obj.config.audit_dir, fmt=obj.config.audit_format)

        with Progress(disable=obj.quiet or obj.json_output) as progress:
            task_id = progress.add_task("Moving", total=len(plan.actionable()))

            def on_progress(_outcome, done, total):
                progress.update(task_id, completed=done, total=total)

            mover = BulkMover(client, checkpoint, audit, on_progress=on_progress)
            try:
                outcomes = mover.run(plan, notify=notify)
            except ThrottledError:
                obj.formatter.lock(lock_report)
                click.echo(f"throttled — resume later with the same command "
                           f"(checkpoint: {checkpoint.path})", err=True)
                raise
            except AuthError:
                obj.formatter.lock(lock_report)
                click.echo(f"session expired — refresh --cookie and re-run to resume "
                           f"(checkpoint: {checkpoint.path})", err=True)
                raise

        obj.formatter.outcomes(outcomes)
        obj.formatter.lock(lock_report)
        click.echo(f"Audit: {audit.path}")

        if any(not o.ok for o in outcomes):
            sys.exit(4)


def _fail_usage(message: str) -> None:
    click.echo(f"error: {message}", err=True)
    raise SystemExit(2)
