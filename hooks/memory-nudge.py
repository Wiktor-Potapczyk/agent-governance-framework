#!/usr/bin/env python3
"""memory-nudge.py: memory-persistence counter and nudge. Hermes P2 Mechanism B.

Spec: Projects/your-project/work/2026-08-17-hermes-p2-memory-governance-plan.md
(design decisions 7, 8, 11, 12, 13). Build plan: 2026-08-18-hermes-p2-build-v2-plan.md.

One file, two registrations, branching on hook_event_name
(subagent-scope-check.py dual-registration precedent):

  Stop          increments turns_since_memory_write by 1 per main-session turn
                close. Skips the increment when the payload carries
                stop_hook_active: true, so a Stop-chain continuation does not
                double-count a turn (spec decision 8). Prints nothing, ever.
  SessionStart  (registered on the `startup` and `resume` matchers) evaluates
                the counter and, past threshold, emits ONE additionalContext
                nudge (lint-cadence-trigger.py stdout-JSON precedent: never
                blocks). Fire condition: turns_since_memory_write >= 10 AND
                turns_since_memory_write - turns_at_last_nudge >= 10 (the
                anti-nag watermark, spec decision 12). On fire it stamps
                turns_at_last_nudge and last_nudge_iso.

The counter is RESET to zero only by a real memory-folder write, which
memory-context-guard.py performs at PreToolUse time (spec decision 9, the
Hermes reset-on-action rule). Threshold 10 is a calibration starting value
(spec decision 10), tunable in the observation step, not a spec constant.

State file: .claude/hooks/_state/memory-nudge.json, shape
{turns_since_memory_write, turns_at_last_nudge, last_memory_write_iso,
last_nudge_iso, updated_iso}. All writes atomic: tmp file then os.replace()
(subagent-scope-check.py _save_state precedent). Missing or corrupt state
bootstraps cleanly (lint-cadence-trigger.py bootstrap lesson). Last-writer-wins
races with concurrent sessions are accepted: the consumer is an advisory
nudge, not a gate (multi-session ruling 2026-08-08).

Nudge text contract (spec decision 13): explicitly permits "nothing to save"
as a correct outcome, requires evaluation against the do-not-capture list
before any save, and never pressures the agent to manufacture entries
(feedback_main_session_can_fabricate_inventory is the failure mode). The
wording passes prompt-engineer review before registration (build Step 6).

Env override for test isolation (resolved at call time, never at import):
  MEMORY_NUDGE_STATE_PATH  the state file (shared with memory-context-guard.py)

This hook NEVER returns a blocking decision on any code path: its only
outputs are nothing (Stop, below-threshold SessionStart) or additionalContext
(threshold fire). Exit 0 always; any internal exception exits 0 silently.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

_HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_STATE_PATH = os.path.join(_HOOKS_DIR, "_state", "memory-nudge.json")

THRESHOLD = 10  # calibration starting value (spec decision 10), not a constant of the spec

_STATE_DEFAULTS = {
    "turns_since_memory_write": 0,
    "turns_at_last_nudge": 0,
    "last_memory_write_iso": "",
    "last_nudge_iso": "",
    "updated_iso": "",
}

NUDGE_TEMPLATE = (
    "[MEMORY PERSISTENCE] {turns} main-session turns have closed since the last "
    "memory-folder write. Take one review pass over recent work for durable, "
    "verified knowledge worth persisting to the memory folder (MEMORY.md "
    "one-line index plus one-fact topic files, the ratified two-tier structure). "
    "Saving nothing is a correct outcome: if nothing qualifies, say so in your "
    "response and move on, do not write a memory file just to record that "
    "nothing qualified; never manufacture an entry to satisfy this reminder. Before "
    "saving anything, check it against the do-not-capture list: "
    "environment-dependent failures, negative claims about tools, and "
    "unresolved failure narratives stay out, because such entries harden into "
    "refusals the agent cites against itself for months after the actual "
    "problem was fixed."
)


def _state_path() -> str:
    return os.environ.get("MEMORY_NUDGE_STATE_PATH", "").strip() or _DEFAULT_STATE_PATH


def _load_state() -> dict:
    """Read the state file; bootstrap defaults on missing/corrupt content."""
    state = dict(_STATE_DEFAULTS)
    try:
        with open(_state_path(), "r", encoding="utf-8") as fh:
            loaded = json.load(fh)
        if isinstance(loaded, dict):
            state.update(loaded)
    except Exception:
        pass
    for key in ("turns_since_memory_write", "turns_at_last_nudge"):
        try:
            state[key] = int(state.get(key, 0))
        except (TypeError, ValueError):
            state[key] = 0
    return state


def _save_state(state: dict) -> None:
    """Atomic tmp-then-os.replace write. Never raises; a lost update under a
    concurrent last-writer-wins race is accepted (advisory tier)."""
    try:
        path = _state_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2)
        os.replace(tmp, path)
    except Exception:
        pass


def _handle_stop(payload: dict) -> None:
    """One increment per main-session turn close; no output on any path."""
    if payload.get("stop_hook_active"):
        return  # Stop-chain continuation: not a new turn (spec decision 8)
    state = _load_state()
    state["turns_since_memory_write"] += 1
    state["updated_iso"] = datetime.now(timezone.utc).isoformat()
    _save_state(state)


def _handle_session_start(payload: dict) -> None:
    """Evaluate the counter; past threshold and watermark, emit ONE nudge."""
    state = _load_state()
    turns = state["turns_since_memory_write"]
    watermark = state["turns_at_last_nudge"]
    if turns < THRESHOLD or (turns - watermark) < THRESHOLD:
        return  # below threshold, or inside the anti-nag window: silence
    now_iso = datetime.now(timezone.utc).isoformat()
    state["turns_at_last_nudge"] = turns
    state["last_nudge_iso"] = now_iso
    state["updated_iso"] = now_iso
    _save_state(state)
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": NUDGE_TEMPLATE.format(turns=turns),
        }
    }))


def main() -> int:
    try:
        raw = sys.stdin.read()
    except Exception:
        return 0
    try:
        payload = json.loads(raw or "{}")
    except Exception:
        return 0
    try:
        if not isinstance(payload, dict):
            return 0
        event = payload.get("hook_event_name") or payload.get("hookEventName") or ""
        if event == "Stop":
            _handle_stop(payload)
        elif event == "SessionStart":
            _handle_session_start(payload)
        return 0
    except Exception:
        # Advisory tier: any failure exits silently, never blocks a turn.
        return 0


if __name__ == "__main__":
    sys.exit(main())
