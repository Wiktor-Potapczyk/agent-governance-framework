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

VAULT = Path(os.environ.get("VAULT_ROOT", ""))
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
        return 0

    if event == "SubagentStop":
        baseline_entry = state.pop(agent_id, None)
        _save_state(state)

        baseline = set(baseline_entry["baseline"]) if baseline_entry else set()
        current = set(porc_now)
        new_changes = sorted(current - baseline)
        resolved_changes = sorted(baseline - current)  # files that returned to clean

        log_entry = {
            "ts": now,
            "event": "subagent_scope_check",
            "agent_id": agent_id,
            "agent_type": agent_type,
            "started_at": baseline_entry["started_at"] if baseline_entry else None,
            "new_changes": new_changes,
            "resolved_changes": resolved_changes,
            "had_baseline": baseline_entry is not None,
        }
        _log(log_entry)

        # Emit WARN to stderr only if there are NEW changes: main session can
        # see them in the conversation. Resolved changes are positive (agent
        # cleaned up); silent log only.
        if new_changes:
            print(
                f"[SCOPE-CHECK] sub-agent {agent_type} ({agent_id[:16]}) "
                f"modified {len(new_changes)} new file(s). See "
                f".claude/hooks/subagent-scope-log.jsonl for paths.",
                file=sys.stderr,
            )
        return 0

    # Unknown event: silent no-op
    return 0


if __name__ == "__main__":
    sys.exit(main())
