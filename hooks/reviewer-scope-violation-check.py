"""
Reviewer Scope Violation Check - PreToolUse Hook (matcher: Write|Edit|MultiEdit)

Design: Projects/Agent-Governance-Research/work/2026-05-25-reviewer-scope-violation-check-design.md
AW-5 Finding 2: evaluative-reviewer sub-agents with Write access can edit the
artifact they were dispatched to review, then produce a critique of their own edit.
This is the runtime enforcement layer (~90% compliance) on top of the prompt-level
"Tool Restrictions" prohibition (~25%) in agent frontmatter.

Blocked agents: adversarial-reviewer, architect-reviewer, code-reviewer.

Detection (§1 of design):
1. PRIMARY — read agent_type from PreToolUse payload. On match, apply FP rules.
2. FALLBACK — if agent_type absent/empty, walk sub-agent transcript (200KB tail)
   for first user entry that contains the agent frontmatter name: field. Sub-agents
   receive their dispatch prompt (including frontmatter) as the first user message
   in their OWN transcript — not the parent session's transcript. The transcript_path
   in a sub-agent's PreToolUse payload points to the sub-agent's JSONL.

False-positive rules applied in order (§3 of design):
  Rule A — if target path matches `work/YYYY-MM-DD-*-review-*.md` → ALLOW (report output)
  Rule C — if target path does NOT exist on disk → ALLOW (new file = new report)
  Otherwise → BLOCK (existing non-review file from reviewer context)

Block format: JSON {"decision": "block", "reason": "..."} to stdout + governance-log entry.
Exit code: always 0 (the structured JSON carries the decision; exit 2 is for non-JSON blocks).

Fast-path: if agent_type absent AND transcript_path absent/missing → exit 0 immediately.
This ensures zero I/O overhead for the dominant case (main-session Write calls).
"""

import sys
import json
import os
import re

# 200KB window — matches all other hardened hooks in this directory
READ_BYTES = 204800

# The evaluative reviewer agents this hook is responsible for blocking.
# code-reviewer is a plugin agent (superpowers/code-review) — included because
# detection is via agent_type field, which is runtime, not frontmatter.
REVIEWER_AGENTS = {"adversarial-reviewer", "architect-reviewer", "code-reviewer"}

# Regex matching the established naming convention for reviewer report output files.
# Pattern: work/ + date + arbitrary name + -review + anything + .md
# Covers: work/2026-05-25-foo-review-adversarial.md, work/2026-05-25-bar-review.md etc.
# NOTE: applied against a forward-slash-normalised copy of the path (see _norm_path)
# to avoid backslash-in-character-class regex issues on Windows.
REVIEW_OUTPUT_RE = re.compile(
    r"work/\d{4}-\d{2}-\d{2}-.+-review.*\.md$",
    re.IGNORECASE,
)

# Regex to extract `name:` field from agent frontmatter in a transcript user message.
# The dispatch prompt contains the full agent definition, which starts with a YAML
# frontmatter block. We look for `name: <agent-name>` near the start of the message.
AGENT_NAME_RE = re.compile(r"^\s*name:\s*([a-zA-Z0-9_-]+)", re.MULTILINE)


def _norm_path(p):
    """Return path with OS separators replaced by forward slashes.
    Used before applying REVIEW_OUTPUT_RE so the regex works on both
    Windows (backslash) and Unix (forward slash) paths without needing
    a backslash-safe character class in the pattern.
    """
    return p.replace(os.sep, "/")

# Observability v2 shared helper — silent on import failure.
try:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _event_emit import emit_event  # type: ignore
except Exception:
    emit_event = None  # type: ignore

# Governance log lives alongside all other hook artefacts.
_HOOK_DIR = os.path.dirname(os.path.abspath(__file__))
_GOVERNANCE_LOG = os.path.join(_HOOK_DIR, "governance-log.jsonl")


