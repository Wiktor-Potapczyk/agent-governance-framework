"""
Process Step Check - Stop Hook
L1 exit gate: verifies process skill steps were actually followed.
Complements skill-step-reminder (soft PostToolUse) with hard enforcement.

HARD blocks (clear violations):
- Missing SCOPE block for the invoked process skill
- Missing QA REPORT with PASS/FAIL for process-qa
- Increment complete (all tasks done + pentest) but /pm not invoked

SOFT logging (judgment-dependent, collected for analysis):
- Synthesis not dispatched when 2+ agents contributed
- architect-review not dispatched for process-build/process-planning
- Zero agent dispatches for process skills that should delegate

All checks logged to governance-log.jsonl for analysis.
"""

import sys
import json
import os
import re

# 200KB window — matches other hardened hooks
READ_BYTES = 204800

# Expected SCOPE block per process skill
SCOPE_PATTERNS = {
    "process-research": "RESEARCH SCOPE",
    "process-analysis": "ANALYSIS SCOPE",
    "process-build": "BUILD SCOPE",
    "process-planning": "PLANNING SCOPE",
    "process-qa": "QA SCOPE",
    "process-pentest": "PENTEST SCOPE",
}


def strip_fences(text):
    """Remove markdown fenced code blocks to prevent false matches."""
    return re.sub(r'```[\s\S]*?```', '', text)


def check_scope(process_skill, text_blocks):
    """HARD: Check that the appropriate SCOPE block is present."""
    pattern = SCOPE_PATTERNS.get(process_skill)
    if not pattern:
        return True, ""
    for text in text_blocks:
        if pattern in text:
            return True, ""
    return False, f"Missing {pattern} block"


def check_qa_report(process_skill, text_blocks):
    """HARD: For process-qa, check QA REPORT block with PASS/FAIL."""
    if process_skill != "process-qa":
        return True, ""
    for text in text_blocks:
        if "QA REPORT" in text and re.search(r'(?:PASS|FAIL)', text):
            return True, ""
    # Allow graceful exit when no verifiable claims
    for text in text_blocks:
        if re.search(r'no verifiable claims', text, re.IGNORECASE):
            return True, ""
    return False, "Missing QA REPORT with PASS/FAIL counts"


def check_pentest_report(process_skill, text_blocks):
    """HARD: For process-pentest, check PENTEST REPORT block with findings."""
    if process_skill != "process-pentest":
        return True, ""
    for text in text_blocks:
        if "PENTEST REPORT" in text and re.search(r'(?:PASS|FAIL|SHIP|FIX|ESCALATE)', text):
            return True, ""
    return False, "Missing PENTEST REPORT with findings and recommendation"


def check_pm_checkpoint_report(lines):
    """HARD: When /pm was invoked, check for PM CHECKPOINT REPORT with Viability verdict.
    B2 fix (2026-04-13): Also verifies pm-orchestrator was actually dispatched — prevents
    rubber-stamping by writing an inline report without dispatching the agent.
    Independent of process-skill tracking — scans full transcript like check_pm_after_increment."""
    pm_invoked = False
    pm_orchestrator_dispatched = False  # B2 fix: track agent dispatch
    text_after_pm = []

    for line in lines:
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
            if block.get("type") == "tool_use" and block.get("name") == "Skill":
                inp = block.get("input", {})
                if isinstance(inp, str):
                    try:
                        inp = json.loads(inp)
                    except (json.JSONDecodeError, TypeError):
                        inp = {}
                skill = (inp.get("skill") or "").lower()
                if skill == "pm":
                    pm_invoked = True
                    pm_orchestrator_dispatched = False  # Reset per-invocation
                    text_after_pm = []  # Reset — track text after latest /pm invocation

            # B2 fix: detect pm-orchestrator Agent dispatch after pm Skill
            if pm_invoked and block.get("type") == "tool_use" and block.get("name") == "Agent":
                inp = block.get("input", {})
                if isinstance(inp, str):
                    try:
                        inp = json.loads(inp)
                    except (json.JSONDecodeError, TypeError):
                        inp = {}
                agent_type = (inp.get("subagent_type") or "").lower()
                if agent_type == "pm-orchestrator":
                    pm_orchestrator_dispatched = True

            if pm_invoked and block.get("type") == "text":
                text_after_pm.append(block.get("text", ""))

    if not pm_invoked:
        return True, ""  # /pm not invoked — nothing to check

    for text in text_after_pm:
        if "PM CHECKPOINT REPORT" in text and re.search(r'Viability:\s*(?:PASS|HOLD|KILL)', text):
            # B2 fix: report present — but was pm-orchestrator actually dispatched?
            if pm_orchestrator_dispatched:
                return True, ""
            else:
                return False, "PM CHECKPOINT REPORT present but pm-orchestrator agent was not dispatched — inline PM is not valid"

    return False, "PM invoked but missing PM CHECKPOINT REPORT with Viability verdict"


