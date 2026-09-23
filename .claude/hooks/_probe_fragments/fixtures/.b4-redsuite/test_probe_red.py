"""Deliberately-failing one-test suite. Fixture for the batch-4 probe of
hook-write-regression-gate.py: pointed at by HOOK_REGRESSION_GATE_TARGET_DIR so
the gate's SUITE RED branch can be exercised without touching the live suite.
Lives in a dot-directory so a `pytest .claude/hooks/` run never recurses into it.
"""


def test_probe_red_marker():
    assert 1 == 2, "intentional failure: probe fixture, not a real regression"