def _log_block(session_id, agent_type, tool_name, file_path, reason):
    """Append a reviewer_scope_violation block entry to governance-log.jsonl."""
    try:
        from datetime import datetime
        entry = json.dumps({
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "schema": 2,
            "event": "reviewer_scope_violation",
            "hook": "reviewer-scope-violation-check",
            "session": session_id,
            "agent_type": agent_type,
            "tool_name": tool_name,
            "file_path": file_path,
            "block_reason": reason,
        }, ensure_ascii=False)
        with open(_GOVERNANCE_LOG, "a", encoding="utf-8") as fh:
            fh.write(entry + "\n")
    except Exception:
        # Governance log failure must never break the block itself.
        pass


def _emit_blocked(session_id, agent_type, tool_name, file_path):
    """Fire observability event for the block (separate from governance log)."""
    if emit_event is None:
        return
    try:
        emit_event(
            event="reviewer_scope_violation_blocked",
            hook="reviewer-scope-violation-check",
            session=session_id,
            extra={
                "agent_type": agent_type,
                "tool_name": tool_name,
                "file_path": file_path,
            },
        )
    except Exception:
        pass


def _extract_agent_type_from_transcript(transcript_path):
    """
    Fallback: read the sub-agent's own transcript to find its agent name.

    In CC, a sub-agent's PreToolUse payload transcript_path points to the
    sub-agent's JSONL file (NOT the parent's). The sub-agent's transcript begins
    with a user message that contains the dispatch prompt, which includes the full
    agent frontmatter (including `name: <agent-name>`). We read the first user
    entry and extract the `name:` field.

    Returns the agent name string if found and in REVIEWER_AGENTS, else None.
    This function does NOT check REVIEWER_AGENTS membership — caller does that.
    """
    if not transcript_path or not os.path.exists(transcript_path):
        return None

    try:
        file_size = os.path.getsize(transcript_path)
        read_bytes = min(READ_BYTES, file_size)

        with open(transcript_path, "r", encoding="utf-8", errors="replace") as fh:
            fh.seek(max(0, file_size - read_bytes))
            tail = fh.read()

        # Walk lines looking for first user entry — that's the dispatch prompt
        for raw_line in tail.split("\n"):
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                entry = json.loads(raw_line)
            except json.JSONDecodeError:
                continue

            if entry.get("type") != "user":
                continue

            # Extract text content from the first user message
            message = entry.get("message", {})
            if isinstance(message, str):
                text = message
            else:
                # Standard CC JSONL: message.content is a list of content blocks
                content = message.get("content", [])
                if isinstance(content, str):
                    text = content
                elif isinstance(content, list):
                    parts = []
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            parts.append(block.get("text", ""))
                        elif isinstance(block, str):
                            parts.append(block)
                    text = "\n".join(parts)
                else:
                    text = ""

            m = AGENT_NAME_RE.search(text)
            if m:
                return m.group(1).strip()

            # Only check the first user entry — subsequent user entries are not
            # the dispatch prompt and may introduce false matches.
            break

    except Exception:
        pass

    return None