def check_synthesis(process_skill, agents):
    """SOFT: If 2+ agents dispatched in research/analysis, synthesis needed."""
    if process_skill not in ("process-research", "process-analysis"):
        return True, ""
    if len(agents) < 2:
        return True, ""
    agent_names = {a.lower() for a in agents}
    if any("synth" in a for a in agent_names):
        return True, ""
    return False, f"{len(agents)} agents but no synthesizer"


def check_architect_review(process_skill, agents):
    """SOFT: For build/planning, architect-review should be dispatched."""
    if process_skill not in ("process-build", "process-planning"):
        return True, ""
    agent_names = {a.lower() for a in agents}
    if any("architect" in a and "review" in a for a in agent_names):
        return True, ""
    return False, "No architect-review dispatch"


def check_agent_dispatch(process_skill, agents):
    """SOFT: Process skills should typically dispatch at least one agent."""
    if process_skill in ("process-qa", "process-pentest"):
        return True, ""  # QA and pentest run inline tests, not agent dispatch
    if len(agents) >= 1:
        return True, ""
    return False, "Zero agents dispatched"


def check_pm_after_increment(lines):
    """HARD: Multi-step increments (2+ TaskCreate) require /pm after all tasks complete + pentest.
    Independent of process skill invocations — runs on every Stop event."""
    task_creates = 0
    task_completes = 0
    pentest_seen = False

    for line in lines:
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
            if block.get("type") != "tool_use":
                continue
            name = block.get("name", "")
            inp = block.get("input", {})
            if isinstance(inp, str):
                try:
                    inp = json.loads(inp)
                except (json.JSONDecodeError, TypeError):
                    inp = {}

            if name == "TaskCreate":
                task_creates += 1
            elif name == "TaskUpdate":
                if (inp.get("status") or "") == "completed":
                    task_completes += 1
            elif name == "Skill":
                skill = (inp.get("skill") or "").lower()
                if skill == "process-pentest":
                    pentest_seen = True
                elif skill == "pm":
                    # PM invoked = increment closed. Reset ALL state for next increment.
                    task_creates = 0
                    task_completes = 0
                    pentest_seen = False

    # Only enforce for multi-step increments
    if task_creates < 2:
        return True, ""

    # Increment not fully complete yet
    if task_completes < task_creates:
        return True, ""

    # Pentest not done yet — pentest enforcement handles this separately
    if not pentest_seen:
        return True, ""

    # All tasks done + pentest done — PM should have been invoked (which resets task_creates).
    # If we reach here, task_creates >= 2 means PM was NOT invoked for this increment.
    return False, f"Increment complete ({task_creates} tasks + pentest) but /pm checkpoint not invoked"


