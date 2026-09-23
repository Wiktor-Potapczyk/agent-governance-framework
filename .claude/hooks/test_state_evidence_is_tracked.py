"""The vault's reliability evidence must have an off-machine copy.

Written 2026-09-10. `.gitignore` carried a blanket `.claude/hooks/_state/`
rule, added when that directory really did hold nothing but hook dedup and
throttle state. It since accumulated a second, different class of file: the
trust-contract ledger, the weekly cadence stamps, the backup result record and
the trust-contract baselines. None of those are re-derivable. The ledger IS the
record that the contract ever passed a cycle; losing it does not degrade the
N=4 streak claim, it erases the evidence the claim was ever true.

The vault's only off-machine copy is its git remote, so an ignored file has no
backup at all. That was the state until this suite was written.

WHY THIS IS A TEST AND NOT A COMMENT. The fix is an enumerated negation list,
and an enumerated allowlist rots: the next durable state file added will default
to ignored, silently, which is the same failure again. These assertions fail
loudly when that happens.

MUTATION EVIDENCE. Before the .gitignore change, `git check-ignore -v` on the
ledger returned `.gitignore:151:.claude/hooks/_state/`, so
test_the_trust_contract_ledger_is_not_ignored failed. The suite is known to
distinguish the fixed rule from the broken one.
"""
import subprocess
from pathlib import Path

import pytest

VAULT = Path(__file__).resolve().parent.parent.parent
STATE = VAULT / ".claude" / "hooks" / "_state"

# Files that are evidence: small, rarely written, not re-derivable.
EVIDENCE = ["trust-contract-ledger.jsonl", "vault-backup.json",
            "enforcement-claims.json", "orphan-baseline.json",
            "kb-index-budget.json", "root-allowlist.json",
            "self-heal-promotion-state.json"]

# Files that are scratch: churn every session, or are bulk undo snapshots.
# Re-including these would bloat every autosave commit for no recovery value.
VOLATILE = ["last-state-inject.json", "memory-nudge.json", "h4-dedup.json",
            "last-compact.json", "mcp-circuit-breaker.json",
            "haiku-orphan-undo.json", "sessionend-probe.jsonl"]


def is_ignored(path):
    """True if the .gitignore RULES would exclude this path.

    Asks git, never reparses .gitignore. Reimplementing gitignore precedence
    here would be the exact mistake this suite exists to catch: a check that
    agrees with our reading of the rules rather than with the tool that
    enforces them.

    --no-index IS LOAD-BEARING, and the first draft of this file omitted it and
    was therefore blind. Plain `git check-ignore` consults the index and never
    reports a TRACKED file as ignored. The moment the evidence files were
    committed, every assertion below started passing no matter what the rules
    said: re-appending the old blanket `_state/` rule left the suite green.
    Measured 2026-09-10 on the ledger, old rule restored: default form returns
    1 (not ignored), --no-index returns 0 (ignored). Only the second form can
    see a rules regression, which is the whole point of this file.
    """
    proc = subprocess.run(["git", "check-ignore", "-q", "--no-index", str(path)],
                          cwd=str(VAULT), capture_output=True, text=True)
    assert proc.returncode in (0, 1), proc.stderr  # 128 means git itself broke
    return proc.returncode == 0


def test_the_trust_contract_ledger_is_not_ignored():
    """The headline. Everything else in this file is defence in depth."""
    ledger = STATE / "trust-contract-ledger.jsonl"
    if not ledger.exists():
        pytest.skip("no ledger on this machine yet")
    assert not is_ignored(ledger)


@pytest.mark.parametrize("name", EVIDENCE)
def test_evidence_files_are_not_ignored(name):
    path = STATE / name
    if not path.exists():
        pytest.skip(f"{name} not present on this machine")
    assert not is_ignored(path)


def test_every_cadence_stamp_is_not_ignored():
    """Cadence stamps say when each weekly sweep last ran. Lose them and every
    staleness reminder silently resets to never-run. Globbed rather than
    enumerated so a NEW sweep's stamp is covered the day it appears."""
    stamps = sorted(STATE.glob("*-cadence.json"))
    if not stamps:
        pytest.skip("no cadence stamps on this machine yet")
    assert [p.name for p in stamps if is_ignored(p)] == []


@pytest.mark.parametrize("name", VOLATILE)
def test_volatile_state_stays_ignored(name):
    """The other direction, and it is not decorative. The lazy repair for a
    rotted allowlist is to drop the whole rule and track the directory, which
    would put megabytes of undo snapshots into every 30-minute autosave."""
    path = STATE / name
    if not path.exists():
        pytest.skip(f"{name} not present on this machine")
    assert is_ignored(path)


def test_no_secret_shaped_content_reaches_the_tracked_set():
    """A tracked state file is a file heading for a git remote. None of these
    should ever carry a token; assert it rather than assume it."""
    import re
    pattern = re.compile(
        r"ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}"
        r"|figd_[A-Za-z0-9_\-]{20,}|xox[baprs]-[A-Za-z0-9\-]{10,}"
        r"|sk-[A-Za-z0-9]{20,}|AIza[A-Za-z0-9_\-]{30,}")
    offenders = []
    for path in sorted(STATE.iterdir()):
        if not path.is_file() or is_ignored(path):
            continue
        if pattern.search(path.read_text(encoding="utf-8", errors="replace")):
            offenders.append(path.name)
    assert offenders == [], offenders
