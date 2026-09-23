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

# Harness audit 1 (2026-09-21, [[2026-09-21-dispatch-and-work-verification-fix-plan]]).
# The report headers may carry markdown decoration (review A3: "**QA REPORT**"
# and "## QA REPORT" were invisible, which silently disabled CHECK 1). The
# TASK TYPE token is captured whatever it says (review A6: a misspelt value read
# as "no classification"); anything but Quick is non-Quick.
QA_REPORT_RE = re.compile(r'(?:^|\n)[ \t*_#>]*QA REPORT[ \t*_]*[\n:].{0,500}?\b(?:PASS|FAIL)\b', re.DOTALL)
PENTEST_REPORT_RE = re.compile(r'(?:^|\n)[ \t*_#>]*PENTEST REPORT[ \t*_]*[\n:].{0,500}?\b(?:PASS|FAIL|SHIP|FIX|ESCALATE)\b', re.DOTALL)
TASK_TYPE_RE = re.compile(r'TASK TYPE:\s*\**\s*([A-Za-z][A-Za-z-]*)', re.IGNORECASE)
VALID_TASK_TYPES = frozenset({"quick", "research", "analysis", "content", "build", "planning", "compound"})
NO_CLAIMS_RE = re.compile(r'^\s*no verifiable claims\s*\.?\s*$', re.IGNORECASE | re.MULTILINE)


_FENCE_RE = re.compile(r'```[\s\S]*?```')


def _strip_fences(text):
    """Fenced code is quoted, not said (architect review of the build, finding 2:
    a documentation turn quoting the templates was a hard false block here while
    the sibling hook already stripped fences)."""
    return _FENCE_RE.sub('', text)


def _safe_entry(line):
    """The JSON object on a transcript line, or None (blank, malformed, not a dict)."""
    line = line.strip()
    if not line:
        return None
    try:
        e = json.loads(line)
    except (json.JSONDecodeError, TypeError):
        return None
    return e if isinstance(e, dict) else None


