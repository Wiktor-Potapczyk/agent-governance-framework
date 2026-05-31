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

# Keywords that indicate a behavioral claim — i.e. "the artifact DOES something"
# rather than "the file EXISTS" or "the config IS present". When a QA/pentest report
# is filed with only Read/Grep tool usage and the work-item text contains one of
# these verbs, a WARN is emitted to stderr (non-blocking).
BEHAVIORAL_CLAIM_KEYWORDS = {
    "fires", "triggers", "sends", "executes", "runs",
}

# --- CHECK 4 (SA-4 file-existence): Write-claim language patterns ---
# Sprint A Item 1 (PRD AC1.1-1.4): detect fabrications where an agent claims to
# have Written a file but neither (a) actually used Write/Edit/MultiEdit on that
# path in this turn, NOR (b) the file pre-exists on disk. Q9 (PRD §9) resolved
# the detection mechanism: Write-tool-trace absence + path-existence check +
# tool_result-block parsing (to catch sub-agent claims, not just main session).
# Q8 (PRD §9) resolved the framing: "ergonomic automation" of ls -la, not a
# safety-critical gap closure — so prefer false-negative (miss some) over
# false-positive (block legitimate work).
WRITE_CLAIM_PATTERNS = [
    # Past-tense Write claims with explicit path-shape token (./path, /path, path/file, file.ext)
    # Path token: \S+/\S+ OR \S+\.[a-zA-Z]+ (extension)
    r'\b(?:wrote(?:\s+the\s+\w+)?|saved(?:\s+the\s+\w+)?|created(?:\s+the\s+\w+)?|written|stored)\s+(?:it\s+)?(?:to|at|in)\s+[`"\']?(\S+\.\w+|\S+/\S+)',
    # "File saved at /path", "file created at path/file.ext"
    r'\b(?:file|report|note|spec|document)\s+(?:saved|written|created|stored)\s+(?:to|at|in)\s+[`"\']?(\S+\.\w+|\S+/\S+)',
    # "I have written ... to /path"
    r'\b(?:I\s+(?:have\s+)?(?:wrote|saved|created|written|stored)|now\s+(?:wrote|saved|created|written))\s+(?:.{0,80}?)\s+(?:to|at|in)\s+[`"\']?(\S+\.\w+|\S+/\S+)',
]
# Failure-language guard (adversarial CR #1) — if Write-claim is within this many
# chars of failure language, treat as legitimate failure report, not a fabrication.
FAILURE_LANGUAGE_WINDOW_CHARS = 100
FAILURE_LANGUAGE_PATTERNS = [
    r'\b(?:failed|error|could\s+not|couldn\'t|tried\s+to|attempted\s+to|blocked|denied|refused)\b',
]
# Vault-root for path-existence resolution. Hook fires from .claude/hooks/, so
# vault root is two levels up.
VAULT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Note: broader verbs (creates, returns, works, updates) deliberately excluded —
# they appear in legitimate static-analysis QA claims that Read can verify
# (e.g., "verified the function returns a string"). Architect-reviewer
# 2026-05-25 flagged false-positive risk; tightened to strong-behavioral verbs only.

