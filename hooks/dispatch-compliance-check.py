"""
Dispatch Compliance Check - Stop Hook
Verifies that skills/agents declared in MUST DISPATCH were actually invoked.
Reads transcript tail, finds last MUST DISPATCH field, checks Skill and Agent
tool_use blocks for matching dispatches. Blocks if any declared item is missing.

Regex hardening (2026-03-22):
- 200KB window (up from 80KB) to capture large agent outputs
- Fence stripping: ignores content inside ``` blocks (prevents false matches on docs/examples)
- Case-insensitive field detection
- Multiline MUST DISPATCH: captures across line breaks until next field label
"""

import sys
import json
import os
import re

# H11 integration (2026-04-19): sidecar_loader import with graceful fallback.
# Used when transcript classification block is missing/truncated (post-compaction
# blind spot). Hook dir injected into sys.path so `sidecar_loader` resolves.
_HOOK_DIR = os.path.dirname(os.path.abspath(__file__))
if _HOOK_DIR not in sys.path:
    sys.path.insert(0, _HOOK_DIR)
try:
    from sidecar_loader import mandatory_agent_names
    _SIDECAR_AVAILABLE = True
except ImportError:
    _SIDECAR_AVAILABLE = False

# 200KB window — covers even 10+ agent outputs per turn
READ_BYTES = 204800

# Field labels used as delimiters for multiline capture
FIELD_LABELS = r'(?:IMPLIES|TASK TYPE|CLASSIFICATION|DOMAIN|APPROACH|MISSED)'

# Known agent/skill names — same set as governance-log.py (P0 fix 2026-04-09)
# Used to filter must_dispatch raw text to valid names only, discarding
# trailing reasoning text that would otherwise cause false-positive blocks.
KNOWN_DISPATCH_NAMES = {
    # Agents
    "adversarial-reviewer", "api-designer", "api-security-audit", "architect-review", "architect-reviewer",
    "blueprint-mode", "competitive-analyst", "content-marketer", "data-engineer",
    "debugger", "git-flow-manager", "implementation-plan", "llm-architect",
    "mcp-developer", "mcp-registry-navigator", "mcp-server-architect", "n8n-reviewer",
    "nosql-specialist", "pm-orchestrator", "postgres-pro", "powershell-7-expert",
    "prompt-engineer", "query-clarifier", "report-generator", "research-analyst",
    "research-coordinator", "research-orchestrator", "research-synthesizer",
    "technical-researcher", "vault-keeper", "workflow-orchestrator",
    # Skills
    "process-qa", "process-analysis", "process-build", "process-planning",
    "process-research", "process-pentest", "pm", "task-classifier", "verify",
    "ensemble", "architect-loop", "save", "maintain", "index",
}

# Skill/short-name → agent-name aliases (2026-04-12, coherence fix)
# Must match agent-dispatch-check.py SKILL_AGENT_ALIASES exactly.
# When a declared item in MUST DISPATCH is a skill name but the actual dispatch
# uses the agent's runtime name (e.g., "architect-review" declared but
# "architect-reviewer" dispatched), alias resolution prevents false blocks.
SKILL_AGENT_ALIASES = {
    "pm": {"pm-orchestrator"},
    "architect-review": {"architect-reviewer"},
    "process-planning": {"implementation-plan", "adversarial-reviewer"},
    "process-build": {"blueprint-mode", "architect-reviewer", "implementation-plan"},
    "process-research": {"research-orchestrator", "technical-researcher", "research-analyst"},
    "process-analysis": {"architect-reviewer", "adversarial-reviewer"},
    "process-qa": {"debugger"},
    "process-pentest": {"debugger"},
    "architect-loop": {"architect-reviewer", "adversarial-reviewer"},
}


