#!/usr/bin/env python3
"""SessionStart cadence trigger for the two public repos (AGF / AGR).

Surfaces a reminder when either public repo has gone longer than its cadence
without receiving a commit, and separately when a local clone has commits that
were never pushed.

Empirical trigger (2026-07-29): the framework repo went 39 days and the research
repo 48 days without an update, and nothing surfaced it. Every other periodic
sweep in this vault (lint, governance-mine, work-triage, setup-audit, ingest)
emits an overdue reminder at SessionStart; repo maintenance emitted none, so the
lapse produced no signal until the owner happened to notice. This closes that
asymmetry.

Design note: the staleness measurement reads the ACTUAL last-commit date out of
each clone with `git log -1`, and the unpushed count out of `git rev-list`. It
deliberately does NOT read a hand-maintained "last synced" timestamp in a state
file. A state file records when someone last claimed to sync; git records when a
commit actually landed. Only the second can catch a sync that silently failed,
which is the failure mode this hook exists to detect.

The state file is therefore used only to throttle the reminder itself, so the
message does not repeat on every session of the same day.

Output contract: stdout JSON per SessionStart hook spec. Never blocks.
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

VAULT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
STATE_FILE = os.path.join(VAULT, ".claude", "hooks", "_state", "repo-sync-cadence.json")

_SESSION: str | None = None  # set from the payload in main(); None when absent

CADENCE_DAYS = 14          # a public repo quiet longer than this is drifting
THROTTLE_HOURS = 20        # do not repeat the reminder within the same working day

REPOS = [
    ("AGF", os.path.join(VAULT, "Projects", "Agent-Governance-Research", "framework-repo"),
     "agent-governance-framework"),
    ("AGR", os.path.join(VAULT, "Projects", "Agent-Governance-Research", "repo"),
     "agent-governance-research"),
]


def _git(repo_dir, args):
    """Run git in repo_dir. Returns stripped stdout, or None on any failure."""
    try:
        r = subprocess.run(
            ["git"] + args,
            cwd=repo_dir,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if r.returncode != 0:
            return None
        return r.stdout.strip()
    except Exception:
        return None


def inspect(repo_dir):
    """Return (days_since_last_commit, unpushed_count) or (None, None) if unreadable.

    Both values come from git itself rather than from any recorded claim.
    """
    if not os.path.isdir(os.path.join(repo_dir, ".git")):
        return None, None

    iso = _git(repo_dir, ["log", "-1", "--format=%cI"])
    days = None
    if iso:
        try:
            when = datetime.fromisoformat(iso)
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            days = (datetime.now(timezone.utc) - when).days
        except Exception:
            days = None

    # No network call: compares against the last-fetched remote ref. A stale
    # remote ref can only make this under-report, never invent unpushed work.
    unpushed = None
    branch = _git(repo_dir, ["rev-parse", "--abbrev-ref", "HEAD"]) or "main"
    count = _git(repo_dir, ["rev-list", "--count", f"origin/{branch}..HEAD"])
    if count is not None:
        try:
            unpushed = int(count)
        except ValueError:
            unpushed = None

    return days, unpushed


def throttled():
    """True when a reminder was already emitted inside the throttle window."""
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            last = datetime.fromisoformat(json.load(f)["last_reminder"])
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - last).total_seconds() < THROTTLE_HOURS * 3600
    except Exception:
        return False


def record():
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"last_reminder": datetime.now(timezone.utc).isoformat()}, f)
    except Exception:
        pass


def build_message():
    stale, pending, unreadable = [], [], []

    for label, path, remote in REPOS:
        days, unpushed = inspect(path)
        if days is None:
            unreadable.append(f"{label} ({remote})")
            continue
        if days >= CADENCE_DAYS:
            stale.append(f"{label} last commit {days}d ago")
        if unpushed:
            pending.append(f"{label} has {unpushed} unpushed commit(s)")

    if not (stale or pending or unreadable):
        return ""

    parts = []
    if pending:
        parts.append(
            "[REPO-SYNC: UNPUSHED WORK] " + "; ".join(pending) +
            ". Commits exist locally that the public remote has never seen. "
            "Push is Gate-1: surface a decision brief, then Wiktor runs it via the !-prefix bypass."
        )
    if stale:
        parts.append(
            f"[REPO-SYNC CADENCE: OVERDUE] " + "; ".join(stale) +
            f" (cadence {CADENCE_DAYS}d). Run /repo-sync to reconcile docs against what the vault "
            "actually ships. Mode B (unsolicited) is bounded to routine doc-truth propagation; "
            "new artifacts and README rewrites need Wiktor's go-ahead."
        )
    if unreadable:
        parts.append(
            "[REPO-SYNC: CLONE UNREADABLE] " + "; ".join(unreadable) +
            ". Expected a git clone at Projects/Agent-Governance-Research/{framework-repo,repo}. "
            "Treat an unexpected path as unknown provenance and STOP rather than syncing it."
        )
    return "\n".join(parts)


def _log_fire(decision, detail=None):
    """Record this firing to hook-activity.jsonl. Never raises (contract C1)."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from _governance_logger import log_fire
        log_fire("repo-sync-cadence-trigger", decision=decision, detail=detail,
                  session=_SESSION)
    except Exception:
        pass


def main():
    # Defect 2 fix (2026-08-07): this hook never read stdin at all; every
    # _log_fire() call therefore logged session=None (no wiring), even though
    # CC's SessionStart payload carries session_id like every other event.
    global _SESSION
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from _governance_logger import session_from
        _SESSION = session_from(sys.stdin.read())
    except Exception:
        _SESSION = None

    if throttled():
        _log_fire("throttled")
        return
    message = build_message()
    if not message:
        _log_fire("in-sync")
        return
    record()
    _log_fire("remind", message[:120])
    try:
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": message,
            }
        }))
    except Exception:
        pass


if __name__ == "__main__":
    main()
