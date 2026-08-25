#!/usr/bin/env python3
"""subagent-scope-check.py: SubagentStart + SubagentStop scope-extension instrumentation.

Empirical trigger (2026-05-26 W-D2 ensemble, loop iter 2):
- prompt-engineer sub-agent self-extended scope to mark its own task_plan ticket
  AND made a tag-policy decision (ensemble → unclassified-pending): both outside
  the design-only ticket scope.
- Substance was accurate; scope was wrong. Documented as the first scope-extension
  event in [[finding_subagent_reviewer_write_grant_pattern]].

V1 mechanism (this hook):
- At SubagentStart: capture `git status --porcelain` baseline keyed by agent_id
- At SubagentStop: re-capture git status, diff against baseline, log new modifications
- Emit one JSONL entry per stop event to .claude/hooks/subagent-scope-log.jsonl

Does NOT block. Pure instrumentation: main session can grep the log post-dispatch
to see if a sub-agent modified files outside its declared output path.

V2 future work (not in this hook): parse the sub-agent's dispatch prompt for the
declared output path + diff against actual modifications → automated scope-extension
detection. V1 just surfaces the data; V2 makes the judgment.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Test seam added 2026-08-23. This hook's verdict is a function of the git
# working tree, not of its stdin payload: with no stored baseline, new_changes
# is every line of `git status --porcelain`. A probe therefore cannot trip it
# deterministically unless it controls the repository being inspected. Every
# path below derives from VAULT, so this single override redirects the git cwd,
# the baseline state file and the JSONL sink together. Unset in production.
VAULT = Path(os.environ.get("SUBAGENT_SCOPE_ROOT")
             or r"C:\Users\exampleuser\Desktop\Vault")
STATE_DIR = VAULT / ".claude" / "hooks" / "_state"
STATE_FILE = STATE_DIR / "subagent-scope-baselines.json"
LOG_FILE = VAULT / ".claude" / "hooks" / "subagent-scope-log.jsonl"


def _git_porcelain() -> list[str]:
    """Return list of `XX path` lines from `git status --porcelain`."""
    try:
        r = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=VAULT, capture_output=True, text=True, timeout=5,
        )
        if r.returncode != 0:
            return []
        return [ln for ln in r.stdout.splitlines() if ln.strip()]
    except Exception:
        return []


def _load_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        tmp.replace(STATE_FILE)
    except Exception:
        pass


def _log(entry: dict) -> None:
    try:
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def main() -> int:
    try:
        raw = sys.stdin.read()
    except Exception:
        return 0
    if not raw:
        return 0

    try:
        payload = json.loads(raw)
    except Exception:
        return 0

    event = payload.get("hook_event_name") or payload.get("hookEventName") or ""
    agent_id = payload.get("agent_id") or payload.get("session_id") or "unknown"
    agent_type = payload.get("agent_type") or payload.get("description") or "unknown"
    now = datetime.now().isoformat()

    def _log_verdict(decision, detail=None):
        """Record this verdict to hook-activity.jsonl. Never raises (contract C2).

        Deliberately NOT named _log: the module-level _log() above writes the
        separate subagent-scope-log.jsonl sink and is a different function.
        """
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from _governance_logger import log_fire, session_from
            log_fire("subagent-scope-check", decision=decision, detail=detail,
                     session=session_from(payload))
        except Exception:
            pass

    state = _load_state()
    porc_now = _git_porcelain()

    if event == "SubagentStart":
        # Capture baseline
        state[agent_id] = {
            "started_at": now,
            "agent_type": agent_type,
            "baseline": porc_now,
        }
        _save_state(state)
        # State recorded, no verdict computed. Contract C1 state-writer wording
        # applied at branch level, which is why this is pass and not allow.
        _log_verdict("pass", "baseline %s" % agent_type)
        return 0

    if event == "SubagentStop":
        baseline_entry = state.pop(agent_id, None)
        _save_state(state)

        current = set(porc_now)

        # NO BASELINE means NO MEASUREMENT (2026-08-24). This used to fall back to
        # `set()`, which makes `current - baseline` the ENTIRE dirty working tree and
        # writes it out as though the subagent had produced it. Measured over the live
        # log before this change: 5,249 of 9,641 records had no baseline and averaged
        # 407 "new" files each, against 0.8 for records that actually had one. Those
        # records held 161.2 MB of the log's 162.8 MB, and produced 18,967 of 18,981
        # apparent ownership violations. All of it was the working tree, not the agent.
        #
        # So: record the fact and the count, never the tree. This is the fix for the
        # size problem too; the cap below is the second-order one.
        if baseline_entry is None:
            new_changes = []
            resolved_changes = []
            no_baseline_note = (
                "no SubagentStart baseline for this agent_id, so no delta could be "
                "computed. The dirty tree is NOT recorded here: it would be the "
                "repository's state, not this subagent's writes.")
        else:
            baseline = set(baseline_entry["baseline"])
            new_changes = sorted(current - baseline)
            resolved_changes = sorted(baseline - current)  # files that returned to clean
            no_baseline_note = None

        # Payload cap, ruled 2026-08-24: keep the count, keep enough paths to recognise
        # what happened, drop the rest. The count is what anyone reads; 20 paths is
        # enough to see the shape.
        CAP = 20
        new_total, resolved_total = len(new_changes), len(resolved_changes)
        truncated = new_total > CAP or resolved_total > CAP

        log_entry = {
            "ts": now,
            "event": "subagent_scope_check",
            "agent_id": agent_id,
            "agent_type": agent_type,
            "started_at": baseline_entry["started_at"] if baseline_entry else None,
            "new_changes": new_changes[:CAP],
            "new_changes_total": new_total,
            "resolved_changes": resolved_changes[:CAP],
            "resolved_changes_total": resolved_total,
            "new_changes_truncated": truncated,
            "had_baseline": baseline_entry is not None,
        }
        if no_baseline_note:
            log_entry["no_baseline_note"] = no_baseline_note
        _log(log_entry)

        # Emit WARN to stderr only if there are NEW changes: main session can
        # see them in the conversation. Resolved changes are positive (agent
        # cleaned up); silent log only.
        if new_changes:
            print(
                f"[SCOPE-CHECK] sub-agent {agent_type} ({agent_id[:16]}) "
                f"modified {new_total} new file(s). See "
                f".claude/hooks/subagent-scope-log.jsonl for paths.",
                file=sys.stderr,
            )
            _log_verdict("warn", "%s %d new" % (agent_type, new_total))
        else:
            _log_verdict("allow", agent_type)
        return 0

    # Unknown event: silent no-op
    _log_verdict("skip", event or "unknown")
    return 0


if __name__ == "__main__":
    sys.exit(main())