def extract_dispatch_names(raw_text):
    """Extract only known agent/skill names from MUST DISPATCH raw text.
    Filters trailing reasoning text (P0 fix 2026-04-09)."""
    if not raw_text:
        return []
    raw_lower = raw_text.lower().strip()
    if raw_lower.startswith("none") or raw_lower.startswith("n/a"):
        return []

    found = []
    for segment in raw_text.split(","):
        segment = segment.strip()
        words = segment.split()
        for i in range(min(3, len(words)), 0, -1):
            candidate = " ".join(words[:i]).strip().lower().rstrip(".,;:")
            if candidate in KNOWN_DISPATCH_NAMES:
                found.append(candidate)
                break
    return found


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

    if payload.get("stop_hook_active"):
        return

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

    must_dispatch = []
    dispatched = set()
    found_contract = False
    task_type_str = ""  # Fix 3 (2026-04-14): captured per classification block

    # H11 integration (2026-04-19): unconditional tracking for post-compaction
    # sidecar fallback. `all_dispatched` mirrors `dispatched` but is populated
    # regardless of `found_contract`. `recent_process_skill` is the last-seen
    # process-* / task-classifier Skill invocation — used to identify the active
    # skill when no classification block survives in the window.
    all_dispatched = set()
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
            # Look for classification blocks containing MUST DISPATCH
            if block.get("type") == "text":
                text = block.get("text", "")
                # Bug fix (2026-04-10): strip_fences was removing the actual
                # classification block when output inside markdown fences.
                # Safe to skip: extract_dispatch_names (P0 fix) filters garbage,
                # and the code resets on each new classification block.
                clean = text
                # Only process MUST DISPATCH inside a REAL classification block
                valid_types = r'(?:Quick|Research|Analysis|Content|Build|Planning|Compound)'
                tt_match = re.search(r'(?:TASK TYPE|CLASSIFICATION):\s*' + valid_types, clean, re.IGNORECASE)
                if tt_match:
                    # New classification resets everything
                    must_dispatch = []
                    dispatched = set()
                    found_contract = False
                    # Fix 3 (2026-04-14): capture the TASK TYPE token so the
                    # general-purpose substitution warning can decide whether to fire.
                    _tt_token = tt_match.group(0).split(":", 1)[-1].strip().lower()
                    task_type_str = _tt_token
                    # Multiline MUST DISPATCH: capture until next field label, fence, or end
                    m = re.search(
                        r'MUST DISPATCH:\s*(.*?)(?=\n\s*' + FIELD_LABELS + r'\s*:|\Z)',
                        clean,
                        re.DOTALL | re.IGNORECASE
                    )
                    if m:
                        raw = m.group(1).strip()
                        raw = raw.strip('`')
                        # Collapse whitespace/newlines into single space
                        raw = re.sub(r'\s+', ' ', raw)
                        # P0 fix (2026-04-09): use extract_dispatch_names to filter
                        # trailing reasoning text. Previously split on commas naively,
                        # which included garbage tokens and caused false-positive blocks.
                        must_dispatch = extract_dispatch_names(raw)
                        found_contract = True
                        dispatched = set()

            # Track Skill and Agent dispatches. Two trackers:
            # - `dispatched`: gated on `found_contract` (existing behavior for
            #   enforcement against the current classification's MUST DISPATCH)
            # - `all_dispatched`: unconditional — feeds H11 post-compaction fallback
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
                    # H11: track most-recent NON-TERMINAL process-* skill invocation for fallback.
                    # Exclude terminal skills (process-qa, process-pentest) — they have empty
                    # mandatory lists, so letting them overwrite recent_process_skill nullifies
                    # enforcement for the earlier process-build/process-planning/etc.
                    # (2026-04-19 architect-reviewer Q4 fix: close exploitable nullification gap.)
                    if dispatched_name and (
                        dispatched_name.startswith("process-")
                        or dispatched_name == "task-classifier"
                    ) and dispatched_name not in ("process-qa", "process-pentest"):
                        recent_process_skill = dispatched_name
                elif name == "Agent":
                    dispatched_name = (inp.get("subagent_type") or "").lower()

                if dispatched_name:
                    all_dispatched.add(dispatched_name)
                    if found_contract:
                        dispatched.add(dispatched_name)

    # H11 fallback (2026-04-19): if no classification block found in the 200KB
    # window but a process-* skill was invoked, load the machine-readable
    # mandatory-dispatch contract from the skill's DISPATCHES.json sidecar.
    # This closes the post-compaction enforcement blind spot surfaced by audit
    # finding H11 (2026-04-18). Acts only when the existing transcript scan
    # found nothing — normal contract-present flow is unchanged.
    if not found_contract and recent_process_skill and _SIDECAR_AVAILABLE:
        try:
            sidecar_mandatory = mandatory_agent_names(recent_process_skill)
        except Exception:
            sidecar_mandatory = []
        if sidecar_mandatory:
            must_dispatch = sidecar_mandatory
            dispatched = set(all_dispatched)
            found_contract = True
            task_type_str = "sidecar-fallback"  # non-"quick" so H3 guard passes through
            # Log fallback activation (observability)
            try:
                from datetime import datetime
                log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "governance-log.jsonl")
                session_id = os.path.splitext(os.path.basename(transcript_path))[0] if transcript_path else "unknown"
                entry = json.dumps({
                    "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "event": "h11_sidecar_fallback_activated",
                    "hook": "dispatch-compliance",
                    "session": session_id,
                    "skill": recent_process_skill,
                    "must_dispatch": must_dispatch,
                    "schema": 2,
                })
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(entry + "\n")
            except Exception:
                pass
        # If sidecar exists but has no mandatory dispatches (e.g. process-qa/pentest
        # — terminal skills), fall through to the normal `if not found_contract` return.
        # If sidecar is missing entirely, also fall through (no enforcement possible).

    if not found_contract:
        return

    # H3 fix (2026-04-18): reject empty MUST DISPATCH on non-Quick tasks.
    # The classifier spec states "none is ONLY valid for Quick tasks." Previously
    # this hook accepted any empty must_dispatch silently — the composed B1+B2+B3
    # bypass relied on this. Block non-Quick MUST DISPATCH: none at the contract
    # level before any dispatch checks run.
    # "task_type_str" is lowercase already (line 152); Quick literal is "quick".
    if not must_dispatch:
        if task_type_str and task_type_str != "quick":
            reason = (
                f"DISPATCH COMPLIANCE: MUST DISPATCH is empty ('none') but TASK TYPE "
                f"is '{task_type_str}'. 'none' is ONLY valid for Quick tasks per the "
                f"classifier spec. Re-classify or populate MUST DISPATCH."
            )
            print(json.dumps({"decision": "block", "reason": reason}))
            try:
                from datetime import datetime
                log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "governance-log.jsonl")
                session_id = os.path.splitext(os.path.basename(transcript_path))[0] if transcript_path else "unknown"
                entry = json.dumps({
                    "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "event": "block",
                    "hook": "dispatch-compliance",
                    "session": session_id,
                    "reason": "empty_must_dispatch_on_non_quick",
                    "task_type": task_type_str,
                    "schema": 2,
                })
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(entry + "\n")
            except Exception:
                pass
            return
        # Quick or unknown type with empty MUST DISPATCH — valid, no enforcement needed
        return

    # Alias-aware missing check (2026-04-12 coherence fix):
    # A declared item is satisfied if either the item itself OR any of its
    # aliases are in the dispatched set. E.g., "architect-review" declared,
    # "architect-reviewer" dispatched → satisfied via alias.
    missing = []
    for item in must_dispatch:
        aliases = SKILL_AGENT_ALIASES.get(item, set())
        if item not in dispatched and not (aliases & dispatched):
            missing.append(item)

    if missing:
        reason = (
            f"DISPATCH COMPLIANCE: MUST DISPATCH declared "
            f"[{', '.join(must_dispatch)}] but missing: "
            f"[{', '.join(missing)}]. Invoke them before completing."
        )
        print(json.dumps({"decision": "block", "reason": reason}))
        # Log block event
        try:
            from datetime import datetime
            log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "governance-log.jsonl")
            session_id = os.path.splitext(os.path.basename(transcript_path))[0] if transcript_path else "unknown"  # Full UUID (P1-D fix 2026-04-09)
            entry = json.dumps({"ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "event": "block", "hook": "dispatch-compliance", "session": session_id, "declared": must_dispatch, "missing": missing, "schema": 2})
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(entry + "\n")
        except Exception:
            pass

        # Fix 3 (2026-04-14): general-purpose substitution soft warning.
        # Pure observability — does NOT change block/pass behavior, only writes
        # an additional JSONL line so we can see how often the assistant
        # substitutes general-purpose for a declared specialist.
        try:
            if (
                "general-purpose" in dispatched
                and task_type_str
                and task_type_str != "quick"
            ):
                from datetime import datetime
                log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "governance-log.jsonl")
                session_id = os.path.splitext(os.path.basename(transcript_path))[0] if transcript_path else "unknown"
                warn_entry = json.dumps({
                    "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "event": "warning",
                    "warning": "general-purpose substitution",
                    "hook": "dispatch-compliance",
                    "session": session_id,
                    "task_type": task_type_str,
                    "declared": must_dispatch,
                    "missing": missing,
                    "schema": 2,
                })
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(warn_entry + "\n")
        except Exception:
            pass
    else:
        # P2-B (2026-04-09): Log pass event when all declared items are dispatched.
        # Required for DAR computation without relying on absence-of-block heuristic.
        # H1 fix (2026-04-18): alias-expand matched computation so declared items
        # satisfied via SKILL_AGENT_ALIASES (e.g., architect-review → architect-reviewer)
        # are correctly counted. Previously this used raw set intersection which
        # recorded matched=[], matched_count=0 for every legitimate alias-satisfied
        # Build/Planning pass — silently corrupting DAR analytics for the two
        # highest-frequency task types.
        try:
            from datetime import datetime
            log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "governance-log.jsonl")
            session_id = os.path.splitext(os.path.basename(transcript_path))[0] if transcript_path else "unknown"
            matched_alias_aware = []
            for item in must_dispatch:
                if item in dispatched:
                    matched_alias_aware.append(item)
                else:
                    aliases = SKILL_AGENT_ALIASES.get(item, set())
                    if aliases & dispatched:
                        matched_alias_aware.append(item)
            entry = json.dumps({
                "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "event": "pass",
                "hook": "dispatch-compliance",
                "session": session_id,
                "declared": must_dispatch,
                "matched": sorted(matched_alias_aware),
                "declared_count": len(must_dispatch),
                "matched_count": len(matched_alias_aware),
                "schema": 2,
            })
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(entry + "\n")
        except Exception:
            pass


if __name__ == "__main__":
    main()
