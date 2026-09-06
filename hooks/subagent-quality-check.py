#!/usr/bin/env python3
"""SubagentStop Hook - L2 exit gate: structural quality check on agent output."""
import json
import sys
import os
import re
from datetime import datetime

# Pure detection logic lives in the sibling module (extracted 2026-06-02 for
# boundary-testability: see _subagent_quality_logic.py). Make it importable.
_HOOK_DIR = os.path.dirname(os.path.abspath(__file__))
if _HOOK_DIR not in sys.path:
    sys.path.insert(0, _HOOK_DIR)
from _subagent_quality_logic import classify_subagent_output  # noqa: E402


# Stand-in recorded when a sub-agent answered through a tool call rather than
# text. Deliberately short and structured so it clears the empty-output check
# without tripping the long-unstructured-output check.
STRUCTURED_ANSWER_SENTINEL = "- structured answer returned via tool call"

# The final turn is at the END of a transcript, so a tail read is correct here.
# Contrast reviewer-scope-violation-check, which needs the dispatch prompt at the
# HEAD and was reading the tail, which is why it never fired.
_FINAL_TURN_TAIL_BYTES = 65536


def _final_turn_used_tool(agent_transcript_path):
    """True when the sub-agent's last assistant entry contains a tool_use block.

    Fails CLOSED: any missing path, unreadable file or parse error returns False,
    which preserves the existing empty-output block. A false negative costs one
    spurious block; a false positive would wave through a genuinely dead agent.
    """
    if not agent_transcript_path or not os.path.exists(agent_transcript_path):
        return False
    try:
        size = os.path.getsize(agent_transcript_path)
        with open(agent_transcript_path, "r", encoding="utf-8", errors="replace") as fh:
            fh.seek(max(0, size - _FINAL_TURN_TAIL_BYTES))
            tail = fh.read()
        last_assistant = None
        for raw in tail.split("\n"):
            raw = raw.strip()
            if not raw:
                continue
            try:
                entry = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if entry.get("type") == "assistant":
                last_assistant = entry
        if not last_assistant:
            return False
        content = last_assistant.get("message", {}).get("content") or []
        if not isinstance(content, list):
            return False
        return any(
            isinstance(b, dict) and b.get("type") == "tool_use" for b in content
        )
    except Exception:
        return False


# O9 increment 2 (2026-09-01): workflow-identity plumbing. The dispatch site
# (.claude/workflows/*.js, wfAgent wrapper) writes 'WORKFLOW-ID: <meta.name>'
# as the literal first line of every agent() prompt; that prompt is the FIRST
# record of the subagent's own transcript (verified on live run dirs), so a
# bounded head read recovers the identity, the symmetric operation to the
# tail read above. The run id is the path component after
# subagents/workflows/. Fails OPEN: identity is telemetry, never a gating
# input, so any failure returns (None, None) and the pass/block decision is
# untouched. A marker miss on a real workflow subagent is emitted as JSON
# null rather than omitted, so it stays visible in the record.
_WORKFLOW_HEAD_BYTES = 65536
_WORKFLOW_MARKER_RE = re.compile(r"\AWORKFLOW-ID:[ \t]*([A-Za-z0-9._-]+)")


def _workflow_identity(agent_transcript_path):
    """(workflow_name_or_None, workflow_run_or_None) from a workflow subagent's
    own transcript path. Fail-open on every error path."""
    try:
        name = None
        run = None
        if not agent_transcript_path:
            return (None, None)
        norm = str(agent_transcript_path).replace(chr(92), "/")
        m = re.search(r"/subagents/workflows/([^/]+)/", norm)
        if m:
            run = m.group(1)
        if os.path.exists(agent_transcript_path):
            with open(agent_transcript_path, "r", encoding="utf-8", errors="replace") as fh:
                head = fh.read(_WORKFLOW_HEAD_BYTES)
            for raw in head.splitlines():
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    entry = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if entry.get("type") != "user":
                    continue
                content = entry.get("message", {}).get("content")
                text = None
                if isinstance(content, str):
                    text = content
                elif isinstance(content, list):
                    for b in content:
                        if isinstance(b, dict) and b.get("type") == "text":
                            text = b.get("text")
                            break
                if isinstance(text, str):
                    mm = _WORKFLOW_MARKER_RE.match(text)
                    if mm:
                        name = mm.group(1)
                # only the FIRST user record is the dispatch prompt
                break
        return (name, run)
    except Exception:
        return (None, None)


