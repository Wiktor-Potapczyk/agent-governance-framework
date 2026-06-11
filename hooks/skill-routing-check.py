"""
Skill Routing Check - PreToolUse Hook (matcher: Skill)
Validates that the process skill being invoked matches the TASK TYPE from classification.
Allows non-process skills (task-classifier, save, ensemble, etc.) unconditionally.
Blocks misrouted process skills.

Regex hardening (2026-03-22):
- 200KB window (up from 80KB) to capture large agent outputs
- Fence stripping: ignores content inside ``` blocks (prevents false matches on docs/examples)
"""

import sys
import json
import os
import re


# Routing table: TYPE -> expected process skill
ROUTING = {
    "research": "process-research",
    "analysis": "process-analysis",
    "content": "process-build",  # Content routes through process-build (content-marketer as builder)
    "build": "process-build",
    "planning": "process-planning",
    "compound": "process-analysis",  # Compound uses process-analysis in Decomposition mode
}

# Process skills that are subject to routing validation
PROCESS_SKILLS = set(ROUTING.values())

# 200KB window — covers even 10+ agent outputs per turn
READ_BYTES = 204800


def strip_fences(text):
    """Remove markdown fenced code blocks to prevent false matches on examples/docs."""
    return re.sub(r'```[\s\S]*?```', '', text)


def main():
    payload_text = sys.stdin.read()
    if not payload_text:
        return

    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError:
        return

    try:
        import os as _gho, sys as _ghs
        _ghs.path.insert(0, _gho.path.dirname(_gho.path.abspath(__file__)))
        from _governance_logger import log_fire
        log_fire("skill-routing-check")
    except Exception:
        pass

    # Get the skill being invoked
    tool_input = payload.get("tool_input", {})
    if isinstance(tool_input, str):
        try:
            tool_input = json.loads(tool_input)
        except (json.JSONDecodeError, TypeError):
            tool_input = {}

    skill_name = (tool_input.get("skill") or "").lower()
    if not skill_name:
        return

    # If it's not a process skill, allow unconditionally
    # (task-classifier, save, ensemble, verify, architect-loop, etc.)
    if skill_name not in PROCESS_SKILLS:
        return

    # It IS a process skill — check if it matches the last classification
    transcript_path = payload.get("transcript_path")
    if not transcript_path or not os.path.exists(transcript_path):
        return  # Can't verify, allow

    # Read last 200KB of transcript
    file_size = os.path.getsize(transcript_path)
    read_bytes = min(READ_BYTES, file_size)

    with open(transcript_path, "r", encoding="utf-8") as f:
        f.seek(max(0, file_size - read_bytes))
        tail = f.read()

    # Workflow-boundary reset (B-0 fix, 2026-06-11):
    # A Workflow tool_use whose name maps to a process skill is a routing-context
    # reset — it consumed the TASK TYPE classification that triggered it. Any Skill
    # invocation that follows should not be blocked by that stale classification.
    # We track the LAST routing event: either a TASK TYPE assertion (text) or a
    # Workflow dispatch (tool_use name="Workflow"). If the most recent routing event
    # is a Workflow dispatch, we clear last_type before comparing.
    last_type = None
    last_workflow_routing_reset = False  # True if the most-recent routing event was a Workflow
    valid_types = re.compile(r'(?:TASK TYPE|CLASSIFICATION):\s*(Quick|Research|Analysis|Content|Build|Planning|Compound)', re.IGNORECASE)

    # Set of process-skill names a Workflow might be named after (matches ROUTING values)
    WORKFLOW_PROCESS_NAMES = set(ROUTING.values()) | set(ROUTING.keys())
    # Also the raw "process-*" prefix covers future skills
    def _wf_name_is_process(wf_name: str) -> bool:
        """Return True if a Workflow invocation name maps to a process skill."""
        n = wf_name.lower().strip()
        if n.startswith("process-"):
            return True
        # scriptPath basename without .js (e.g. ".claude/workflows/process-planning.js")
        base = os.path.basename(n)
        if base.endswith(".js"):
            base = base[:-3]
        return base.startswith("process-")

    for line in tail.split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        if entry.get("type") != "assistant":
            continue

        message = entry.get("message", {})
        for block in message.get("content", []):
            if block.get("type") == "text":
                text = block.get("text", "")
                # Strip fenced code blocks to avoid matching examples/docs
                clean = strip_fences(text)
                m = valid_types.search(clean)
                if m:
                    last_type = m.group(1).lower()
                    last_workflow_routing_reset = False  # TASK TYPE assertion wins
            elif block.get("type") == "tool_use" and block.get("name") == "Workflow":
                inp = block.get("input", {})
                if isinstance(inp, str):
                    try:
                        inp = json.loads(inp)
                    except (json.JSONDecodeError, TypeError):
                        inp = {}
                wf_name = (inp.get("name") or inp.get("workflow_name") or "").strip()
                if not wf_name:
                    sp = inp.get("scriptPath") or ""
                    base = os.path.basename(sp)
                    wf_name = base[:-3] if base.endswith(".js") else base
                if _wf_name_is_process(wf_name):
                    # This Workflow consumed the last TASK TYPE — mark as reset
                    last_workflow_routing_reset = True

    # If the most-recent routing event was a Workflow dispatch, the classification
    # context has been consumed. Clear last_type so the next Skill invocation is
    # not blocked by stale residue from that Workflow's input classification.
    if last_workflow_routing_reset:
        last_type = None

    # If no classification found or Quick, allow
    if not last_type or last_type == "quick":
        return

    # Check if the process skill matches the routing table
    expected_skill = ROUTING.get(last_type)
    if not expected_skill:
        return  # Unknown type, allow

    if skill_name != expected_skill:
        reason = (
            f"SKILL ROUTING: TASK TYPE is '{last_type}' which should invoke "
            f"'{expected_skill}', but '{skill_name}' was invoked instead. "
            f"Use the correct process skill."
        )
        result = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }
        print(json.dumps(result))
        # Log deny event
        try:
            from datetime import datetime
            log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "governance-log.jsonl")
            session_id = os.path.splitext(os.path.basename(transcript_path))[0] if transcript_path else "unknown"  # Full UUID (P1-D fix 2026-04-09)
            entry = json.dumps({"ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "event": "deny", "hook": "skill-routing-check", "session": session_id, "attempted": skill_name, "expected": expected_skill, "type": last_type, "schema": 2})
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(entry + "\n")
        except Exception:
            pass
        return

    # Correct routing — allow
    return


if __name__ == "__main__":
    main()