def main():
    payload_text = sys.stdin.read()
    if not payload_text:
        return

    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError:
        return

    # Valid JSON of the wrong shape is still unusable input. Without this,
    # a bare array or scalar reached .get and printed an AttributeError
    # traceback. See test_hooks_survive_malformed_payload.py.
    if not isinstance(payload, dict):
        return
    if payload.get("stop_hook_active"):
        return

    try:
        import os as _gho, sys as _ghs
        _ghs.path.insert(0, _gho.path.dirname(_gho.path.abspath(__file__)))
        from _governance_logger import log_fire, session_from
        log_fire("work-verification-check", session=session_from(payload))
    except Exception:
        pass

    transcript_path = payload.get("transcript_path")
    if not transcript_path or not os.path.exists(transcript_path):
        return

    # Read the tail up to the start of the turn (silent-failure review item 1,
    # 2026-09-21: the fixed 200 KB tail could not see a turn behind one large
    # tool result). The old fixed read is the fallback if the helper is missing.
    window_info = {"window_bytes": 0, "capped": False, "turn_start": -1, "turn_boundary": "unavailable"}
    try:
        from _turn_boundary import tail_to_turn_start, boundary_kind
        lines, window_info = tail_to_turn_start(transcript_path, start_bytes=READ_BYTES)
        window_info["turn_boundary"] = boundary_kind(lines)
        file_size = window_info["file_size"]
    except Exception as exc:
        print(f"WARN: work-verification could not use _turn_boundary ({type(exc).__name__}: {exc}); "
              f"reading the fixed {READ_BYTES} byte tail with the old last-user rule instead.", file=sys.stderr)
        file_size = os.path.getsize(transcript_path)
        read_bytes = min(READ_BYTES, file_size)
        with open(transcript_path, "r", encoding="utf-8", errors="replace") as f:
            f.seek(max(0, file_size - read_bytes))
            tail = f.read()
        lines = tail.split("\n")
        window_info["window_bytes"] = read_bytes

    def _emit(event, extra):
        """One governance event, never raising (review A7 and A10: two hard blocks
        and three warnings used to leave no trace)."""
        if emit_event is None:
            return
        try:
            from _governance_logger import session_from
            emit_event(event=event, hook="work-verification-check", session=session_from(payload), extra=extra)
        except Exception:
            pass

    # Find the LAST assistant turn (everything after the last user message)
    last_turn_tools = []  # list of tool names used
    last_turn_text = []   # list of text blocks
    has_qa_report = False
    has_pentest_report = False
    is_non_quick = False
    bash_commands = []  # the literal command of every Bash tool_use this turn
    has_process_qa = False
    has_process_pentest = False
    # B-2/B-3 flags (2026-06-11): set when QA/pentest ran inside a Workflow invocation.
    # The workflow's Bash/MCP calls run inside the subagent and never appear in the
    # main transcript's tool list, so the execution_tools list is empty on the relay
    # turn. B-3 suppresses CHECK 1's zero-execution-tools block when the flag is set —
    # the execution-evidence obligation moves into the workflow script's typed per-claim
    # fields (Part C process-qa note). The suppression is keyed on the workflow-invocation
    # flag specifically, never on mere presence of any Workflow tool_use.
    qa_via_workflow = False
    pentest_via_workflow = False

    # --- the turn (harness audit 1, 2026-09-21) --------------------------------
    # `lines` ends at the current turn and `turn_start` is the last entry that IS
    # the user (see _turn_boundary). Skill bodies, tool_result wrappers and Stop
    # hook feedback are user entries that are not the user; each of them used to
    # start the turn here, which hid the classification, the Skill call and every
    # earlier tool: 44 QA reports with zero tools logged as passes in 30 days,
    # three of them retries in the owner's own session after a block.
    turn_start = window_info.get("turn_start", -1)
    turn_boundary = window_info.get("turn_boundary", "unavailable")
    if turn_start < 0:
        for i in range(len(lines) - 1, -1, -1):
            e = _safe_entry(lines[i])
            if e is not None and e.get("type") == "user":
                turn_start = i
                break
    if turn_start < 0:
        return  # No user message found
    last_user_idx = turn_start
    tool_calls = []  # (name, input) pairs: the escalation gate counts approaches, not calls (review A8)
    task_type_token = ""
    unrecognised_task_type = ""
    for i in range(turn_start + 1, len(lines)):
        entry = _safe_entry(lines[i])
        if entry is None or entry.get("type") != "assistant":
            continue
        message = entry.get("message") or {}
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                text = str(block.get("text", ""))
                last_turn_text.append(text)
                said = _strip_fences(text)
                if QA_REPORT_RE.search(said):
                    has_qa_report = True
                if PENTEST_REPORT_RE.search(said):
                    has_pentest_report = True
                m = TASK_TYPE_RE.search(said)
                if m:
                    task_type_token = m.group(1).lower()
                    if task_type_token != "quick":
                        is_non_quick = True
                        if task_type_token not in VALID_TASK_TYPES:
                            unrecognised_task_type = task_type_token
            elif block.get("type") == "tool_use":
                name = str(block.get("name", ""))
                inp = block.get("input", {})
                if isinstance(inp, str):
                    try:
                        inp = json.loads(inp)
                    except (json.JSONDecodeError, TypeError):
                        inp = {}
                if not isinstance(inp, dict):
                    inp = {}
                last_turn_tools.append(name)
                try:
                    tool_calls.append((name, json.dumps(inp, sort_keys=True)[:2000]))
                except Exception:
                    tool_calls.append((name, str(i)))
                if name == "Bash" and isinstance(inp.get("command"), str):
                    bash_commands.append(inp["command"])
                elif name == "Skill":
                    skill_name = str(inp.get("skill") or "").strip().lower()
                    if skill_name == "process-qa":
                        has_process_qa = True
                    elif skill_name == "process-pentest":
                        has_process_pentest = True
                elif name == "Workflow":
                    # A workflow-path QA runs its tools inside the subagents; the
                    # relay turn shows none. CHECK 1 keys its suppression on this flag.
                    wf_name = str(inp.get("name") or inp.get("workflow_name") or "").strip().lower()
                    if not wf_name:
                        sp = str(inp.get("scriptPath") or "")
                        base = os.path.basename(sp)
                        wf_name = base[:-3].lower() if base.endswith(".js") else base.lower()
                    if wf_name == "process-qa":
                        has_process_qa = True
                        qa_via_workflow = True
                    elif wf_name == "process-pentest":
                        has_process_pentest = True
                        pentest_via_workflow = True
    if unrecognised_task_type:
        print(f"WARN: TASK TYPE '{unrecognised_task_type}' is not a recognised type; treated as non-Quick.", file=sys.stderr)

    # Categorize tools
    execution_tools = [t for t in last_turn_tools if t == "Bash" or t.startswith("mcp__")]
    any_tools = [t for t in last_turn_tools if t not in ("Skill",)]  # Skill alone doesn't count as "work"
    tool_count = len(any_tools)
    distinct_tool_calls = len({tc for tc in tool_calls if tc[0] != "Skill"})

    # Combine all text for pattern matching
    full_text = "\n".join(last_turn_text)

    # --- CHECK 1: QA/Pentest Execution (HARD) ---
    # Catches lazy execution WITHIN an invoked process-qa/process-pentest skill.
    # B-3 suppression (2026-06-11): when QA/pentest ran inside a Workflow invocation,
    # the workflow's Bash/MCP calls run in the subagent and are invisible to the main
    # transcript's execution_tools list (built from main-transcript tool_use only).
    # The zero-execution-tools block is suppressed when qa_via_workflow or
    # pentest_via_workflow is True — the execution-evidence obligation has moved into
    # the workflow script's typed per-claim fields. The suppression is keyed on the
    # workflow-invocation flag specifically, not on mere Workflow presence in the turn,
    # so Skill-path process-qa with zero execution tools is still blocked normally.
    if (has_qa_report or has_pentest_report) and (has_process_qa or has_process_pentest):
        _via_workflow = (has_qa_report and qa_via_workflow) or (has_pentest_report and pentest_via_workflow)
        if len(execution_tools) == 0 and not _via_workflow:
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
                _emit("block", {"check": "zero-tool-qa", "tool_count": tool_count, "turn_boundary": turn_boundary})
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
                _emit("warn", {"check": "behavioral-claim", "keyword": matched_keyword})

    # --- CHECK 1d: invoked without a verdict (HARD, 2026-09-21, review A9) ---
    # Skill(process-qa) satisfied dispatch-compliance, and with no report written
    # this hook had nothing to check: invocation without a verdict passed both.
    _qa_no_verdict = has_process_qa and not qa_via_workflow and not has_qa_report and not NO_CLAIMS_RE.search(full_text)
    _pt_no_verdict = has_process_pentest and not pentest_via_workflow and not has_pentest_report
    if _qa_no_verdict or _pt_no_verdict:
        reason = (
            "WORK VERIFICATION: process-qa (or process-pentest) was invoked this turn "
            "but no QA REPORT (or the line 'no verifiable claims') was filed. Invocation "
            "without a verdict is not verification: run the claims and file the report, "
            "or state on its own line that there are no verifiable claims."
        )
        print(json.dumps({"decision": "block", "reason": reason}))
        _emit("block", {"check": "qa-invoked-without-verdict", "tool_count": tool_count, "turn_boundary": turn_boundary})
        return

    # --- CHECK 1c: self-QA on a Build turn (WARN, 2026-09-21) ---
    # The verifier and the builder are the same session when a Build turn files
    # its QA through the Skill path. The record's one controlled comparison
    # (Module-8B 2026-09-18: self-check 6/6, independent rerun 5/6) is why this
    # is named. Never a block: the fallback path is legitimate; it must say what
    # it is. The qa-log entry carries `Verifier: main-session`.
    if is_non_quick and has_qa_report and has_process_qa and not qa_via_workflow:
        print(
            "WARN: SELF-QA: this turn verified its own claims in the main "
            "session (Skill path). The verifier is the builder. Record "
            "'Verifier: main-session' in the qa-log entry, or run the workflow path "
            "so a separate agent tests each claim.",
            file=sys.stderr,
        )
        _emit("warn", {"check": "self-qa", "tool_count": tool_count, "execution_tools": len(execution_tools)})
        # The tool name says nothing about what ran (QA contract review, 2026-09-21):
        # when every Bash call of the turn only read files, say so.
        try:
            from _command_class import is_read_only_command
            if bash_commands and all(is_read_only_command(c) for c in bash_commands):
                print(
                    f"WARN: READ-ONLY-QA: all {len(bash_commands)} Bash call(s) this turn only read files "
                    "(cat, sed, grep, git show...). Nothing was run. A PASS on a run or execute claim "
                    "needs the artifact invoked.",
                    file=sys.stderr,
                )
                _emit("warn", {"check": "read-only-qa", "bash_calls": len(bash_commands)})
        except Exception:
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
                # Module-level import at line 70. A local re-import here would
                # rebind emit_event as a function-local and break every earlier
                # reference to it in this same function.
                from _governance_logger import session_from
                session_id = session_from(payload)
                emit_event(
                    event="block",
                    hook="work-verification-check",
                    session=session_id,
                    extra={"check": "inline-qa-without-skill", "turn_boundary": turn_boundary, "tool_count": tool_count},
                )
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
                from _governance_logger import session_from
                session_id = session_from(payload)
                emit_event(
                    event="block",
                    hook="work-verification-check",
                    session=session_id,
                    extra={"check": "inline-pentest-without-skill", "turn_boundary": turn_boundary, "tool_count": tool_count},
                )
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
        entry = _safe_entry(lines[i])
        if entry is None or entry.get("type") != "assistant":
            continue
        _c4 = (entry.get("message") or {}).get("content")
        for block in (_c4 if isinstance(_c4, list) else []):
            if not isinstance(block, dict) or block.get("type") != "tool_use":
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
    # The shared boundary (2026-09-21, architect finding 4): CHECK 4 kept its own
    # last-user scan, which crashed on a non-dict line and failed the hook open.
    real_last_user_idx = last_user_idx

    candidate_texts = []
    candidate_texts.append(full_text)  # already-collected assistant text
    for i in range(real_last_user_idx + 1, len(lines)):
        entry = _safe_entry(lines[i])
        if entry is None:
            continue
        # tool_result blocks are wrapped in user-type entries
        if entry.get("type") not in ("user", "assistant"):
            continue
        _c4b = (entry.get("message") or {}).get("content")
        for block in (_c4b if isinstance(_c4b, list) else []):
            if not isinstance(block, dict):
                continue
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
                # R18 tune (owner 'ok go' 2026-09-06): a markdown self-link
                # swallows "[label](path" into the capture; keep the path part.
                if "](" in claimed:
                    claimed = claimed.split("](")[-1]
                    claimed = claimed.strip("`\"'.,;:)]}([")
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
                # Resolve relative paths against vault root.
                # R18 tune: expand ~ first; a home-relative claim resolved
                # against VAULT_ROOT was a guaranteed false miss.
                claimed_fs = os.path.expanduser(claimed)
                if not os.path.isabs(claimed_fs):
                    abs_path = os.path.join(VAULT_ROOT, claimed_fs)
                else:
                    abs_path = claimed_fs
                # Path-existence check
                if os.path.exists(abs_path):
                    continue
                # R18 tune: real vault artifacts nest under Projects/<name>/
                # (one or two levels); a bare project-relative claim is not a
                # false claim just because it omits the project prefix.
                # Sampling 2026-09-06: 15 of 17 fired events were this shape.
                if not os.path.isabs(claimed_fs):
                    import glob as _glob
                    if (_glob.glob(os.path.join(VAULT_ROOT, "Projects", "*", claimed_fs))
                            or _glob.glob(os.path.join(VAULT_ROOT, "Projects", "*", "*", claimed_fs))):
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
            from _governance_logger import session_from
            session_id_f = session_from(payload)
            for claim, snip in unique_fabrications:
                emit_event(
                    event="fabrication_detected",
                    hook="work-verification-check",
                    session=session_id_f,
                    extra={
                        "check": "file-existence-check",
                        "claimed_path": claim,
                        "actual_exists": False,
                        "snippet": snip[:200],
                    },
                )
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

    # Distinct (tool, input) pairs, not raw calls (review A8, 2026-09-21: three
    # identical reads satisfied "three approaches").
    if response_asks_user and is_non_quick and distinct_tool_calls < 3:
        reason = (
            f"WORK VERIFICATION: You are asking the user for help after only "
            f"{distinct_tool_calls} distinct tool call(s) this turn ({tool_count} in all). Before escalating, ask yourself:\n"
            "- Did I try to SOLVE this myself with Bash/MCP?\n"
            "- Did I search for similar patterns in the codebase (Grep)?\n"
            "- Did I read error messages and try a fix?\n"
            "- Did I try an alternative approach or a different tool?\n"
            "- Am I asking because I'm genuinely stuck or because it's easier?\n"
            "Exhaust your tools before asking the user. Try at least 3 different approaches."
        )
        print(json.dumps({"decision": "block", "reason": reason}))
        _emit("block", {"check": "premature-escalation", "tool_count": tool_count, "distinct_tool_calls": distinct_tool_calls})
        return

    # --- CHECK 3: Zero-Work Non-Quick (SOFT — log only) ---
    # INFO-4 fix (2026-04-09): Track whether warn was emitted to prevent
    # double-logging (warn + pass on same turn would corrupt analytics).
    warn_emitted = False
    if is_non_quick and tool_count == 0:
        try:
            from _governance_logger import session_from
            session_id = session_from(payload)
            emit_event(
                event="warn",
                hook="work-verification-check",
                session=session_id,
                extra={
                    "check": "zero-work-non-quick",
                    "tool_count": 0,
                    "has_qa_report": has_qa_report,
                    "is_non_quick": is_non_quick,
                },
            )
            # Set on attempt, not on confirmed write. emit_event swallows I/O
            # errors and returns nothing, so a failed write can no longer fall
            # through to the pass branch and record a misleading pass for a turn
            # that warned. On failure this turn now records neither.
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
            from _governance_logger import session_from
            session_id_h = session_from(payload)
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
                from _governance_logger import session_from
                session_id_e = session_from(payload)
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
            from _governance_logger import session_from
            session_id = session_from(payload)
            emit_event(
                event="pass",
                hook="work-verification-check",
                session=session_id,
                extra={
                    "tool_count": tool_count,
                    "distinct_tool_calls": distinct_tool_calls,
                    "execution_tools": len(execution_tools),
                    "has_qa_report": has_qa_report,
                    "has_pentest_report": has_pentest_report,
                    "response_asks_user": response_asks_user,
                    "has_process_qa": has_process_qa,
                    "qa_via_workflow": qa_via_workflow,
                    "task_type": task_type_token,
                    "turn_boundary": turn_boundary,
                    "window_bytes": window_info.get("window_bytes", 0),
                    "window_capped": bool(window_info.get("capped")),
                },
            )
        except Exception:
            pass


if __name__ == "__main__":
    main()
