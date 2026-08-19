#!/usr/bin/env python3
"""
qmd-rerank-default-guard.py: PreToolUse guard enforcing rerank:false on mcp__qmd__query.

R3, CE-1 qmd substrate repair (2026-08-07).
Spec: Projects/your-project/work/2026-08-07-ce1-qmd-repair-plan.md, Phase 2.

TASK-007 investigated qmd's config surface for a server-side rerank default and found
NONE: QMD_CONFIG_DIR's index.yml defines only `collections:` (no rerank key at all);
`node qmd.js mcp --help` lists no mcp-subcommand rerank flag (only the generic top-level
help, and an `--http`/`--daemon` transport note); every `rerank` occurrence grepped
across the installed @tobilu/qmd package's dist/ tree was checked, and the MCP tool
schema default at dist/mcp/server.js:235 (`z.boolean().optional().default(true)`) is a
static Zod literal destructured straight from the incoming tool-call JSON args at line
237, with no process.env or config-object read anywhere upstream of it (the one
rerank-adjacent env var found, QMD_RERANK_MODEL at dist/llm.js:194, selects WHICH model
to use, not WHETHER to rerank (an orthogonal setting). So the only enforcement lever
available is this PreToolUse hook (structural fallback, TASK-007 Branch B).

This closes the query-path hang doctrine already stated in CLAUDE.md's Memory Recall
section ("ALWAYS pass rerank:false to mcp__qmd__query on this machine"); CLAUDE.md's
sentence is left untouched (TASK-012); this hook is the runtime enforcement UNDER that
standing prose rule, per this vault's hooks-over-prose doctrine.

Matching is EXACT tool-name (mcp__qmd__query only, NOT the blanket mcp__.* matcher
mcp-circuit-breaker.py / mcp-irreversible-guard.py use), since this hook concerns
exactly one tool. Deny fires when `rerank` is absent OR present but not exactly the
boolean `false` (an explicit `rerank: true` still denies: true is exactly the
hang-triggering value).

Mechanism: hookSpecificOutput.permissionDecision = "deny" plus permissionDecisionReason,
mirroring mcp-irreversible-guard.py's _emit_deny shape exactly (PAT-001: no
tool_input-mutation mechanism is evidenced anywhere in this hook suite: deny-with-
instruction is the only confirmed lever).

Exit codes: 0 always. Fail-open: the hook never crashes the parent session.
"""

from __future__ import annotations

import json
import os
import sys

TOOL_NAME = "mcp__qmd__query"


def _emit_deny(marker: str) -> None:
    reason = (
        f"QMD RERANK GUARD: Blocked '{TOOL_NAME}' ({marker}). "
        "This machine has no working GPU; the default rerank:true pipeline hangs "
        "indefinitely on the LLM reranking stage (documented: 300s+, no result). "
        "Reissue the call with rerank: false explicitly (measured 0.2s lex / 8.8s vec "
        "with rerank:false). Per CLAUDE.md's Memory Recall doctrine, ALWAYS pass "
        "rerank:false to mcp__qmd__query on this machine."
    )
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))


def _log(event: str, payload: dict, extra: dict | None = None) -> None:
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from _event_emit import emit_event
        from _governance_logger import session_from
        session_id = session_from(payload)
        merged = {"tool": TOOL_NAME}
        if extra:
            merged.update(extra)
        emit_event(
            event=event,
            hook="qmd-rerank-default-guard",
            session=session_id,
            extra=merged,
        )
    except Exception:
        pass


def rerank_is_missing_or_not_false(tool_input) -> bool:
    """True (deny) when `rerank` is absent, or present but not exactly bool False.

    An explicit `rerank: true` still denies: true is exactly the value that triggers
    the hang, so passing it explicitly does not earn an exemption.
    """
    if not isinstance(tool_input, dict):
        return True
    if "rerank" not in tool_input:
        return True
    return tool_input.get("rerank") is not False


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:
        return 0  # fail-open

    tool_name = payload.get("tool_name", "")
    if tool_name != TOOL_NAME:
        return 0  # matcher-scope leak guard: no-op on every other tool

    tool_input = payload.get("tool_input", {})
    if isinstance(tool_input, str):
        try:
            tool_input = json.loads(tool_input)
        except (json.JSONDecodeError, TypeError):
            tool_input = {}

    if rerank_is_missing_or_not_false(tool_input):
        missing = not isinstance(tool_input, dict) or "rerank" not in tool_input
        marker = "rerank absent" if missing else "rerank not false"
        _emit_deny(marker)
        _log("deny", payload, {"marker": marker})
        return 0

    # rerank: false explicit: allow silently
    return 0


if __name__ == "__main__":
    sys.exit(main())