# Observability v2: shared event-emit helper (silent on import failure)
try:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _event_emit import emit_event  # type: ignore
except Exception:  # pragma: no cover
    emit_event = None  # type: ignore


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

    try:
        import os as _gho, sys as _ghs
        _ghs.path.insert(0, _gho.path.dirname(_gho.path.abspath(__file__)))
        from _governance_logger import log_fire
        log_fire("work-verification-check")
    except Exception:
        pass

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
            # Read/Grep used but no Bash/MCP — softer warning for non-execution QA.
            # Detects behavioral-claim QA filed with Read-only tool use:
            # if the work-item text contains a verb from BEHAVIORAL_CLAIM_KEYWORDS
            # (e.g. "fires", "runs", "triggers"), the claim asserts runtime behavior
            # that Read/Grep cannot verify — emit WARN to stderr (non-blocking).
            # Non-behavioral items (existence checks, config presence) pass silently.
            work_text_lower = full_text.lower()
            matched_keyword = next(
                (kw for kw in BEHAVIORAL_CLAIM_KEYWORDS if kw in work_text_lower),
                None,
            )
            if matched_keyword is not None:
                print(
                    f"WARN: behavioral claim without execution tool — found keyword "
                    f"'{matched_keyword}' in work item; consider running Bash/MCP to "
                    f"actually exercise the artifact, not just read it.",
                    file=sys.stderr,
                )

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

    # --- CHECK 4 (SA-4 file-existence / fabrication detection): ---
    # PRD Item 1 (Sprint A) — detect agent claims of "I wrote/saved/created X"
    # where path X was NOT actually written via Write/Edit/MultiEdit tool_use in
    # this turn AND does NOT exist on disk. Per Q9 (PRD §9): combine Write-trace
    # absence + path-existence + tool_result block parsing (catches sub-agent
    # fabrications, not just main-session). Per Q8: ergonomic automation framing —
    # prefer false-negative (miss some) over false-positive (block legitimate).
    #
    # Walks the same last-turn window already collected above. Also rescans for
    # tool_result blocks (sub-agent output) because the existing loop only
    # processes entry.type == "assistant" blocks.
    actually_written = set()
    # First pass: gather Write/Edit/MultiEdit file_paths from main-session tool_use
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
        for block in entry.get("message", {}).get("content", []):
            if block.get("type") != "tool_use":
                continue
            name = block.get("name", "")
            if name in ("Write", "Edit", "MultiEdit"):
                inp = block.get("input", {})
                if isinstance(inp, str):
                    try:
                        inp = json.loads(inp)
                    except (json.JSONDecodeError, TypeError):
                        inp = {}
                p = inp.get("file_path")
                if p:
                    actually_written.add(p)
                    # also normalize trailing path component for fuzzy match
                    actually_written.add(os.path.basename(p))

    # Second pass: collect text from both assistant blocks AND tool_result blocks
    # (sub-agent output appears as tool_result in main-session transcript).
    # IMPORTANT: tool_result blocks are wrapped in user-type entries — the
    # last_user_idx logic above stops walking at the LAST user-type entry, which
    # in transcripts with sub-agent dispatches IS the tool_result wrapper itself.
    # So we re-find the "last real user message" by looking for user entries
    # whose content is a STRING (not a list of tool_result blocks).
    real_last_user_idx = -1
    for i in range(len(lines) - 1, -1, -1):
        line = lines[i].strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            if entry.get("type") == "user":
                content = entry.get("message", {}).get("content")
                # Real user message: content is a plain string OR a list with a
                # "text" block (not "tool_result"). tool_result wrappers have
                # content = [{"type": "tool_result", ...}].
                if isinstance(content, str):
                    real_last_user_idx = i
                    break
                if isinstance(content, list):
                    has_text = any(
                        isinstance(b, dict) and b.get("type") == "text"
                        for b in content
                    )
                    has_only_tool_result = all(
                        isinstance(b, dict) and b.get("type") == "tool_result"
                        for b in content
                    ) if content else False
                    if has_text and not has_only_tool_result:
                        real_last_user_idx = i
                        break
        except json.JSONDecodeError:
            continue
    if real_last_user_idx < 0:
        real_last_user_idx = last_user_idx  # fallback to original

    candidate_texts = []
    candidate_texts.append(full_text)  # already-collected assistant text
    for i in range(real_last_user_idx + 1, len(lines)):
        line = lines[i].strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        # tool_result blocks are wrapped in user-type entries
        if entry.get("type") not in ("user", "assistant"):
            continue
        for block in entry.get("message", {}).get("content", []):
            if block.get("type") == "tool_result":
                content = block.get("content")
                if isinstance(content, str):
                    candidate_texts.append(content)
                elif isinstance(content, list):
                    for sub in content:
                        if isinstance(sub, dict) and sub.get("type") == "text":
                            candidate_texts.append(sub.get("text", ""))

    # Scan candidate texts for Write-claim patterns; check each claimed path.
    fabrications = []  # list of (claimed_path, source_snippet)
    for text in candidate_texts:
        if not text:
            continue
        for pattern in WRITE_CLAIM_PATTERNS:
            for m in re.finditer(pattern, text, re.IGNORECASE):
                claimed = m.group(1).strip("`\"'.,;:)]}")
                # Failure-language guard — skip if claim is near "failed/error/tried/etc"
                start = max(0, m.start() - FAILURE_LANGUAGE_WINDOW_CHARS)
                end = min(len(text), m.end() + FAILURE_LANGUAGE_WINDOW_CHARS)
                window = text[start:end]
                is_failure = any(
                    re.search(fp, window, re.IGNORECASE)
                    for fp in FAILURE_LANGUAGE_PATTERNS
                )
                if is_failure:
                    continue
                # Skip if path was actually written this turn (by basename OR full)
                if claimed in actually_written or os.path.basename(claimed) in actually_written:
                    continue
                # Resolve relative paths against vault root
                if not os.path.isabs(claimed):
                    abs_path = os.path.join(VAULT_ROOT, claimed)
                else:
                    abs_path = claimed
                # Path-existence check
                if os.path.exists(abs_path):
                    continue
                # Fabrication detected
                snippet = text[max(0, m.start() - 60):min(len(text), m.end() + 60)]
                fabrications.append((claimed, snippet.strip()))

    if fabrications:
        # Deduplicate by claimed path
        seen = set()
        unique_fabrications = []
        for claim, snip in fabrications:
            if claim in seen:
                continue
            seen.add(claim)
            unique_fabrications.append((claim, snip))
            if len(unique_fabrications) >= 5:
                break
        # Log to governance + warn (non-blocking per Q8 ergonomic framing).
        # If user wants block, this is the swap point: replace WARN block with the
        # `print(json.dumps({"decision": "block", "reason": ...})); return` pattern.
        try:
            from datetime import datetime
            log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "governance-log.jsonl")
            session_id_f = os.path.splitext(os.path.basename(transcript_path))[0] if transcript_path else "unknown"
            for claim, snip in unique_fabrications:
                entry = json.dumps({
                    "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "event": "fabrication_detected",
                    "hook": "work-verification-check",
                    "session": session_id_f,
                    "check": "file-existence-check",
                    "claimed_path": claim,
                    "actual_exists": False,
                    "snippet": snip[:200],
                    "schema": 2,
                })
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(entry + "\n")
        except Exception:
            pass
        warn_msg = (
            f"FABRICATION_DETECTED: {len(unique_fabrications)} Write-claim(s) found "
            f"without matching Write trace OR path on disk:\n"
            + "\n".join(f"  - {c}" for c, _ in unique_fabrications)
            + "\n(Logged to governance-log.jsonl. Non-blocking per ergonomic framing.)"
        )
        print(warn_msg, file=sys.stderr)

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

    # --- Observability v2: event 19 session_end (heartbeat) ---
    # Emitted on every Stop. Aggregators should take the MAX(ts) row per session
    # as the effective session end. Fields: turn_count (assistant messages in
    # transcript tail), approx_tokens (file_size / 4), duration_sec (from earliest
    # session_start entry in governance-log for this session, if findable).
    if emit_event is not None:
        try:
            session_id_h = os.path.splitext(os.path.basename(transcript_path))[0] if transcript_path else "unknown"
            turn_count = 0
            for _line in lines:
                _line = _line.strip()
                if not _line:
                    continue
                try:
                    _e = json.loads(_line)
                    if _e.get("type") == "assistant":
                        turn_count += 1
                except json.JSONDecodeError:
                    continue
            approx_tokens = int(file_size / 4) if file_size else 0

            # Duration estimate: look up session_start for this session in governance-log
            duration_sec = None
            try:
                log_path_d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "governance-log.jsonl")
                start_ts = None
                with open(log_path_d, "r", encoding="utf-8", errors="replace") as _lf:
                    for _row in _lf:
                        _row = _row.strip()
                        if not _row:
                            continue
                        try:
                            _re = json.loads(_row)
                        except json.JSONDecodeError:
                            continue
                        if _re.get("event") == "session_start" and _re.get("session") == session_id_h:
                            start_ts = _re.get("ts")
                            break
                if start_ts:
                    from datetime import datetime as _dt
                    try:
                        sdt = _dt.strptime(start_ts, "%Y-%m-%d %H:%M:%S")
                        duration_sec = int((_dt.now() - sdt).total_seconds())
                    except Exception:
                        duration_sec = None
            except Exception:
                duration_sec = None

            emit_event(
                event="session_end",
                hook="work-verification-check",
                session=session_id_h,
                extra={
                    "turn_count": turn_count,
                    "approx_tokens": approx_tokens,
                    "duration_sec": duration_sec,
                    "heartbeat": True,
                },
            )
        except Exception:
            pass

    # --- Observability v2: event 26 qa_fail_reported ---
    # Fires when a QA REPORT block contains at least one FAIL: line with a non-empty
    # (non-"none") claim. Independent of block/pass decision — pure telemetry.
    if has_qa_report and emit_event is not None:
        fail_lines = []
        for m in re.finditer(r'(?:^|\n)\s*FAIL:\s*([^\n]+)', full_text, re.IGNORECASE):
            claim = m.group(1).strip()
            low = claim.lower().rstrip(".,;:")
            if low and low not in {"none", "n/a", "na", "-"}:
                fail_lines.append(claim[:200])
        if fail_lines:
            try:
                session_id_e = os.path.splitext(os.path.basename(transcript_path))[0] if transcript_path else "unknown"
                emit_event(
                    event="qa_fail_reported",
                    hook="work-verification-check",
                    session=session_id_e,
                    extra={
                        "fail_count": len(fail_lines),
                        "fails": fail_lines[:5],  # cap to 5 to avoid bloat
                        "via_process_qa": has_process_qa,
                        "via_process_pentest": has_process_pentest,
                    },
                )
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