def main():
    payload_text = sys.stdin.read()
    if not payload_text:
        return

    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError:
        return

    # -------------------------------------------------------------------
    # Step 1: Identify whether this call comes from a reviewer agent.
    # -------------------------------------------------------------------

    # PRIMARY: agent_type field in PreToolUse payload.
    # The SubagentStart payload confirms agent_type is populated (subagent-governance.py
    # line 24). The design assumes PreToolUse shares the same payload schema.
    agent_type = (payload.get("agent_type") or "").strip().lower()

    transcript_path = payload.get("transcript_path") or ""
    session_id = (
        os.path.splitext(os.path.basename(transcript_path))[0]
        if transcript_path else "unknown"
    )

    # FALLBACK: if agent_type absent, try transcript walking.
    if not agent_type:
        fallback_name = _extract_agent_type_from_transcript(transcript_path)
        if fallback_name:
            agent_type = fallback_name.lower()

    # Fast-path exit: not a reviewer → allow immediately (zero further I/O).
    if agent_type not in REVIEWER_AGENTS:
        return

    # -------------------------------------------------------------------
    # Step 2: Extract the target file_path from the tool input.
    # -------------------------------------------------------------------

    tool_input = payload.get("tool_input", {})
    if isinstance(tool_input, str):
        try:
            tool_input = json.loads(tool_input)
        except (json.JSONDecodeError, TypeError):
            tool_input = {}

    tool_name = payload.get("tool_name", "")
    file_path = (tool_input.get("file_path") or "").strip()

    if not file_path:
        # No path to check — cannot determine target, allow (safe failure).
        return

    # -------------------------------------------------------------------
    # Step 3: Apply false-positive exclusion rules (§3 of design).
    # Order matters: Rule A before Rule C (see edge-case in §3).
    # -------------------------------------------------------------------

    # Normalize to forward slashes for cross-platform regex matching.
    # os.path.exists works on the original path; REVIEW_OUTPUT_RE needs the normalised one.
    norm_path = _norm_path(file_path)

    # Rule A: Report-output path regex match → ALLOW.
    # Covers: existing report files being overwritten on a re-run (Rule C would block).
    if REVIEW_OUTPUT_RE.search(norm_path):
        return  # exit 0 — legitimate report output

    # Rule C: File does not yet exist on disk → ALLOW (new file = report output).
    # The artifact under review already exists; the reviewer's output is always new.
    if not os.path.exists(file_path):
        return  # exit 0 — new file, safe to write

    # -------------------------------------------------------------------
    # Step 4: BLOCK — reviewer is attempting to edit an existing non-report file.
    # -------------------------------------------------------------------

    block_reason = (
        f"REVIEWER SCOPE VIOLATION: {agent_type} attempted to {tool_name} "
        f"existing artifact at '{file_path}'. "
        f"Reviewers may only write new report files or paths matching the "
        f"review-output naming convention (work/YYYY-MM-DD-*-review-*.md)."
    )

    # Structured block decision to stdout (CC PreToolUse block protocol).
    print(json.dumps({"decision": "block", "reason": block_reason}))

    # Governance log entry for audit trail.
    _log_block(session_id, agent_type, tool_name, file_path, block_reason)

    # Observability v2 event.
    _emit_blocked(session_id, agent_type, tool_name, file_path)

    # Exit 0: the structured JSON carries the block; exit 2 is for non-JSON blocks.
    return


