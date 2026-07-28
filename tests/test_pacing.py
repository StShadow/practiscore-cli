"""Request pacing & backoff (NF6, implementation.md §3.2)."""
from __future__ import annotations

import practiscore_squads.pacing as pacing_mod
from practiscore_squads.pacing import Pacer


def test_wait_sleeps_within_bounds(monkeypatch):
    slept = []
    monkeypatch.setattr(pacing_mod.time, "sleep", lambda s: slept.append(s))
    p = Pacer(min_gap=0.5, max_gap=1.5)
    p.wait()
    p.wait()
    # at least the second wait must sleep, and never longer than max_gap
    assert slept, "Pacer.wait must sleep to keep request rate near-human"
    assert all(s <= 1.5 + 1e-9 for s in slept)


def test_penalize_backoff_grows_and_caps(monkeypatch):
    slept = []
    monkeypatch.setattr(pacing_mod.time, "sleep", lambda s: slept.append(s))
    p = Pacer(min_gap=0, max_gap=0, backoff_base=2.0, backoff_cap=10.0)
    p.penalize(1)
    p.penalize(3)
    p.penalize(9)
    assert slept[0] < slept[1]            # backoff grows with attempt
    assert all(s <= 10.0 + 1e-9 for s in slept)  # capped
