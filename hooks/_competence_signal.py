"""Structural reliability signal for the Step-11 competence gate (2026-07-13).

Computes a per-agent STRUCTURAL RELIABILITY score from governance-log.jsonl
completion events. This is NOT semantic competence: a semantically wrong but
well-formatted output passes all three structural checks (signal-source
research §Q4d). It is a lower-bound proxy — agents that fail even structurally
are the strongest gate candidates. Every consumer-facing message must use the
phrase "structural reliability signal" (spec DQ-1 honest-naming requirement).

Completion events counted (per agent_type, pre-filtered):
  PASS   {"event": "pass",  "hook": "subagent-quality-check"}
  BLOCK  {"event": "block", "hook": "subagent-quality-check"}   (Shape D)
  SCOPE  {"event": "reviewer_scope_violation"}                  (Shape G)

Mandatory pre-filter: entries with session == 'session' are synthetic
subprocess-test pollution and are dropped before any counting.

score   = passes / (passes + blocks + scope_violations) over the last
          WINDOW_PER_AGENT completion events for that agent.
verdict = NO_SIGNAL (n < WARMUP_N) | OK (score >= threshold) | BELOW.

Fail-open contract: no function here ever raises to the caller; the gate
built on top of this module is ADVISORY-ONLY and structurally incapable of
denying a dispatch. MODE is a constant — the ENFORCE flip is spec Step 8,
owner-gated, and deliberately NOT implemented anywhere in this module.

Stdlib only. No side effects at import.
"""

import json
import os

# ---------------------------------------------------------------------------
# Config block — single Wiktor-editable location (spec DQ-2: hand-owned,
# git-tracked, single-line-editable; changes are Quick-class edits).
# ---------------------------------------------------------------------------
ADVISORY_THRESHOLD = 0.8      # placeholder; enforce threshold TBD from window
WARMUP_N = 5                  # below this n the verdict is NO_SIGNAL
WINDOW_PER_AGENT = 50         # last-N completion events per agent_type
TAIL_READ_BYTES = 1_048_576   # bounded tail read of governance-log.jsonl
MODE = "ADVISORY"             # ENFORCE is spec Step 8 (owner-gated, NOT built)

# Synthetic subprocess-test session marker (dropped by pre-filter).
_SYNTHETIC_SESSION = "session"

_QUALITY_HOOK = "subagent-quality-check"
_SCOPE_EVENT = "reviewer_scope_violation"


def read_log_tail(path, max_bytes=TAIL_READ_BYTES):
    """Bounded tail read of a log file. Returns '' on any OS error (fail-open)."""
    try:
        size = os.path.getsize(path)
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            f.seek(max(0, size - max_bytes))
            return f.read()
    except OSError:
        return ""


def parse_events(text):
    """Parse JSONL text to a list of dicts.

    Malformed lines are skipped silently; synthetic-session entries
    (session == 'session') are dropped (mandatory analytic pre-filter).
    """
    events = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(entry, dict):
            continue
        if entry.get("session") == _SYNTHETIC_SESSION:
            continue
        events.append(entry)
    return events


def _is_completion(entry, agent_type):
    """True if entry is one of the three completion shapes for agent_type."""
    if entry.get("agent_type") != agent_type:
        return False
    event = entry.get("event")
    if event in ("pass", "block") and entry.get("hook") == _QUALITY_HOOK:
        return True
    if event == _SCOPE_EVENT:
        return True
    return False


def score_agent(events, agent_type):
    """Score one agent_type from pre-parsed events (pure function, no I/O).

    Returns {"score": float|None, "n": int, "verdict": str}. Only the LAST
    WINDOW_PER_AGENT completion events for the agent count (older excluded).
    """
    completions = [e for e in events if _is_completion(e, agent_type)]
    window = completions[-WINDOW_PER_AGENT:]
    n = len(window)
    if n < WARMUP_N:
        return {"score": None, "n": n, "verdict": "NO_SIGNAL"}
    passes = sum(1 for e in window if e.get("event") == "pass")
    score = passes / n
    verdict = "OK" if score >= ADVISORY_THRESHOLD else "BELOW"
    return {"score": score, "n": n, "verdict": verdict}


def get_verdict(log_path, agent_type):
    """Composition wrapper: tail-read + parse + score. NEVER raises.

    Any internal exception returns the fail-open safe object
    {"score": None, "n": 0, "verdict": "NO_SIGNAL", "error": True}.
    """
    try:
        text = read_log_tail(log_path, TAIL_READ_BYTES)
        events = parse_events(text)
        return score_agent(events, agent_type)
    except Exception:
        return {"score": None, "n": 0, "verdict": "NO_SIGNAL", "error": True}