if __name__ == "__main__":
    # -----------------------------------------------------------------------
    # Smoke tests — only execute on direct invocation, NEVER when CC calls hook.
    # Guard: HOOK_SMOKE_TEST=1 env var is set by the parent test runner on child
    # processes so the child does NOT re-enter this block (avoids infinite recursion).
    # -----------------------------------------------------------------------
    if os.environ.get("HOOK_SMOKE_TEST") == "1":
        # Running as child subprocess invoked BY a smoke test — execute normally.
        main()
        sys.exit(0)

    import subprocess
    import tempfile

    hook_path = os.path.abspath(__file__)
    # Use sys.executable only if it points to a real Python binary.
    # When the smoke tests are run via `python hook.py` directly, sys.executable
    # is the Python interpreter. When the hook is invoked by the CC hook runner
    # (node process), sys.executable may not be Python — fall back to the known path.
    _candidate = sys.executable
    python_exe = (
        _candidate
        if os.path.basename(_candidate).lower().startswith("python")
        else r"C:\Program Files\Python314\python.exe"
    )
    passed = 0
    failed = 0

    def run_hook(payload_dict):
        """Run this hook with the given payload dict, return (returncode, stdout, stderr).
        HOOK_SMOKE_TEST=1 env var prevents the child process from re-entering __main__
        and running tests again (which would cause infinite recursion / timeout).
        """
        stdin_bytes = json.dumps(payload_dict).encode("utf-8")
        env = os.environ.copy()
        env["HOOK_SMOKE_TEST"] = "1"
        result = subprocess.run(
            [python_exe, hook_path],
            input=stdin_bytes,
            capture_output=True,
            timeout=10,
            env=env,
        )
        return result.returncode, result.stdout.decode("utf-8", errors="replace"), result.stderr.decode("utf-8", errors="replace")

    def assert_test(name, condition, detail=""):
        global passed, failed
        status = "PASS" if condition else "FAIL"
        suffix = f" — {detail}" if detail else ""
        print(f"  [{status}] {name}{suffix}")
        if condition:
            passed += 1
        else:
            failed += 1

    print("\nSmoke tests: reviewer-scope-violation-check.py")
    print("=" * 60)

    # ------------------------------------------------------------------
    # TP1: architect-reviewer attempts Edit on an existing file.
    # STATE.md exists on disk → should BLOCK.
    # ------------------------------------------------------------------
    # _HOOK_DIR = .claude/hooks  →  vault root = two levels up
    _vault_root = os.path.dirname(os.path.dirname(_HOOK_DIR))
    existing_target = os.path.join(
        _vault_root,
        "Projects", "Agent-Governance-Research", "STATE.md"
    )
    # If STATE.md doesn't exist locally, fall back to CLAUDE.md (guaranteed).
    if not os.path.exists(existing_target):
        existing_target = os.path.join(_vault_root, "CLAUDE.md")

    tp1_payload = {
        "agent_type": "architect-reviewer",
        "tool_name": "Edit",
        "tool_input": {"file_path": existing_target},
        "transcript_path": "",
    }
    tp1_rc, tp1_out, tp1_err = run_hook(tp1_payload)
    try:
        tp1_json = json.loads(tp1_out.strip())
        tp1_blocked = tp1_json.get("decision") == "block"
    except (json.JSONDecodeError, ValueError):
        tp1_blocked = False
    assert_test(
        "TP1 - architect-reviewer Edit existing artifact -> BLOCK",
        tp1_rc == 0 and tp1_blocked,
        f"exit={tp1_rc} decision={tp1_json.get('decision') if tp1_blocked else 'parse-failed'}"
        if tp1_blocked else f"exit={tp1_rc} stdout={repr(tp1_out[:120])}",
    )

    # ------------------------------------------------------------------
    # TN1: architect-reviewer Write to a NEW file at a work/ report path.
    # The path does NOT exist on disk → Rule C → ALLOW (no block output).
    # ------------------------------------------------------------------
    new_report_path = os.path.join(
        _vault_root,
        "Projects", "Agent-Governance-Research", "work",
        "2026-05-25-test-review-adversarial.md",
    )
    # Ensure the test target doesn't accidentally exist.
    if os.path.exists(new_report_path):
        # Use a guaranteed-nonexistent temp path instead.
        new_report_path = os.path.join(
            tempfile.gettempdir(),
            "2026-05-25-reviewer-hook-test-review-adversarial.md",
        )

    tn1_payload = {
        "agent_type": "architect-reviewer",
        "tool_name": "Write",
        "tool_input": {"file_path": new_report_path},
        "transcript_path": "",
    }
    tn1_rc, tn1_out, tn1_err = run_hook(tn1_payload)
    tn1_no_block = tn1_out.strip() == ""
    assert_test(
        "TN1 - architect-reviewer Write to NEW file -> ALLOW",
        tn1_rc == 0 and tn1_no_block,
        f"exit={tn1_rc} stdout={repr(tn1_out[:120])}",
    )

    # ------------------------------------------------------------------
    # TN2: main-session (no agent_type) Edit on STATE.md → ALLOW (fast-path).
    # ------------------------------------------------------------------
    tn2_payload = {
        # agent_type absent — simulates main-session Write call
        "tool_name": "Edit",
        "tool_input": {"file_path": existing_target},
        "transcript_path": "",
    }
    tn2_rc, tn2_out, tn2_err = run_hook(tn2_payload)
    tn2_no_block = tn2_out.strip() == ""
    assert_test(
        "TN2 - main-session (no agent_type) Edit -> ALLOW (fast-path)",
        tn2_rc == 0 and tn2_no_block,
        f"exit={tn2_rc} stdout={repr(tn2_out[:120])}",
    )

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed out of {passed + failed} tests")
    if failed:
        sys.exit(1)