def main():
    try:
        raw = sys.stdin.read()
    except Exception:
        return

    if not raw:
        return

    try:
        payload = json.loads(raw)
    except Exception:
        return

    # Prevent infinite loops
    if payload.get("stop_hook_active") is True:
        return

    agent_type = payload.get("agent_type", "unknown")
    agent_id = payload.get("agent_id", "unknown")
    message = payload.get("last_assistant_message", "")

    # A sub-agent that answers through a tool call (a Workflow agent with a
    # `schema` is REQUIRED to use StructuredOutput) ends its turn with an empty
    # text message. Reading only last_assistant_message scored that as "empty
    # output" and blocked on SubagentStop, forcing a retry: 780 of 930 such
    # blocks were agent_type=workflow-subagent at a 91% rate, roughly 37% of all
    # blocking in the log. The SubagentStop payload carries `agent_transcript_path`
    # (the sub-agent's OWN transcript, distinct from transcript_path), so the
    # structured answer is reachable without a blanket exemption. Verified by an
    # instrumented dispatch 2026-08-04. Genuinely empty agents are still caught.
    if not (message or "").strip():
        if _final_turn_used_tool(payload.get("agent_transcript_path")):
            message = STRUCTURED_ANSWER_SENTINEL
    message_len = len(message)

    # P1-D fix (2026-04-09): full session UUID, needed for cross-source joins.
    # 2026-08-01: the derivation used to sit inside an `if transcript_path:` guard,
    # which made it unreachable in the one case that matters, a payload carrying a
    # session_id but no transcript. session_from already handles both sources and
    # returns None when identity is genuinely absent, so the guard only blocked it.
    from _governance_logger import session_from
    session_id = session_from(payload) or "unknown"

    # O9 increment 2 (2026-09-01): workflow identity for the two governance
    # emits below. Only workflow subagents pay the head read; every other
    # agent_type skips it entirely and its records carry no new fields.
    workflow_name = None
    workflow_run = None
    if agent_type == "workflow-subagent":
        workflow_name, workflow_run = _workflow_identity(payload.get("agent_transcript_path"))

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "subagent-quality.log")

    def log_and_block(result, check_failed, reason):
        # 2026-05-10: capture violation excerpt so log entries are auditable
        # (per finding_must_dispatch_compliance_53pct.md: 11 unauditable blocks/week pre-fix)
        violation_excerpt = (message[:200] + "...") if message_len > 200 else message
        violation_excerpt = violation_excerpt.replace("\n", " ").replace("\r", " ").strip()

        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"{timestamp} | agent={agent_type} | id={agent_id} | len={message_len} | result={result} | failed={check_failed} | excerpt={violation_excerpt[:120]}\n")
        except Exception:
            pass
        # Also log to governance-log.jsonl
        # P1-D + P1-E fix (2026-04-09): added session + schema fields for analytics joins
        # 2026-05-10: added violation_excerpt + reason for actionable diagnostics
        try:
            from _event_emit import emit_event
            _extra = {
                "agent_type": agent_type,
                "agent_id": agent_id,
                "message_len": message_len,
                "check_failed": check_failed,
                "violation_excerpt": violation_excerpt,
                "block_reason": reason,
            }
            # O9 increment 2: identity fields for workflow subagents only.
            if agent_type == "workflow-subagent":
                _extra["workflow"] = workflow_name
                _extra["workflow_run"] = workflow_run
            emit_event(
                event="block",
                hook="subagent-quality-check",
                session=session_id,
                extra=_extra,
            )
        except Exception:
            pass
        response = {"decision": "block", "reason": reason}
        print(json.dumps(response))
        sys.exit(0)

    # Structural quality checks (CHECK 1/2/3): extracted to
    # _subagent_quality_logic.classify_subagent_output 2026-06-02 for
    # boundary-testability; behavior preserved exactly.
    blocked, check_failed, reason = classify_subagent_output(message)
    if blocked:
        log_and_block("BLOCK", check_failed, reason)

    # All checks passed
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"{timestamp} | agent={agent_type} | id={agent_id} | len={message_len} | result=PASS\n")
    except Exception:
        pass
    # Step-11 competence gate (2026-07-13): persist the PASS as a structured
    # governance-log event: mirror of the Shape D block entry minus
    # check_failed/violation_excerpt/block_reason. Per-agent PASS rate was
    # "the single largest gap for per-agent analytics" (signal-source research
    # §Q4d). Fail-silent: telemetry must never break the SubagentStop flow.
    try:
        from _event_emit import emit_event
        _extra = {
            "agent_type": agent_type,
            "agent_id": agent_id,
            "message_len": message_len,
        }
        # O9 increment 2: identity fields for workflow subagents only.
        if agent_type == "workflow-subagent":
            _extra["workflow"] = workflow_name
            _extra["workflow_run"] = workflow_run
        emit_event(
            event="pass",
            hook="subagent-quality-check",
            session=session_id,
            extra=_extra,
        )
    except Exception:
        pass

if __name__ == "__main__":
    main()
