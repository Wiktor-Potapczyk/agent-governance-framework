"""Pytest configuration for the hooks suite.

Stops the suite writing into the two live observability streams.

Measured 2026-08-01, before this file existed: a single run of this suite
appended **128 records** to `.claude/hooks/governance-log.jsonl` (74 from
bash-safety-guard, 21 from work-verification-check, 17 from
agent-dispatch-check, the rest scattered) and **117 records** to
`.claude/hooks/hook-activity.jsonl`. That is a large part of why both logs
read as majority test pollution, and it is not only an analytics nuisance:
the Step-11 competence gate derives an agent's warm-up count from a bounded
tail of the governance log, and `hook_activity_report` derives its fire
counts and its dark-hook list from the activity log. Synthetic records evict
real history in the first and invent coverage in the second.

This became possible only after contract C7 converged the writers onto two
shared helpers that resolve their destination at call time: `_event_emit`
(`GOVERNANCE_LOG_PATH`) and `_governance_logger` (`HOOK_ACTIVITY_LOG_PATH`).
Before that there were 29 call sites each computing their own path.

Scope and its limits: this redirects writers that go through the shared
helpers. The writers deliberately left direct (the Gate-1 degradation alarm
with its own GATE1_ALARM_LOG_PATH, the competence gate that reads its own
write path, the classifier fallback that fires only when the helper import
failed) are unaffected and still write where they always did.
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
    tmp = tempfile.mkdtemp(prefix="hooks-suite-logs-")
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
