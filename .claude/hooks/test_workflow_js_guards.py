#!/usr/bin/env python3
"""Runs the JavaScript regression guards under .claude/workflows/ inside pytest.

Empirical trigger (2026-08-24, finding UT-1 of the harness audit): all three .mjs
guards in .claude/workflows/ were invoked by no runner at all. No package.json
under .claude or .claude/workflows, no runner registration, and the only
references to each in the live tree were the file itself. All three passed when
run by hand, which is what made the gap invisible: the guards were correct and
disconnected at the same time.

Meanwhile all 77 Python tests were collected. The Python half of the harness had
an automatic gate (hook-write-regression-gate.py) and the JavaScript half had
nothing -- and the JS half is what guards the workflow scripts that make the six
process skills enforced by construction rather than by prompt.

This file is the join. Living in .claude/hooks/ puts the JS guards under the same
pytest run the gate already executes, so they now run on every hook write.

Two deliberate design choices, both of which are the point rather than polish:

1. DISCOVERY IS DYNAMIC. Hardcoding the three known names would mean a fourth
   guard added later is disconnected again and nobody finds out until the next
   audit. The glob means a new test_*.mjs is picked up the moment it lands.

2. NOTHING HERE SKIPS QUIETLY. A missing node, or an empty glob, FAILS. The
   tempting alternative is to skip, so the suite stays green on a machine
   without node -- but a skip would restore the exact silence this finding is
   about: the guards would appear connected while running nowhere. If node is
   genuinely unavailable somewhere this must be re-decided in the open.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

WORKFLOWS = Path(__file__).resolve().parent.parent / "workflows"


def _guards() -> list[Path]:
    return sorted(WORKFLOWS.glob("test_*.mjs"))


def test_the_guard_set_is_not_empty():
    """Zero-denominator guard: an empty glob must fail, never pass vacuously.

    Without this, moving or renaming the workflows directory turns every
    parametrised case below into "no tests ran", which pytest reports as
    success. The whole finding this file answers is a check that looked
    connected while running nothing.
    """
    found = _guards()
    assert found, (
        "No test_*.mjs found under %s. Either the guards moved and this file "
        "needs repointing, or they were deleted. Both need a human; neither is "
        "a pass." % WORKFLOWS
    )


def test_node_is_available():
    """Fails rather than skips. See design note 2 in the module docstring."""
    assert shutil.which("node"), (
        "node is not on PATH, so the JavaScript guards cannot run. This is a "
        "FAIL and not a skip on purpose: skipping would report the guards as "
        "connected while they execute nowhere, which is the defect this file "
        "exists to close."
    )


@pytest.mark.parametrize("guard", _guards(), ids=lambda p: p.name)
def test_workflow_js_guard_passes(guard: Path):
    r = subprocess.run(
        ["node", str(guard)],
        capture_output=True, text=True, timeout=120, cwd=str(WORKFLOWS.parent.parent),
    )
    assert r.returncode == 0, "%s failed (exit %d)\n--- stdout ---\n%s\n--- stderr ---\n%s" % (
        guard.name, r.returncode, r.stdout[-4000:], r.stderr[-2000:])