def main():
    payload_text = sys.stdin.read()
    if not payload_text:
        return

    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError:
        return

    if payload.get("stop_hook_active"):
        return

    transcript_path = payload.get("transcript_path")
    if not transcript_path or not os.path.exists(transcript_path):
        return

    file_size = os.path.getsize(transcript_path)
    read_bytes = min(READ_BYTES, file_size)

    with open(transcript_path, "r", encoding="utf-8", errors="replace") as f:
        f.seek(max(0, file_size - read_bytes))
        tail = f.read()

    lines = tail.split("\n")

    # Find the last process skill invocation and collect everything after it
    last_process_skill = None
    text_after_skill = []
    agents_after_skill = []
    found_skill = False

    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        # User message = turn boundary. If a process skill was found in a
        # previous turn, a user message means that turn completed — reset.
        if entry.get("type") == "user" and found_skill:
            # The previous turn had a process skill. Check if it already
            # passed (has SCOPE + QA REPORT as needed). If so, clear state
            # so we don't re-check on future turns.
            last_process_skill = None
            text_after_skill = []
            agents_after_skill = []
            found_skill = False

        if entry.get("type") != "assistant":
            continue

        message = entry.get("message", {})
        for block in message.get("content", []):
            # Detect process skill invocation
            if block.get("type") == "tool_use" and block.get("name") == "Skill":
                inp = block.get("input", {})
                if isinstance(inp, str):
                    try:
                        inp = json.loads(inp)
                    except (json.JSONDecodeError, TypeError):
                        inp = {}
                skill = (inp.get("skill") or "").lower()
                if skill.startswith("process-"):
                    last_process_skill = skill
                    text_after_skill = []
                    agents_after_skill = []
                    found_skill = True
                    continue

            # After a process skill, collect text and agent dispatches
            if found_skill:
                if block.get("type") == "text":
                    text = block.get("text", "")
                    clean = strip_fences(text)
                    text_after_skill.append(clean)
                elif block.get("type") == "tool_use" and block.get("name") == "Agent":
                    inp = block.get("input", {})
                    if isinstance(inp, str):
                        try:
                            inp = json.loads(inp)
                        except (json.JSONDecodeError, TypeError):
                            inp = {}
                    agent_type = inp.get("subagent_type") or inp.get("description") or "unknown"
                    agents_after_skill.append(agent_type)

    # --- PM increment check (independent of process skill invocation) ---
    pm_passed, pm_msg = check_pm_after_increment(lines)
    if not pm_passed:
        # Log and block
        try:
            from datetime import datetime
            log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "governance-log.jsonl")
            session_id = os.path.splitext(os.path.basename(transcript_path))[0]  # Full UUID (P1-D fix 2026-04-09)
            log_entry = json.dumps({
                "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "event": "block",
                "hook": "process-step-check",
                "session": session_id,
                "process": "pm-enforcement",
                "hard_failures": [pm_msg],
                "soft_warnings": [],
                "schema": 2,
            })
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(log_entry + "\n")
        except Exception:
            pass
        reason = f"PM ENFORCEMENT: {pm_msg}. Invoke /pm before reporting back."
        print(json.dumps({"decision": "block", "reason": reason}))
        return

    # --- PM checkpoint report check (independent of process skill invocation) ---
    pm_report_passed, pm_report_msg = check_pm_checkpoint_report(lines)
    if not pm_report_passed:
        hard_failures_pm = [pm_report_msg]
        try:
            from datetime import datetime
            log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "governance-log.jsonl")
            session_id = os.path.splitext(os.path.basename(transcript_path))[0]  # Full UUID (P1-D fix 2026-04-09)
            log_entry = json.dumps({
                "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "event": "block",
                "hook": "process-step-check",
                "session": session_id,
                "process": "pm-report-enforcement",
                "hard_failures": hard_failures_pm,
                "soft_warnings": [],
                "schema": 2,
            })
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(log_entry + "\n")
        except Exception:
            pass
        reason = f"PM REPORT: {pm_report_msg}. Add PM CHECKPOINT REPORT block after /pm output."
        print(json.dumps({"decision": "block", "reason": reason}))
        return

    if not last_process_skill or not found_skill:
        return  # No process skill invoked this turn — nothing to check

    # --- HARD checks (block on failure) ---
    hard_failures = []

    passed, msg = check_scope(last_process_skill, text_after_skill)
    if not passed:
        hard_failures.append(msg)

    passed, msg = check_qa_report(last_process_skill, text_after_skill)
    if not passed:
        hard_failures.append(msg)

    passed, msg = check_pentest_report(last_process_skill, text_after_skill)
    if not passed:
        hard_failures.append(msg)

    # --- SOFT checks (log only) ---
    soft_warnings = []

    passed, msg = check_synthesis(last_process_skill, agents_after_skill)
    if not passed:
        soft_warnings.append(msg)

    passed, msg = check_architect_review(last_process_skill, agents_after_skill)
    if not passed:
        soft_warnings.append(msg)

    passed, msg = check_agent_dispatch(last_process_skill, agents_after_skill)
    if not passed:
        soft_warnings.append(msg)

    # Always log when a process skill was detected (pass or fail)
    try:
        from datetime import datetime
        log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "governance-log.jsonl")
        session_id = os.path.splitext(os.path.basename(transcript_path))[0]  # Full UUID (P1-D fix 2026-04-09)
        log_entry = json.dumps({
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "event": "block" if hard_failures else ("warn" if soft_warnings else "pass"),
            "hook": "process-step-check",
            "session": session_id,
            "process": last_process_skill,
            "hard_failures": hard_failures,
            "soft_warnings": soft_warnings,
            "agent_count": len(agents_after_skill),
            "agents": agents_after_skill,
            "schema": 2,
        })
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(log_entry + "\n")
    except Exception:
        pass

    # Only block on hard failures
    if hard_failures:
        reason = (
            f"PROCESS STEP CHECK ({last_process_skill}): "
            f"{' | '.join(hard_failures)}. "
            f"Complete the missing step(s) before proceeding."
        )
        print(json.dumps({"decision": "block", "reason": reason}))


if __name__ == "__main__":
    main()
