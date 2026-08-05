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
- architect-reviewer not dispatched for process-build/process-planning
- Zero agent dispatches for process skills that should delegate

All checks logged to governance-log.jsonl for analysis.
"""

import sys
import json
import os
import re

# 200KB window: matches other hardened hooks
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
    """HARD: When /pm was invoked, check for PM CHECKPOINT REPORT with Viability verdict
    AND that pm-orchestrator Agent was dispatched after the skill (not just inline text).

    Rubber-stamp hardening (B2 fix 2026-04-13, originally failing test_pm_without_orchestrator_inline_report_blocked;
    implemented 2026-04-18 as part of Opus-4.7 adversarial review of H1 sprint):
    The /pm Skill MUST dispatch pm-orchestrator: otherwise the checkpoint is an inline
    rubber stamp, defeating the whole point of having a PM orchestrator agent.
    """
    pm_invoked = False
    pm_orchestrator_dispatched = False
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
                    pm_orchestrator_dispatched = False  # Reset: track dispatch after latest /pm
                    text_after_pm = []

            # Track pm-orchestrator Agent dispatches that happen AFTER /pm was invoked
            if pm_invoked and block.get("type") == "tool_use" and block.get("name") == "Agent":
                inp = block.get("input", {})
                if isinstance(inp, str):
                    try:
                        inp = json.loads(inp)
                    except (json.JSONDecodeError, TypeError):
                        inp = {}
                subagent = (inp.get("subagent_type") or "").lower()
                if subagent == "pm-orchestrator":
                    pm_orchestrator_dispatched = True

            if pm_invoked and block.get("type") == "text":
                text_after_pm.append(block.get("text", ""))

    if not pm_invoked:
        return True, ""  # /pm not invoked: nothing to check

    has_report = any(
        "PM CHECKPOINT REPORT" in text and re.search(r'Viability:\s*(?:PASS|HOLD|KILL)', text)
        for text in text_after_pm
    )

    # Rubber-stamp guard: if report is present but pm-orchestrator was never dispatched,
    # the report is inline text without the orchestrator actually running. Block.
    if has_report and not pm_orchestrator_dispatched:
        return False, (
            "PM REPORT: inline PM CHECKPOINT REPORT found but pm-orchestrator agent was "
            "not dispatched. /pm requires the pm-orchestrator Agent to run the checkpoint; "
            "writing the report inline is a rubber stamp. Invoke pm-orchestrator properly."
        )

    if has_report:
        return True, ""

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
    """SOFT: For build/planning, architect-reviewer should be dispatched."""
    if process_skill not in ("process-build", "process-planning"):
        return True, ""
    agent_names = {a.lower() for a in agents}
    if any("architect" in a and "review" in a for a in agent_names):
        return True, ""
    return False, "No architect-reviewer dispatch"


def check_agent_dispatch(process_skill, agents):
    """SOFT: Process skills should typically dispatch at least one agent."""
    if process_skill in ("process-qa", "process-pentest"):
        return True, ""  # QA and pentest run inline tests, not agent dispatch
    if len(agents) >= 1:
        return True, ""
    return False, "Zero agents dispatched"


def check_pm_after_increment(lines):
    """HARD: Multi-step increments (2+ TaskCreate) require /pm after all tasks complete + pentest.
    Independent of process skill invocations: runs on every Stop event."""
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
            elif name == "Workflow":
                # 2026-06-11 adoption: process-pentest may run as a Workflow
                # invocation; count it or the PM-after-increment gate silently
                # stops firing (architect review F2).
                wf = (inp.get("name") or "").lower()
                if not wf:
                    sp = inp.get("scriptPath") or ""
                    base = os.path.basename(sp)
                    wf = base[:-3].lower() if base.endswith(".js") else base.lower()
                if wf == "process-pentest":
                    pentest_seen = True

    # Only enforce for multi-step increments
    if task_creates < 2:
        return True, ""

    # Increment not fully complete yet
    if task_completes < task_creates:
        return True, ""

    # Pentest not done yet: pentest enforcement handles this separately
    if not pentest_seen:
        return True, ""

    # All tasks done + pentest done: PM should have been invoked (which resets task_creates).
    # If we reach here, task_creates >= 2 means PM was NOT invoked for this increment.
    return False, f"Increment complete ({task_creates} tasks + pentest) but /pm checkpoint not invoked"


# Anchored + single-line (pentest HIGH 2026-08-01): unanchored matching parsed
# "RECHECK:" and mid-sentence "double CHECK:" as declared clauses, and the DOTALL
# tail captured the NEXT line whenever the clause itself was empty.
_CHECK_CLAUSE_RE = re.compile(r"(?:^|[.;)])[ \t]*CHECK:[ \t]*([^\n]*)", re.MULTILINE)
# Most specific first: re-derivation and tool-call are tested before the generic
# test bucket so a clause naming both lands in the more informative category.
_CHECK_TYPE_KEYWORDS = [
    ("none-exists", ("none-exists",)),
    ("re-derivation", ("re-deriv", "rederiv", "separate agent", "independent", "verifier", "recount", "recompute")),
    ("tool-call", ("validate", "n8n_", "webfetch", "curl", "http", "mcp", "bash", "node --check", "grep")),
    ("test", ("pytest", "test", "assert", "exit 0", "exit code", "suite")),
]


# The gate's 200KB window is 0.05% of a long transcript (measured 2026-08-01: a
# 394MB session held 308 TaskCreate blocks, ZERO of them inside the window), so
# observation reads its own larger bounded window and STAMPS whether it was
# truncated. Consumers must treat a truncated observation as a lower bound.
# NOTE: the same blindness affects check_pm_after_increment's HARD gate. That is
# an enforcement-semantics change and is surfaced to the owner, not fixed here.
OBSERVE_READ_BYTES = 4 * 1024 * 1024


def _read_observation_window(path):
    """Return (lines, truncated) for the observation pass. Never raises."""
    size = os.path.getsize(path)
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        fh.seek(max(0, size - OBSERVE_READ_BYTES))
        return fh.read().split("\n"), size > OBSERVE_READ_BYTES


def _tok_hit(low, tok):
    """Word-boundary match for word-only tokens, substring for symbol-bearing ones.
    Plain substring matching let 'latest' and 'attests' claim the 'test' bucket,
    corrupting the emitted histogram (pentest HIGH 2026-08-01)."""
    probe = tok.strip()
    if probe.replace(" ", "").isalnum():
        return re.search(r"\b" + re.escape(probe) + r"\b", low) is not None
    return probe in low

# A clause is STRONG when it names something executable: a runner, a tool, an
# artifact path, an observable comparison, or an independent re-derivation.
# Absence of every one of these is the WEAK_CHECK signal (see observe_step_checks).
_STRONG_CHECK_TOKENS = (
    "pytest", "unittest", "npm ", "node ", "python ", "bash ", "exit 0", "exit code",
    "test_", "assert", " green", "suite", "returns", "return code", "run ", "rerun",
    "n8n_", "mcp__", "curl", "http", "webfetch", "grep", "glob", "validate", "git ",
    "equals", "matches", "zero errors", "no errors", "count", "diff", "output",
    "re-deriv", "rederiv", "separate agent", "independent", "verifier", "recompute", "recount",
    ".py", ".js", ".md", ".json", ".jsonl", ".mjs", ".sh",
)


def observe_step_checks(lines):
    """Stage 1 instrumentation (ratified 2026-08-01 proposal): count CHECK: clauses
    on TaskCreate descriptions in the transcript tail. ADVISORY ONLY: never blocks.
    Returns None when no TaskCreate is present (nothing to observe).
    Consumers compute the attach-rate over real-UUID sessions only (REV-7 semantics)."""
    task_creates = 0
    with_check = 0
    weak_check = 0
    types = {}
    seen_clauses = []
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
        for block in (entry.get("message", {}) or {}).get("content", []):
            if block.get("type") != "tool_use" or block.get("name") != "TaskCreate":
                continue
            inp = block.get("input", {})
            if isinstance(inp, str):
                try:
                    inp = json.loads(inp)
                except (json.JSONDecodeError, TypeError):
                    inp = {}
            task_creates += 1
            desc = str(inp.get("description") or "")
            seen_clauses.append(desc)  # key on FULL step text: clause-only keys collide
            # Read EVERY clause in the step, not just the first: a weak leading
            # clause used to hide a real one behind it (pentest HIGH). An empty
            # clause is no clause at all.
            clauses = [c.strip() for c in _CHECK_CLAUSE_RE.findall(desc)]
            clauses = [c for c in clauses if c]
            if not clauses:
                continue
            with_check += 1
            resolved = None
            for clause in clauses:
                low = clause.lower()
                ctype = "other"
                for label, keywords in _CHECK_TYPE_KEYWORDS:
                    if any(_tok_hit(low, k) for k in keywords):
                        ctype = label
                        break
                # WEAK_CHECK (pentest HIGH fix 2026-08-01): the doctrine's canonical
                # theater is a SHORT clause restating the goal ("verify the change
                # works"), which a length-only rule scores 0. A clause is weak when
                # it names no executable action, or blows the length cap.
                # `none-exists` is an honest declaration and is never weak.
                weak = ctype != "none-exists" and (
                    len(clause) > 120 or not any(_tok_hit(low, t) for t in _STRONG_CHECK_TOKENS))
                if not weak:
                    resolved = ctype
                    break
            if resolved is None:
                weak_check += 1
                resolved = "weak"
            types[resolved] = types.get(resolved, 0) + 1
    if task_creates == 0:
        return None
    # obs_key (pentest MED fix): every Stop event re-reads the same transcript tail,
    # so repeated Stops re-emit identical observations. Consumers dedupe on
    # (session, obs_key) instead of summing raw records, which would make the
    # attach-rate Stop-count-weighted.
    import hashlib
    obs_key = hashlib.sha256(" ".join(seen_clauses).encode("utf-8")).hexdigest()[:12]
    return {"task_creates": task_creates, "with_check": with_check,
            "weak_check": weak_check, "types": types, "obs_key": obs_key}


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

    # Stage 1 step-check observation (ratified 2026-08-01): advisory emit, fail-open.
    try:
        from _event_emit import emit_event
        obs_lines, obs_truncated = _read_observation_window(transcript_path)
        obs = observe_step_checks(obs_lines)
        if obs is not None:
            obs["window_truncated"] = obs_truncated
            from _governance_logger import session_from
            session_id = session_from(payload)
            emit_event(
                event="step_check_observation",
                hook="process-step-check",
                session=session_id,
                extra=obs,
            )
    except Exception:
        pass  # instrumentation must never break the gate

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

        # B-1b fix (2026-06-11): Turn-boundary reset must fire only on REAL user
        # messages, not on tool_result wrapper entries. A Workflow invocation lands
        # as three transcript entries:
        #   1. assistant: Workflow tool_use
        #   2. user: tool_result wrapper  ← NOT a real user turn
        #   3. assistant: relay text (contains SCOPE/QA REPORT)
        # If we reset on entry 2, found_skill is False before the relay text (entry 3)
        # arrives, and the SCOPE/QA-REPORT check silently skips: B-1a without B-1b
        # has zero enforcement effect.
        # Real user message: content is a plain string, or a list containing a "text"
        # block that is not all-tool_result. Ported from work-verification-check.py
        # lines 335-372 (same logic, same comment structure).
        if entry.get("type") == "user" and found_skill:
            content = entry.get("message", {}).get("content")
            is_real_user = False
            if isinstance(content, str):
                is_real_user = True
            elif isinstance(content, list):
                has_text = any(
                    isinstance(b, dict) and b.get("type") == "text"
                    for b in content
                )
                has_only_tool_result = all(
                    isinstance(b, dict) and b.get("type") == "tool_result"
                    for b in content
                ) if content else False
                if has_text and not has_only_tool_result:
                    is_real_user = True
            if is_real_user:
                # The previous turn had a process skill. A real user message means
                # that turn completed: reset state so we don't re-check on future turns.
                last_process_skill = None
                text_after_skill = []
                agents_after_skill = []
                found_skill = False

        if entry.get("type") != "assistant":
            continue

        message = entry.get("message", {})
        for block in message.get("content", []):
            # B-1a fix (2026-06-11): Detect process skill invocation via EITHER
            # a Skill tool_use (existing path) OR a Workflow tool_use whose name/
            # scriptPath basename maps to a process-* skill. Without this branch,
            # Workflow-based process skills are never recognized and SCOPE/QA REPORT
            # checks go silent for all converted skills.
            if block.get("type") == "tool_use" and block.get("name") == "Workflow":
                inp = block.get("input", {})
                if isinstance(inp, str):
                    try:
                        inp = json.loads(inp)
                    except (json.JSONDecodeError, TypeError):
                        inp = {}
                wf_name = (inp.get("name") or inp.get("workflow_name") or "").strip().lower()
                if not wf_name:
                    sp = inp.get("scriptPath") or ""
                    base = os.path.basename(sp)
                    wf_name = base[:-3].lower() if base.endswith(".js") else base.lower()
                if wf_name.startswith("process-"):
                    last_process_skill = wf_name
                    text_after_skill = []
                    agents_after_skill = []
                    found_skill = True
                    continue

            # Detect process skill invocation via Skill tool
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
            from _event_emit import emit_event
            from _governance_logger import session_from
            session_id = session_from(payload)
            emit_event(
                event="block",
                hook="process-step-check",
                session=session_id,
                extra={
                    "process": "pm-enforcement",
                    "hard_failures": [pm_msg],
                    "soft_warnings": [],
                },
            )
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
            from _event_emit import emit_event
            from _governance_logger import session_from
            session_id = session_from(payload)
            emit_event(
                event="block",
                hook="process-step-check",
                session=session_id,
                extra={
                    "process": "pm-report-enforcement",
                    "hard_failures": hard_failures_pm,
                    "soft_warnings": [],
                },
            )
        except Exception:
            pass
        reason = f"PM REPORT: {pm_report_msg}. Add PM CHECKPOINT REPORT block after /pm output."
        print(json.dumps({"decision": "block", "reason": reason}))
        return

    if not last_process_skill or not found_skill:
        return  # No process skill invoked this turn: nothing to check

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
        from _event_emit import emit_event
        from _governance_logger import session_from
        session_id = session_from(payload)
        emit_event(
            event="block" if hard_failures else ("warn" if soft_warnings else "pass"),
            hook="process-step-check",
            session=session_id,
            extra={
                "process": last_process_skill,
                "hard_failures": hard_failures,
                "soft_warnings": soft_warnings,
                "agent_count": len(agents_after_skill),
                "agents": agents_after_skill,
            },
        )
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
