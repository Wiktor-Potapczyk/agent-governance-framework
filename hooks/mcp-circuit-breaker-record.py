"""
mcp-circuit-breaker-record.py: PostToolUse half of the MCP circuit breaker.

Records per-server failures and successes into the breaker state file so the
PreToolUse half (`mcp-circuit-breaker.py`) can decide when to block.

What counts as a "failure": heuristic:
    - tool_response.is_error is True
    - tool_response.error / tool_response.error_message is non-empty
    - tool_response contains the string "MCP error" / "error" near the start
    - tool_response is missing entirely (tool was killed / timed out)

What counts as a "success":
    - tool_response present, not error, has any non-trivial content

Successes RESET the failure list (the breaker is rate-of-failure based;
one good response means the server is alive). Successes do NOT clear a
tripped_at: that requires either MCP_BREAKER_RESET or cooldown expiry.

Exit codes: 0 always. Hook never crashes the parent session.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

STATE_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "_state",
)
STATE_FILE = os.path.join(STATE_DIR, "mcp-circuit-breaker.json")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _extract_server(tool_name: str) -> str | None:
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


def classify_response(tool_response) -> str:
    """Return 'failure' | 'success' | 'unknown'.

    Failure heuristics: dict with is_error=True or a non-empty 'error' field,
    or string starting with 'error' / 'MCP error' (case-insensitive),
    or tool_response missing entirely. Success: any other non-empty response.
    Unknown: tool_response present but ambiguous.
    """
    if tool_response is None:
        return "failure"
    if isinstance(tool_response, dict):
        if tool_response.get("is_error") is True:
            return "failure"
        err_fields = ("error", "error_message", "errorMessage")
        for f in err_fields:
            v = tool_response.get(f)
            if isinstance(v, str) and v.strip():
                return "failure"
        # Heuristic on a 'content' field containing the error keyword early
        content = tool_response.get("content")
        if isinstance(content, list) and content:
            first = content[0]
            if isinstance(first, dict):
                text = first.get("text", "")
                if isinstance(text, str):
                    head = text.strip()[:60].lower()
                    if head.startswith("error") or head.startswith("mcp error"):
                        return "failure"
        if tool_response:
            return "success"
        return "unknown"
    if isinstance(tool_response, str):
        head = tool_response.strip()[:60].lower()
        if head.startswith("error") or head.startswith("mcp error"):
            return "failure"
        return "success" if tool_response.strip() else "unknown"
    return "unknown"


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:
        return 0

    tool_name = payload.get("tool_name", "")
    server = _extract_server(tool_name)
    if server is None:
        return 0  # not an MCP tool

    tool_response = payload.get("tool_response")
    verdict = classify_response(tool_response)

    state = load_state()
    server_state = state.get(server) or {"failures": [], "tripped_at": None, "last_success_at": None}

    if verdict == "failure":
        failures = list(server_state.get("failures") or [])
        failures.append(_now_iso())
        # Cap retained list at 50 so the file doesn't grow unbounded
        if len(failures) > 50:
            failures = failures[-50:]
        server_state["failures"] = failures
    elif verdict == "success":
        # Success resets the failure window: the server is responsive
        server_state["failures"] = []
        server_state["last_success_at"] = _now_iso()
    # 'unknown' → don't change state

    state[server] = server_state
    save_state(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
