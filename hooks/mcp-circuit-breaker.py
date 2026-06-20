"""
mcp-circuit-breaker.py: PreToolUse guard for MCP tool calls (ECC-LEARN-E1).

Closes the silent-dead-MCP-server failure mode: a server that has crashed or hung
returns errors on every subsequent call, the main session keeps trying, turns get
wasted. This hook tracks recent failures per server in a state file and trips a
breaker when failure rate exceeds a threshold. Tripped breaker → tool call is
DENIED with a clear message until either the cooldown expires, the user sets
the override env var, or `--reset` is run by hand.

Companion: `mcp-circuit-breaker-record.py` is the PostToolUse half that records
failures. This file is the PreToolUse half that reads the state and decides.

Tool-name shape:
    mcp__<server>__<tool>
The hook extracts <server> as the breaker key.

State file:
    .claude/hooks/_state/mcp-circuit-breaker.json
    Schema:
      {
        "<server>": {
          "failures": [iso_ts_string, ...],   # rolling list, capped
          "tripped_at": iso_ts_string | null,  # set when breaker trips
          "last_success_at": iso_ts_string | null
        },
        ...
      }

Defaults (overridable via env vars):
    THRESHOLD = 3 failures
    WINDOW    = 600 seconds (10 minutes)
    COOLDOWN  = 1800 seconds (30 minutes after trip, then breaker auto-resets)

Override:
    MCP_HEALTH_FAIL_OPEN=1 : bypass the breaker for the next call
    MCP_BREAKER_RESET=<server>: clear the breaker for a specific server

Exit codes: 0 always. Hook never crashes the parent session: fail-open.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Tunables (read once at startup so unit tests can patch via env)
# ---------------------------------------------------------------------------

def _int_env(name: str, default: int) -> int:
    try:
        v = int(os.environ.get(name, ""))
        return v if v > 0 else default
    except (TypeError, ValueError):
        return default


THRESHOLD = _int_env("MCP_BREAKER_THRESHOLD", 3)
WINDOW_SECONDS = _int_env("MCP_BREAKER_WINDOW_SECONDS", 600)
COOLDOWN_SECONDS = _int_env("MCP_BREAKER_COOLDOWN_SECONDS", 1800)

STATE_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "_state",
)
STATE_FILE = os.path.join(STATE_DIR, "mcp-circuit-breaker.json")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(s: str) -> datetime | None:
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _extract_server(tool_name: str) -> str | None:
    """mcp__<server>__<tool> → <server>. Returns None for non-MCP tools."""
    if not tool_name or not tool_name.startswith("mcp__"):
        return None
    rest = tool_name[len("mcp__"):]
    parts = rest.split("__", 1)
    if not parts or not parts[0]:
        return None
    return parts[0]


def load_state() -> dict:
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(state: dict) -> None:
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(state, fh, sort_keys=True, indent=2)
        os.replace(tmp, STATE_FILE)
    except OSError:
        pass


def prune_old_failures(server_state: dict, now: datetime) -> dict:
    """Drop failure timestamps older than WINDOW_SECONDS."""
    failures = server_state.get("failures") or []
    fresh = []
    cutoff = now.timestamp() - WINDOW_SECONDS
    for ts in failures:
        dt = _parse_iso(ts) if isinstance(ts, str) else None
        if dt is not None and dt.timestamp() >= cutoff:
            fresh.append(ts)
    server_state["failures"] = fresh
    return server_state


def is_tripped(server_state: dict, now: datetime) -> bool:
    """Breaker is tripped when: (a) tripped_at is set AND cooldown not yet expired,
    OR (b) failure count in current window >= THRESHOLD."""
    tripped_at = _parse_iso(server_state.get("tripped_at") or "")
    if tripped_at is not None:
        if now.timestamp() - tripped_at.timestamp() < COOLDOWN_SECONDS:
            return True
        # Cooldown expired: auto-reset
        server_state["tripped_at"] = None
    return len(server_state.get("failures") or []) >= THRESHOLD


def _emit_deny(server: str, server_state: dict, now: datetime) -> None:
    failure_count = len(server_state.get("failures") or [])
    tripped_at = server_state.get("tripped_at")
    cooldown_remaining = None
    tripped_dt = _parse_iso(tripped_at or "")
    if tripped_dt is not None:
        elapsed = now.timestamp() - tripped_dt.timestamp()
        cooldown_remaining = max(0, int(COOLDOWN_SECONDS - elapsed))

    reason_parts = [
        f"MCP CIRCUIT BREAKER: Blocked call to '{server}'.",
        f"This server has failed {failure_count} times in the last {WINDOW_SECONDS // 60} minutes.",
    ]
    if cooldown_remaining is not None:
        reason_parts.append(f"Cooldown remaining: ~{cooldown_remaining // 60} min.")
    reason_parts.append(
        "Likely causes: server crashed, hung, or lost auth. "
        "To force-attempt anyway, set MCP_HEALTH_FAIL_OPEN=1. "
        "To clear the breaker for this server, set MCP_BREAKER_RESET=" + server + "."
    )
    reason = " ".join(reason_parts)

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))


def _log_event(event: str, server: str, payload: dict, extra: dict | None = None) -> None:
    """Append to governance-log.jsonl. Silent on I/O failure."""
    try:
        log_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "governance-log.jsonl",
        )
        transcript_path = payload.get("transcript_path", "")
        session_id = (
            os.path.splitext(os.path.basename(transcript_path))[0]
            if transcript_path
            else "unknown"
        )
        entry = {
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "schema": 2,
            "event": event,
            "hook": "mcp-circuit-breaker",
            "session": session_id,
            "server": server,
        }
        if extra:
            entry.update(extra)
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def _is_override_set() -> bool:
    val = os.environ.get("MCP_HEALTH_FAIL_OPEN", "").strip().lower()
    return val in ("1", "true", "yes", "on")


def _reset_request() -> str | None:
    v = os.environ.get("MCP_BREAKER_RESET", "").strip()
    return v if v else None


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:
        return 0  # fail-open

    tool_name = payload.get("tool_name", "")
    server = _extract_server(tool_name)
    if server is None:
        return 0  # not an MCP tool: pass

    state = load_state()
    server_state = state.get(server) or {}
    now = datetime.now(timezone.utc)

    # Reset request for this server clears its breaker state and lets the call through
    reset_target = _reset_request()
    if reset_target == server:
        server_state["failures"] = []
        server_state["tripped_at"] = None
        state[server] = server_state
        save_state(state)
        _log_event("breaker_reset", server, payload)
        return 0

    # Prune stale failure timestamps
    server_state = prune_old_failures(server_state, now)

    if is_tripped(server_state, now):
        if _is_override_set():
            _log_event("breaker_override", server, payload, {
                "failure_count": len(server_state.get("failures") or [])
            })
            # Save the pruned state but do not deny
            state[server] = server_state
            save_state(state)
            return 0

        # Persist the tripped_at if it isn't already
        if not server_state.get("tripped_at"):
            server_state["tripped_at"] = _now_iso()
        state[server] = server_state
        save_state(state)
        _emit_deny(server, server_state, now)
        _log_event("breaker_blocked", server, payload, {
            "failure_count": len(server_state.get("failures") or [])
        })
        return 0

    # Breaker not tripped: save pruned state and allow
    state[server] = server_state
    save_state(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
