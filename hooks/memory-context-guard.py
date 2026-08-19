#!/usr/bin/env python3
"""memory-context-guard.py: PreToolUse advisory guard (matcher: Write|Edit|MultiEdit)
for writes into the memory folder. Hermes P2 Mechanism A.

Spec: Projects/your-project/work/2026-08-17-hermes-p2-memory-governance-plan.md
(design decisions 1 to 6 and 9). Build plan: 2026-08-18-hermes-p2-build-v2-plan.md.
Binding research verdict: 2026-08-17-hermes-p2-context-discrimination-research.md:
only inside-a-subagent detection is reliable. This hook never claims to detect
scheduled or headless sessions; that claim is unsupported and stays out of every
log field and warning text.

What it does, per in-scope event (a Write/Edit/MultiEdit whose target sits
inside the memory folder):
  1. Classifies the write context with the two-tier pattern proved by
     reviewer-scope-violation-check.py (29,445 live firings):
     payload `agent_type` primary (confirmed live for `workflow-subagent` by
     the Step 2 payload probe, 2026-08-18), transcript-frontmatter scrape of
     `transcript_path` as fallback.
  2. Appends exactly ONE JSONL record to
     .claude/hooks/aggregates/memory-context-warnings.jsonl, including clean
     log-only events, so the calibration denominator is the line count (the
     plain-language-warnings.jsonl precedent). Fields: ts, tool, path,
     context (subagent / main / unknown), agent_type (value or empty string),
     detection_tier (payload / transcript / none), session, decision
     (warn / log).
  3. Resets the memory-persistence counter that memory-nudge.py reads:
     turns_since_memory_write = 0, turns_at_last_nudge = 0,
     last_memory_write_iso stamped. Atomic tmp-then-os.replace write
     (subagent-scope-check.py _save_state precedent). Accepted residual per
     spec decision 9: a write later denied by another hook still resets.
  4. Subagent context: returns permissionDecision "allow" PLUS a
     permissionDecisionReason caution (the bash-safety-guard.py WARN-tier
     mechanism, CLAUDE.md 2026-08-05 amendment). NEVER "deny". The deny tier
     for the three singleton files stays exactly aggregate-write-guard.py.
     Main-session context: log record only, no message.

Fast path: any target outside the memory folder exits 0 immediately with zero
file input or output (reviewer-scope-violation-check.py fast-path precedent).
Boundary rule: prefix match against the normalized folder WITH a trailing
separator, so a sibling like ...\\memory-extra\\f.md never matches.

Env overrides for test isolation (resolved at call time, never at import):
  MEMORY_CONTEXT_GUARD_DIR       the memory folder (spec decision 2)
  MEMORY_CONTEXT_GUARD_LOG_PATH  the JSONL log
  MEMORY_NUDGE_STATE_PATH        the shared counter state file (honored by
                                 BOTH this hook and memory-nudge.py)

Exit codes: 0 always. Any internal exception fails toward allow
(aggregate-write-guard.py precedent): a broken advisory guard must never
block or break ordinary work.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone

_HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))

_DEFAULT_MEMORY_DIR = (
    r"C:\Users\exampleuser\.claude\projects\C--Users-exampleuser-Desktop-Vault"
    r"\memory"
)
_DEFAULT_LOG_PATH = os.path.join(_HOOKS_DIR, "aggregates", "memory-context-warnings.jsonl")
_DEFAULT_STATE_PATH = os.path.join(_HOOKS_DIR, "_state", "memory-nudge.json")

# 200KB head window and frontmatter name regex, both copied from
# reviewer-scope-violation-check.py (the demonstrated two-tier pattern).
READ_BYTES = 204800
AGENT_NAME_RE = re.compile(r"^\s*name:\s*([a-zA-Z0-9_-]+)", re.MULTILINE)


def _memory_dir() -> str:
    return os.environ.get("MEMORY_CONTEXT_GUARD_DIR", "").strip() or _DEFAULT_MEMORY_DIR


def _log_path() -> str:
    return os.environ.get("MEMORY_CONTEXT_GUARD_LOG_PATH", "").strip() or _DEFAULT_LOG_PATH


def _state_path() -> str:
    return os.environ.get("MEMORY_NUDGE_STATE_PATH", "").strip() or _DEFAULT_STATE_PATH


def _norm(path: str) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(path)))


def is_memory_target(file_path: str) -> bool:
    """True iff file_path sits INSIDE the memory folder.

    Prefix match against the normalized folder with a trailing separator
    appended, so a sibling path that shares the folder prefix without the
    separator (...\\memoryX\\f.md) never matches. Pure path arithmetic:
    no file input or output on this path.
    """
    if not file_path:
        return False
    folder = _norm(_memory_dir())
    if not folder.endswith(os.sep):
        folder += os.sep
    return _norm(file_path).startswith(folder)


def _extract_agent_name(transcript_path: str):
    """Transcript-frontmatter fallback, copied from
    reviewer-scope-violation-check.py _extract_agent_type_from_transcript:
    read the HEAD of the subagent's own transcript, find the first user entry
    (the dispatch prompt, which carries the agent frontmatter), extract its
    `name:` field. Returns the name string or None. Never raises."""
    try:
        with open(transcript_path, "r", encoding="utf-8", errors="replace") as fh:
            head = fh.read(READ_BYTES)
        for raw_line in head.split("\n"):
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                entry = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if entry.get("type") != "user":
                continue
            message = entry.get("message", {})
            if isinstance(message, str):
                text = message
            else:
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
            break  # only the first user entry is the dispatch prompt
    except Exception:
        pass
    return None


def classify_context(payload: dict):
    """Returns (context, agent_type, detection_tier).

    context: "subagent" (an agent identity was found), "main" (no subagent
    signal), or "unknown" (a transcript_path was claimed but no such file
    exists, so the fallback could not run). No field ever claims to detect
    scheduled or headless sessions; that axis is out of reach per the
    binding research verdict.
    """
    agent_type = (payload.get("agent_type") or "").strip()
    if agent_type:
        return "subagent", agent_type, "payload"
    transcript_path = payload.get("transcript_path") or ""
    if not transcript_path:
        return "main", "", "none"
    if not os.path.exists(transcript_path):
        return "unknown", "", "none"
    name = _extract_agent_name(transcript_path)
    if name:
        return "subagent", name, "transcript"
    return "main", "", "none"


def _session_from(payload: dict):
    """Session identity via the shared helper (contract C3: a real id or None,
    never a guessed placeholder). Import at call time, silent fallback to None
    when the helper is unreachable (reviewer-scope-violation-check.py precedent)."""
    try:
        sys.path.insert(0, _HOOKS_DIR)
        from _governance_logger import session_from
        return session_from(payload)
    except Exception:
        return None


def _append_record(record: dict) -> None:
    """One JSONL line per in-scope event, warn and log-only alike. Never raises."""
    try:
        log_path = _log_path()
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except Exception:
        pass


def _reset_counter(now_iso: str) -> None:
    """Zero the persistence counter memory-nudge.py reads. Atomic tmp write
    then os.replace (subagent-scope-check.py lines 61 to 68 precedent).
    Last-writer-wins races accepted (advisory tier, multi-session ruling
    2026-08-08). Bootstraps the state file if absent or corrupt. Never raises."""
    try:
        state_path = _state_path()
        state = {}
        try:
            with open(state_path, "r", encoding="utf-8") as fh:
                loaded = json.load(fh)
            if isinstance(loaded, dict):
                state = loaded
        except Exception:
            state = {}
        state["turns_since_memory_write"] = 0
        state["turns_at_last_nudge"] = 0
        state["last_memory_write_iso"] = now_iso
        state.setdefault("last_nudge_iso", "")
        state["updated_iso"] = now_iso
        os.makedirs(os.path.dirname(state_path), exist_ok=True)
        tmp = state_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2)
        os.replace(tmp, state_path)
    except Exception:
        pass


def _emit_warn(agent_type: str, detection_tier: str) -> None:
    """Allow plus caution: the WARN tier, never a deny."""
    reason = (
        "MEMORY CONTEXT GUARD (advisory warning, not a block): this write targets "
        "the memory folder from inside a dispatched subagent "
        f"('{agent_type}', detected via the {detection_tier} tier). "
        "The memory folder is main-session-owned: report memory-worthy findings "
        "back to the orchestrator in your final output instead of writing them "
        "yourself. The write proceeds."
    )
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "permissionDecisionReason": reason,
        }
    }))


def main() -> int:
    try:
        raw = sys.stdin.read()
    except Exception:
        return 0
    try:
        payload = json.loads(raw or "{}")
    except Exception:
        return 0
    try:
        if not isinstance(payload, dict):
            return 0
        tool_name = payload.get("tool_name", "")
        if tool_name not in ("Write", "Edit", "MultiEdit"):
            return 0  # matcher-scope leak guard

        tool_input = payload.get("tool_input", {})
        if isinstance(tool_input, str):
            try:
                tool_input = json.loads(tool_input)
            except (json.JSONDecodeError, TypeError):
                tool_input = {}
        if not isinstance(tool_input, dict):
            return 0

        file_path = (tool_input.get("file_path") or "").strip()
        if not is_memory_target(file_path):
            return 0  # fast path: out of scope, zero file input or output

        context, agent_type, detection_tier = classify_context(payload)
        decision = "warn" if context == "subagent" else "log"
        now_iso = datetime.now(timezone.utc).isoformat()

        _append_record({
            "ts": now_iso,
            "tool": tool_name,
            "path": file_path,
            "context": context,
            "agent_type": agent_type,
            "detection_tier": detection_tier,
            "session": _session_from(payload),
            "decision": decision,
        })
        _reset_counter(now_iso)

        if decision == "warn":
            _emit_warn(agent_type, detection_tier)
        return 0
    except Exception:
        # Fail toward allow: a broken advisory guard must never block work.
        return 0


if __name__ == "__main__":
    sys.exit(main())
