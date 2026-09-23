"""Pytest configuration for the scripts suite.

Stops the suite writing into the two live observability streams, mirroring
`.claude/hooks/conftest.py` (2026-08-01), which protects the hooks suite but
not this directory.

Why this exists (O12 discovery D-E, 2026-09-02): the hook-mode tests in
test_staleness_check.py / test_staleness_check_generated.py call
staleness_check hook mode in-process, which routes to
_governance_logger.log_fire. Without a redirect every scripts-suite run
appends fixture evaluations to the LIVE `.claude/hooks/hook-activity.jsonl`.
Measured on 2026-09-02: 132 of the 161 staleness_check records in the live
sink were fixture-shaped ("1 entries all PASS" x43, "stale:STALE" x43,
"ManifestError" x45, "probe-fixture-stale:STALE" x1); only 29 were genuine
board runs. During the O12 observation window (2026-09-03 through 09-16) a
single polluted run would inject a fixture stale:STALE record that never
clears, corrupting the window verdict's parts (a) and (c).

Scope: redirects only the writers that resolve their destination at call time
through the shared helpers (`GOVERNANCE_LOG_PATH` for _event_emit,
`HOOK_ACTIVITY_LOG_PATH` for _governance_logger.log_fire). Tests that need
their own sink fixtures keep working: test_exit_cost_report.py passes both
env vars explicitly per subprocess (overriding this), and
test_matrix_findings.py derives findings from writer SOURCE inside a
VAULT_DIR fixture vault, not from sink records.
"""

import os
import tempfile

import pytest

_REDIRECTED = {
    "GOVERNANCE_LOG_PATH": "governance-log.jsonl",
    "HOOK_ACTIVITY_LOG_PATH": "hook-activity.jsonl",
}


@pytest.fixture(scope="session", autouse=True)
def _redirect_live_logs():
    """Point both shared-helper writers at throwaway files for the whole run."""
    tmp = tempfile.mkdtemp(prefix="scripts-suite-logs-")
    previous = {name: os.environ.get(name) for name in _REDIRECTED}
    for name, filename in _REDIRECTED.items():
        os.environ[name] = os.path.join(tmp, filename)
    try:
        yield
    finally:
        for name, prior in previous.items():
            if prior is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = prior
