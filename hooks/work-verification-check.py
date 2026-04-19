"""
Work Verification Check - Stop Hook
Forces actual execution and autonomous exhaustion before completing.

THREE CHECKS:
1. QA/Pentest Execution (HARD): If QA REPORT or PENTEST REPORT exists but zero
   execution tools (Bash, mcp__*) were used → block. Reading files alone is not testing.
2. Premature Escalation (HARD): If response asks the user for help/decision AND
   fewer than 3 tool_use blocks were used this turn → block with self-interrogation.
3. Zero-Work Non-Quick (SOFT): If non-Quick classification + zero tool_use of any kind
   in this turn → log warning (not block — some analysis is legitimately text-heavy).

The self-interrogation questions (injected on block):
- Did I actually RUN what I built/changed?
- Did I TRY to fix the problem myself before asking?
- Did I use ALL available tools (Bash, MCP, Read, Agent)?
- Am I asking because I'm genuinely stuck or because it's easier?
"""

import sys
import json
import os
import re

READ_BYTES = 204800  # 200KB window


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

    # Find the LAST assistant turn (everything after the last user message)
    last_turn_tools = []  # list of tool names used
    last_turn_text = []   # list of text blocks
    has_qa_report = False
    has_pentest_report = False
    is_non_quick = False
    has_process_qa = False
    has_process_pentest = False

    # Walk backwards to find last user message, then forward for the last assistant turn
    last_user_idx = -1
    for i in range(len(lines) - 1, -1, -1):
        line = lines[i].strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            if entry.get("type") == "user":
                last_user_idx = i
                break
        except json.JSONDecodeError:
            continue

    if last_user_idx < 0:
        return  # No user message found

    # Process everything after the last user message
    for i in range(last_user_idx + 1, len(lines)):
        line = lines[i].strip()
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
                last_turn_text.append(text)

                # Check for QA/pentest reports.
                # Opus-4.7 adversarial-review fix (2026-04-18): tightened from naive
                # substring+word match to structural-block detection. Narrative
                # mentions like "the earlier QA REPORT showed PASS" used to trigger
                # has_qa_report → CHECK 1b then blocked legitimate recaps. New regex
                # requires "QA REPORT" at start-of-line (or after newline), followed
                # by colon or newline (structural marker), with PASS/FAIL verdict
                # within the next 500 chars as a whole word.
                if re.search(r'(?:^|\n)\s*QA REPORT\s*[\n:].{0,500}?\b(?:PASS|FAIL)\b',
                             text, re.DOTALL):
                    has_qa_report = True
                if re.search(r'(?:^|\n)\s*PENTEST REPORT\s*[\n:].{0,500}?\b(?:PASS|FAIL|SHIP|FIX|ESCALATE)\b',
                             text, re.DOTALL):
                    has_pentest_report = True

                # Check for non-Quick classification
                if re.search(r'TASK TYPE:\s*(?:Research|Analysis|Build|Planning|Content|Compound)', text, re.IGNORECASE):
                    is_non_quick = True

            elif block.get("type") == "tool_use":
                name = block.get("name", "")
                last_turn_tools.append(name)

                # Track QA/pentest skill invocation
                if name == "Skill":
                    inp = block.get("input", {})
                    if isinstance(inp, str):
                        try:
                            inp = json.loads(inp)
                        except (json.JSONDecodeError, TypeError):
                            inp = {}
                    skill = (inp.get("skill") or "").lower()
                    if skill == "process-qa":
                        has_process_qa = True
                    elif skill == "process-pentest":
                        has_process_pentest = True

    # Categorize tools
    execution_tools = [t for t in last_turn_tools if t == "Bash" or t.startswith("mcp__")]
    any_tools = [t for t in last_turn_tools if t not in ("Skill",)]  # Skill alone doesn't count as "work"
    tool_count = len(any_tools)

    # Combine all text for pattern matching
    full_text = "\n".join(last_turn_text)

    # --- CHECK 1: QA/Pentest Execution (HARD) ---
    # Catches lazy execution WITHIN an invoked process-qa/process-pentest skill.
    if (has_qa_report or has_pentest_report) and (has_process_qa or has_process_pentest):
        if len(execution_tools) == 0:
            # Check if Read/Grep were used (acceptable for some claim types)
            read_tools = [t for t in last_turn_tools if t in ("Read", "Grep", "Glob")]
            if len(read_tools) == 0:
                reason = (
                    "WORK VERIFICATION: QA/Pentest report filed with ZERO tool usage. "
                    "You did not execute any tests — no Bash, no MCP, not even Read. "
                    "Before reporting results, ask yourself:\n"
                    "- Did I actually RUN what I built/changed?\n"
                    "- Did I pipe test inputs through the hook/script?\n"
                    "- Did I fetch the live system state via MCP?\n"
                    "- Did I verify with Read/Grep at minimum?\n"
                    "Go back and ACTUALLY TEST before filing the report."
                )
                print(json.dumps({"decision": "block", "reason": reason}))
                return
            # Read/Grep used but no Bash/MCP — softer warning for non-execution QA
            # This is acceptable for claims like "file exists" or "config is registered"
            # but not for "hook blocks correctly" or "workflow runs"
            # Log it but don't block
            pass

    # --- CHECK 1b: QA/Pentest Report Inline Without Skill Invocation (HARD) ---
    # H5 fix (2026-04-18): The original CHECK 1 above only fires when the process
    # skill was invoked. An agent that writes `QA REPORT: PASS` inline WITHOUT
    # calling /process-qa (or /process-pentest) bypassed the gate entirely.
    # This check closes that hole: producing a QA/Pentest verdict on a non-Quick
    # task requires actually invoking the corresponding process skill.
    if is_non_quick:
        if has_qa_report and not (has_process_qa or has_process_pentest):
            reason = (
                "WORK VERIFICATION: QA REPORT block produced on a non-Quick task "
                "without invoking /process-qa (or /process-pentest). Writing a "
                "QA verdict inline bypasses the QA process. Invoke the /process-qa "
                "skill properly — it structures scope, execution, and reporting. "
                "Inline QA reports are not valid evidence of verification."
            )
            print(json.dumps({"decision": "block", "reason": reason}))
            try:
                from datetime import datetime
                log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "governance-log.jsonl")
                session_id = os.path.splitext(os.path.basename(transcript_path))[0] if transcript_path else "unknown"
                entry = json.dumps({
                    "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "event": "block",
                    "hook": "work-verification-check",
                    "session": session_id,
                    "check": "inline-qa-without-skill",
                    "schema": 2,
                })
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(entry + "\n")
            except Exception:
                pass
            return
        if has_pentest_report and not has_process_pentest:
            reason = (
                "WORK VERIFICATION: PENTEST REPORT block produced on a non-Quick "
                "task without invoking /process-pentest. Inline pentest verdicts "
                "bypass the pentest process. Invoke /process-pentest properly."
            )
            print(json.dumps({"decision": "block", "reason": reason}))
            try:
                from datetime import datetime
                log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "governance-log.jsonl")
                session_id = os.path.splitext(os.path.basename(transcript_path))[0] if transcript_path else "unknown"
                entry = json.dumps({
                    "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "event": "block",
                    "hook": "work-verification-check",
                    "session": session_id,
                    "check": "inline-pentest-without-skill",
                    "schema": 2,
                })
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(entry + "\n")
            except Exception:
                pass
            return

    # --- CHECK 2: Premature Escalation (HARD) ---
    # Detect: response asks user for help/decision with minimal tool usage
    escalation_patterns = [
        r'(?:want|should|shall|would you like)\s+(?:me|I)\s+(?:to\s+)?',
        r'(?:do you|would you)\s+(?:want|prefer|like)',
        r"(?:what do you think|your (?:call|decision|take))\s*\??",
        r"(?:I'm stuck|I cannot|I can't figure)",
        r'(?:any (?:ideas|suggestions|thoughts))\s*\??',
    ]

    response_asks_user = False
    for pattern in escalation_patterns:
        if re.search(pattern, full_text, re.IGNORECASE):
            response_asks_user = True
            break

    if response_asks_user and is_non_quick and tool_count < 3:
        reason = (
            f"WORK VERIFICATION: You are asking the user for help after using only "
            f"{tool_count} tool(s) this turn. Before escalating, ask yourself:\n"
            "- Did I try to SOLVE this myself with Bash/MCP?\n"
            "- Did I search for similar patterns in the codebase (Grep)?\n"
            "- Did I read error messages and try a fix?\n"
            "- Did I try an alternative approach or a different tool?\n"
            "- Am I asking because I'm genuinely stuck or because it's easier?\n"
            "Exhaust your tools before asking the user. Try at least 3 different approaches."
        )
        print(json.dumps({"decision": "block", "reason": reason}))
        return

    # --- CHECK 3: Zero-Work Non-Quick (SOFT — log only) ---
    # INFO-4 fix (2026-04-09): Track whether warn was emitted to prevent
    # double-logging (warn + pass on same turn would corrupt analytics).
    warn_emitted = False
    if is_non_quick and tool_count == 0:
        try:
            from datetime import datetime
            log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "governance-log.jsonl")
            session_id = os.path.splitext(os.path.basename(transcript_path))[0]  # Full UUID (P1-D fix 2026-04-09)
            log_entry = json.dumps({
                "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "event": "warn",
                "hook": "work-verification-check",
                "session": session_id,
                "check": "zero-work-non-quick",
                "tool_count": 0,
                "has_qa_report": has_qa_report,
                "is_non_quick": is_non_quick,
                "schema": 2,
            })
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(log_entry + "\n")
            warn_emitted = True
        except Exception:
            pass

    # --- Log pass for monitoring ---
    # Skip if warn was already emitted this turn (prevents double-counting)
    if (is_non_quick or has_qa_report or has_pentest_report) and not warn_emitted:
        try:
            from datetime import datetime
            log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "governance-log.jsonl")
            session_id = os.path.splitext(os.path.basename(transcript_path))[0]  # Full UUID (P1-D fix 2026-04-09)
            log_entry = json.dumps({
                "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "event": "pass",
                "hook": "work-verification-check",
                "session": session_id,
                "tool_count": tool_count,
                "execution_tools": len(execution_tools),
                "has_qa_report": has_qa_report,
                "has_pentest_report": has_pentest_report,
                "response_asks_user": response_asks_user,
                "schema": 2,
            })
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(log_entry + "\n")
        except Exception:
            pass


if __name__ == "__main__":
    main()
