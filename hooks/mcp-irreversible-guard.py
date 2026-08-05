"""
mcp-irreversible-guard.py: PreToolUse guard for irreversible MCP tool calls.

Two-Gate Autonomy Enforcement, Gate-1 (reversibility HARD FLOOR), MCP fire point.
Spec: Projects/your-project/work/2026-06-15-two-gate-enforcement-spec.md

The Bash safety guard cannot see MCP tool calls (a Bash matcher never fires on an
mcp__* tool). This separate PreToolUse hook (registered under the mcp__.* matcher,
alongside mcp-circuit-breaker.py) denies the irreversible MCP surface enumerated in
_irreversible_surface.IRREVERSIBLE_MCP_TOOLS.

S0 verdict (2026-06-16): CONFIRMED: a PreToolUse permissionDecision:"deny" DOES block
an MCP tool call in this harness (canary: a tripped mcp-circuit-breaker deny blocked a
live mcp__n8n-mcp__n8n_health_check call). So this hook's deny has real teeth.

Matching is EXACT tool-name + (for dual-use tools) a payload predicate. There is NO
blanket mcp__.* deny: read tools and benign writes pass. The deny emits a decision
brief; the human gate is the !-prefix manual bypass (skips PreToolUse), identical to
the Bash force-push pattern.

Exit codes: 0 always. Fail-open: the hook never crashes the parent session.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from _irreversible_surface import mcp_tool_is_irreversible
except Exception:  # fail-open if the shared module can't load
    mcp_tool_is_irreversible = None


def _emit_deny(tool_name: str, marker: str) -> None:
    reason = (
        f"GATE-1 IRREVERSIBLE MCP: Blocked '{tool_name}' ({marker}). "
        f"This call is on the canonical irreversible surface (delete / activation flip / "
        f"destructive datatable op / irreversible external side effect). "
        f"Surface a decision brief (what, why, options + recommendation) to the owner. "
        f"If intentional, re-issue via the !-prefix manual path (which skips PreToolUse hooks)."
    )
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))


def _log(event: str, tool_name: str, payload: dict, extra: dict | None = None) -> None:
    try:
        from _event_emit import emit_event
        transcript_path = payload.get("transcript_path", "")
        from _governance_logger import session_from
        session_id = session_from(payload)
        merged = {"tool": tool_name}
        if extra:
            merged.update(extra)
        emit_event(
            event=event,
            hook="mcp-irreversible-guard",
            session=session_id,
            extra=merged,
        )
    except Exception:
        pass


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:
        return 0  # fail-open

    if mcp_tool_is_irreversible is None:
        return 0  # shared module unavailable: fail-open

    tool_name = payload.get("tool_name", "")
    if not tool_name.startswith("mcp__"):
        return 0  # not an MCP tool

    tool_input = payload.get("tool_input", {})
    if isinstance(tool_input, str):
        try:
            tool_input = json.loads(tool_input)
        except (json.JSONDecodeError, TypeError):
            tool_input = {}

    is_irr, marker = mcp_tool_is_irreversible(tool_name, tool_input)
    if is_irr:
        _emit_deny(tool_name, marker)
        _log("deny", tool_name, payload, {"marker": marker})
        return 0

    # benign / read / non-activation update: allow silently
    return 0


if __name__ == "__main__":
    sys.exit(main())
