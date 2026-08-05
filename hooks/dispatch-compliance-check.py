"""
Dispatch Compliance Check - Stop Hook
Verifies that skills/agents declared in MUST DISPATCH were actually invoked.
Reads transcript tail, finds last MUST DISPATCH field, checks Skill, Agent, and
Workflow tool_use blocks for matching dispatches. Blocks if any declared item is missing.

Regex hardening (2026-03-22):
- 200KB window (up from 80KB) to capture large agent outputs
- Fence stripping: ignores content inside ``` blocks (prevents false matches on docs/examples)
- Case-insensitive field detection
- Multiline MUST DISPATCH: captures across line breaks until next field label

Refactored 2026-05-14 (CC-AUTOMATION-LEARN Step 1): pure logic now lives in
`_dispatch_compliance_logic.py`. This file is the thin I/O wrapper: transcript
file reads, sidecar fallback orchestration, governance-log writing, stdout
block emission. KNOWN_DISPATCH_NAMES / SKILL_AGENT_ALIASES / extract_dispatch_names /
strip_fences are re-exported at module level for any importers.
"""

import sys
import json
import os
import re
import uuid

# Make sibling logic module importable BEFORE the sidecar import below,
# since both live in the same directory.
_HOOK_DIR = os.path.dirname(os.path.abspath(__file__))
if _HOOK_DIR not in sys.path:
    sys.path.insert(0, _HOOK_DIR)

# Backward-compatibility shim (LOW-2, 2026-05-21).
# Before the 2026-05-14 Step 1 extraction these names were DEFINED in this file.
# They now live in `_dispatch_compliance_logic.py`. This block re-exports them
# at module level as defensive future-proofing: a consumer that loads this hook
# via importlib / sys.path manipulation (the filename is hyphenated, so a plain
# `import` statement cannot reach it) still sees the same symbols it would have
# before the extraction. No such consumer exists in the repo today: both
# `governance-log.py` and `agent-dispatch-check.py` keep their own independent
# copies of KNOWN_DISPATCH_NAMES: so the shim is precautionary, not
# load-bearing. New code should import from `_dispatch_compliance_logic` directly.
from _dispatch_compliance_logic import (  # noqa: E402
    FIELD_LABELS,
    KNOWN_DISPATCH_NAMES,
    SKILL_AGENT_ALIASES,
    compute_matched_alias_aware,
    compute_missing,
    extract_dispatch_names,
    find_must_dispatch_raw,
    find_task_type,
    format_empty_dispatch_reason,
    format_missing_reason,
    is_trackable_process_skill,
    scan_assistant_text_block,
    strip_fences,
)

# H11 integration (2026-04-19): sidecar_loader import with graceful fallback.
# Used when transcript classification block is missing/truncated (post-compaction
# blind spot).
try:
    from sidecar_loader import mandatory_agent_names
    _SIDECAR_AVAILABLE = True
except ImportError:
    _SIDECAR_AVAILABLE = False

# 200KB window: covers even 10+ agent outputs per turn
READ_BYTES = 204800

# GAP-4 dual-emit (2026-07-10): date the dual-emit migration landed. The legacy
# int `schema` field may retire after consumers move to `schema_version`.
LEGACY_SCHEMA_RETIREMENT_DATE = "2026-07-10"


