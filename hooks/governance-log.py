"""
Governance Log - Stop Hook
Captures classification, dispatch, and agent activity per response.
Appends one JSON line to governance-log.jsonl per response.
Does NOT block: logging only.

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
from datetime import datetime


# LOG_PATH removed 2026-08-01: the only reader was the direct open() this hook
# no longer performs. The destination now lives in _event_emit, which resolves
# GOVERNANCE_LOG_PATH at call time.

# 200KB window: covers even 10+ agent outputs per turn
READ_BYTES = 204800

VALID_TYPES = re.compile(
    r'(?:TASK TYPE|CLASSIFICATION):\s*(Quick|Research|Analysis|Content|Build|Planning|Compound)',
    re.IGNORECASE
)

# Field labels used as delimiters for multiline capture
FIELD_LABELS = r'(?:IMPLIES|TASK TYPE|CLASSIFICATION|DOMAIN|APPROACH|MISSED)'

# Known agent and skill names for must_dispatch extraction (P0 fix 2026-04-09)
# Must_dispatch raw text often contains trailing reasoning after the comma-separated
# names. This set filters to only valid names, discarding garbage tokens.
KNOWN_DISPATCH_NAMES = {
    # Agents (from .claude/agents/)
    "adversarial-reviewer", "api-designer", "api-security-audit", "architect-review", "architect-reviewer",
    "blueprint-mode", "competitive-analyst", "content-marketer", "data-engineer",
    "debugger", "git-flow-manager", "implementation-plan", "llm-architect",
    "mcp-developer", "mcp-registry-navigator", "mcp-server-architect",
    "n8n-reviewer", "n8n-workflow-architect", "n8n-workflow-builder",
    "nosql-specialist", "pm-orchestrator", "postgres-pro", "powershell-7-expert",
    "prompt-engineer", "query-clarifier", "report-generator", "research-analyst",
    "research-coordinator", "research-orchestrator", "research-synthesizer",
    "technical-researcher", "vault-keeper",
    # Skills (from .claude/skills/): only process/governance skills likely in MUST DISPATCH
    "process-qa", "process-analysis", "process-build", "process-planning",
    "process-research", "process-pentest", "pm", "task-classifier", "verify",
    "ensemble", "architect-loop", "save", "maintain", "index",
}


def extract_dispatch_names(raw_text):
    """Extract only known agent/skill names from a must_dispatch raw string.

    The classifier often appends reasoning text after the comma-separated names:
      'process-qa, pm Let me break down...'
    This function splits on commas and whitespace, matches each token against
    KNOWN_DISPATCH_NAMES, and returns only the valid names as a clean comma-separated string.
    """
    if not raw_text:
        return None
    raw_lower = raw_text.lower().strip()
    if raw_lower.startswith("none") or raw_lower.startswith("n/a"):
        return "none"

    # Split on commas first, then check each segment
    found = []
    for segment in raw_text.split(","):
        segment = segment.strip()
        # The name might be followed by reasoning text: try matching the first word(s)
        # that form a known name (handles multi-word like "architect-review")
        words = segment.split()
        for i in range(min(3, len(words)), 0, -1):
            candidate = " ".join(words[:i]).strip().lower().rstrip(".,;:")
            if candidate in KNOWN_DISPATCH_NAMES:
                found.append(candidate)
                break

    return ", ".join(found) if found else None


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

    # Don't log during stop-hook-active retries
    if payload.get("stop_hook_active"):
        return

    # effort.level: Week-19 2026 hook-payload field. Telemetry only; recorded
    # so the analytics layer can correlate effort tier with dispatch compliance,
    # Quick-classification rate, and token usage. Absent on pre-Week-19 payloads.
    effort = payload.get("effort")
    effort_level = (
        str(effort.get("level"))
        if isinstance(effort, dict) and effort.get("level") is not None
        else None
    )

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

    # Extract data from the last assistant turn
    last_type = None
    last_domain = None
    last_must_dispatch = None
    last_implies = None
    agents_dispatched = []
    skills_invoked = []
    wiki_queried = False  # W-V1 Phase 1 (2026-05-26): mcp__qmd__query tool_use detection
    memory_searched_raw = False  # 2026-06-01: raw Grep of a qmd-indexed corpus (memory/ or Resources/KB)

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
                text = block.get("text", "")
                # Strip fenced code blocks to avoid matching examples/docs
                clean = strip_fences(text)

                # Classification fields
                m = VALID_TYPES.search(clean)
                if m:
                    last_type = m.group(1)
                    # Reset ALL state per new classification
                    last_domain = None
                    last_must_dispatch = None
                    last_implies = None
                    agents_dispatched = []
                    skills_invoked = []

                    # IMPLIES (case-insensitive)
                    im = re.search(r'IMPLIES:\s*(.+)', clean, re.IGNORECASE)
                    if im:
                        last_implies = im.group(1).strip()[:200]  # Cap at 200 chars

                    # Domain (case-insensitive)
                    dm = re.search(r'DOMAIN:\s*(.+)', clean, re.IGNORECASE)
                    if dm:
                        last_domain = dm.group(1).strip()

                    # Must dispatch (multiline-aware, case-insensitive)
                    md = re.search(
                        r'MUST DISPATCH:\s*(.*?)(?=\n\s*' + FIELD_LABELS + r'\s*:|\Z)',
                        clean,
                        re.DOTALL | re.IGNORECASE
                    )
                    if md:
                        raw = md.group(1).strip().strip('`')
                        raw = re.sub(r'\s+', ' ', raw)
                        last_must_dispatch = extract_dispatch_names(raw)

            # Track dispatches after classification
            if block.get("type") == "tool_use":
                name = block.get("name", "")
                inp = block.get("input", {})
                if isinstance(inp, str):
                    try:
                        inp = json.loads(inp)
                    except (json.JSONDecodeError, TypeError):
                        inp = {}

                if name == "Agent":
                    agent_type = inp.get("subagent_type") or inp.get("description") or "unknown"
                    agents_dispatched.append(agent_type)
                elif name == "Skill":
                    skill = inp.get("skill") or "unknown"
                    skills_invoked.append(skill)
                elif name.startswith("mcp__qmd__"):
                    # W-V1 Phase 1 (2026-05-26): any qmd MCP tool call counts as a
                    # wiki/memory consult. Includes query (hybrid search), get,
                    # multi_get, status. Collection (agr-kb vs memory) is inside
                    # inp["collection"] but we count both as "consulted retrieval";
                    # downstream analysis can disaggregate.
                    wiki_queried = True
                elif name == "Grep":
                    # 2026-06-01: detect a raw Grep of a qmd-indexed corpus (the
                    # memory folder or Resources/KB). Paired with wiki_queried below
                    # this is the "forgot qmd" baseline signal: searched the corpus
                    # by hand without consulting qmd. Grep only (search intent);
                    # single-file Read is a legitimate fetch, not a forget.
                    gp = (inp.get("path") or "").replace("\\", "/").lower()
                    if ("/memory" in gp and "/projects/" in gp) or "resources/kb" in gp:
                        memory_searched_raw = True

    # Only log if we found a classification this turn
    if not last_type:
        return

    # session_id first, then the transcript stem (P1-D fix 2026-04-09 kept the
    # stem; session_from restores session_id as the primary source). This hook
    # returns early without a transcript, so the two agree in practice here.
    from _governance_logger import session_from
    session_id = session_from(payload)

    extra = {
        "type": last_type,
        "effort_level": effort_level,  # Week-19 effort.level telemetry (P1-E+, 2026-05-22)
        "implies": last_implies,
        "domain": last_domain,
        "must_dispatch": last_must_dispatch,
        "agents": agents_dispatched,  # Agent tool invocations (subagent_type values from Agent calls this turn)
        "skills": skills_invoked,    # Skill tool invocations (skill names from Skill calls this turn)
        "agent_count": len(agents_dispatched),
        "skill_count": len(skills_invoked),
        "wiki_queried": wiki_queried,  # W-V1 Phase 1 (2026-05-26): qmd MCP consultation this turn
        "memory_searched_raw": memory_searched_raw,  # 2026-06-01: raw Grep of memory/KB corpus this turn
        "memory_forgot_qmd": memory_searched_raw and not wiki_queried,  # 2026-06-01: forget signal: searched corpus by hand, never consulted qmd
    }

    # C7 convergence (2026-08-01). This was the last direct writer with its own
    # open(). emit_event supplies ts/schema/event/hook/session/environment and
    # merges the rest, so the record gains `environment` and loses nothing.
    #
    # The catch widens from `except OSError` to emit_event's bare Exception, and
    # that is a fix rather than a cost: json.dumps used to sit inside this try,
    # so a serialization failure escaped the narrow clause and crashed the Stop
    # hook, which crashes the turn. The comment here already said "Don't crash on
    # write failure"; the narrow clause did not implement it. A lost log line is
    # recoverable and C5's DARK_HOOK check surfaces a hook that stops appearing.
    from _event_emit import emit_event
    emit_event(
        event="turn_summary",  # 2026-05-08: schema consistency fix; was a bare row producing the dashboard `legacy_classification` fallback
        hook="governance-log",
        session=session_id,
        extra=extra,
    )


if __name__ == "__main__":
    main()