def stamp_and_append(entry, log_path, correlation_id):
    """GAP-4 dual-emit (2026-07-10): stamp the new schema fields onto a
    governance-log entry dict and append it as one JSONL line.

    Dual-emit contract: the legacy `schema: 2` int field each emit site already
    sets stays UNTOUCHED: old and new fields coexist; nothing is renamed or
    removed. New fields:
      - schema_version: "2" (string form of the current schema)
      - correlation_id: uuid4 string generated ONCE per hook invocation and
        shared by every entry that run emits, so a dispatch-chain correlates
      - retirement_date: the dual-emit migration date (see constant above)

    Raises on I/O failure: every call site wraps in its existing try/except
    (the hook must never crash on a logging failure)."""
    entry["schema_version"] = "2"
    entry["correlation_id"] = correlation_id
    entry["retirement_date"] = LEGACY_SCHEMA_RETIREMENT_DATE
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


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

    # GAP-4 (2026-07-10): ONE correlation id per hook invocation, shared by every
    # governance-log entry this run emits (see stamp_and_append).
    correlation_id = str(uuid.uuid4())

    try:
        import os as _gho, sys as _ghs
        _ghs.path.insert(0, _gho.path.dirname(_gho.path.abspath(__file__)))
        from _governance_logger import log_fire
        log_fire("dispatch-compliance-check")
    except Exception:
        pass

    transcript_path = payload.get("transcript_path")
    if not transcript_path or not os.path.exists(transcript_path):
        return

    # Read last 200KB of transcript
    file_size = os.path.getsize(transcript_path)
    read_bytes = min(READ_BYTES, file_size)

    with open(transcript_path, "r", encoding="utf-8", errors="replace") as f:
        f.seek(max(0, file_size - read_bytes))
        tail = f.read()

    lines = tail.split("\n")

    # Scan state: must_dispatch / dispatched / found_contract / task_type
    # plus H11 trackers (all_dispatched, recent_process_skill).
    state = {
        "must_dispatch": [],
        "dispatched": set(),
        "found_contract": False,
        "task_type": "",
    }
    all_dispatched: set[str] = set()
    recent_process_skill = None

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
            if block.get("type") == "text":
                # Pure logic decides whether this block changes state.
                state = scan_assistant_text_block(block.get("text", ""), state)

            if block.get("type") == "tool_use":
                name = block.get("name", "")
                inp = block.get("input", {})
                if isinstance(inp, str):
                    try:
                        inp = json.loads(inp)
                    except (json.JSONDecodeError, TypeError):
                        inp = {}

                dispatched_name = None
                if name == "Skill":
                    dispatched_name = (inp.get("skill") or "").lower()
                    if is_trackable_process_skill(dispatched_name):
                        recent_process_skill = dispatched_name
                elif name == "Agent":
                    dispatched_name = (inp.get("subagent_type") or "").lower()
                elif name == "Workflow":
                    dispatched_name = (inp.get("name") or "").lower()
                    if not dispatched_name:
                        sp = inp.get("scriptPath") or ""
                        base = os.path.basename(sp)
                        dispatched_name = base[:-3].lower() if base.endswith(".js") else base.lower()
                    # Deliberately do NOT set recent_process_skill here: a
                    # workflow-converted skill performs its sidecar dispatches
                    # INSIDE the workflow run (invisible to this transcript), so
                    # arming the H11 sidecar fallback off a Workflow invocation
                    # demands dispatches that can never appear here: false
                    # positive hit live 2026-06-11 (process-planning acceptance
                    # run). The workflow script itself IS the dispatch guarantee.

                if dispatched_name:
                    all_dispatched.add(dispatched_name)
                    if state["found_contract"]:
                        state["dispatched"].add(dispatched_name)

    # H11 fallback (2026-04-19): if no classification block found but a
    # process-* skill was invoked, load mandatory-dispatch contract from
    # the skill's DISPATCHES.json sidecar.
    if not state["found_contract"] and recent_process_skill and _SIDECAR_AVAILABLE:
        try:
            sidecar_mandatory = mandatory_agent_names(recent_process_skill)
        except Exception:
            sidecar_mandatory = []
        if sidecar_mandatory:
            state["must_dispatch"] = sidecar_mandatory
            state["dispatched"] = set(all_dispatched)
            state["found_contract"] = True
            state["task_type"] = "sidecar-fallback"
            try:
                from datetime import datetime
                log_path = os.path.join(_HOOK_DIR, "governance-log.jsonl")
                from _governance_logger import session_from
                session_id = session_from(payload)
                stamp_and_append({
                    "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "event": "h11_sidecar_fallback_activated",
                    "hook": "dispatch-compliance",
                    "session": session_id,
                    "skill": recent_process_skill,
                    "must_dispatch": state["must_dispatch"],
                    "schema": 2,
                }, log_path, correlation_id)
            except Exception:
                pass

    if not state["found_contract"]:
        return

    must_dispatch = state["must_dispatch"]
    dispatched = state["dispatched"]
    task_type_str = state["task_type"]

    # H3 fix (2026-04-18): reject empty MUST DISPATCH on non-Quick tasks.
    if not must_dispatch:
        if task_type_str and task_type_str != "quick":
            reason = format_empty_dispatch_reason(task_type_str)
            print(json.dumps({"decision": "block", "reason": reason}))
            try:
                from datetime import datetime
                log_path = os.path.join(_HOOK_DIR, "governance-log.jsonl")
                from _governance_logger import session_from
                session_id = session_from(payload)
                stamp_and_append({
                    "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "event": "block",
                    "hook": "dispatch-compliance",
                    "session": session_id,
                    "reason": "empty_must_dispatch_on_non_quick",
                    "task_type": task_type_str,
                    "schema": 2,
                }, log_path, correlation_id)
            except Exception:
                pass
            return
        # Quick or unknown type with empty MUST DISPATCH: valid
        return

    missing = compute_missing(must_dispatch, dispatched, SKILL_AGENT_ALIASES)

    if missing:
        reason = format_missing_reason(must_dispatch, missing)
        print(json.dumps({"decision": "block", "reason": reason}))
        try:
            from datetime import datetime
            log_path = os.path.join(_HOOK_DIR, "governance-log.jsonl")
            from _governance_logger import session_from
            session_id = session_from(payload)
            stamp_and_append({
                "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "event": "block",
                "hook": "dispatch-compliance",
                "session": session_id,
                "declared": must_dispatch,
                "missing": missing,
                "schema": 2,
            }, log_path, correlation_id)
        except Exception:
            pass

        # Fix 3 (2026-04-14): general-purpose substitution soft warning.
        try:
            if (
                "general-purpose" in dispatched
                and task_type_str
                and task_type_str != "quick"
            ):
                from datetime import datetime
                log_path = os.path.join(_HOOK_DIR, "governance-log.jsonl")
                from _governance_logger import session_from
                session_id = session_from(payload)
                stamp_and_append({
                    "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "event": "warning",
                    "warning": "general-purpose substitution",
                    "hook": "dispatch-compliance",
                    "session": session_id,
                    "task_type": task_type_str,
                    "declared": must_dispatch,
                    "missing": missing,
                    "schema": 2,
                }, log_path, correlation_id)
        except Exception:
            pass
    else:
        # P2-B (2026-04-09): Log pass event when all declared items are dispatched.
        try:
            from datetime import datetime
            log_path = os.path.join(_HOOK_DIR, "governance-log.jsonl")
            from _governance_logger import session_from
            session_id = session_from(payload)
            matched_alias_aware = compute_matched_alias_aware(must_dispatch, dispatched, SKILL_AGENT_ALIASES)
            stamp_and_append({
                "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "event": "pass",
                "hook": "dispatch-compliance",
                "session": session_id,
                "declared": must_dispatch,
                "matched": sorted(matched_alias_aware),
                "declared_count": len(must_dispatch),
                "matched_count": len(matched_alias_aware),
                "schema": 2,
            }, log_path, correlation_id)
        except Exception:
            pass


if __name__ == "__main__":
    main()
