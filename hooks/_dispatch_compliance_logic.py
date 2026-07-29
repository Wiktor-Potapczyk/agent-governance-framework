"""Pure logic for dispatch-compliance-check.

Extracted from dispatch-compliance-check.py 2026-05-14 (CC-AUTOMATION-LEARN Step 1).
Functions here have no filesystem or stdin/stdout I/O — they operate on:
- raw MUST DISPATCH text (strings)
- parsed transcript lines (lists of dicts produced by the hook wrapper)
- declared/dispatched sets (regular Python sets)

The hook wrapper handles stdin reading, transcript file I/O, governance-log
writing, and stdout block emission. The logic here is what gets unit-tested.

`vault_root` is not needed by this logic — transcript paths and hook directory
are passed in by the wrapper when needed.
"""
from __future__ import annotations

import re
from typing import TypedDict, cast


class ScanState(TypedDict):
    """State threaded through scan_assistant_text_block across transcript blocks.

    must_dispatch  — declared dispatch names from the latest classification block
    dispatched     — dispatch names actually seen (filled by the hook wrapper)
    found_contract — True once a classification block with MUST DISPATCH is seen
    task_type      — lowercase TASK TYPE token from the latest classification block
    """
    must_dispatch: list[str]
    dispatched: set[str]
    found_contract: bool
    task_type: str


FIELD_LABELS = r'(?:IMPLIES|TASK TYPE|CLASSIFICATION|DOMAIN|APPROACH|MISSED)'
VALID_TASK_TYPES = r'(?:Quick|Research|Analysis|Content|Build|Planning|Compound)'

# Known agent/skill names — kept in sync with governance-log.py.
# Used to filter must_dispatch raw text to valid names only, discarding
# trailing reasoning text that would otherwise cause false-positive blocks.
# NOTE: declared as a regular `set`, not `frozenset`, so the pre-existing
# cross-file drift guard at `test_known_dispatch_names_drift.py` (which uses
# `assertIsInstance(x, set)`) continues to fire — frozenset is not a subclass
# of set. Restored 2026-05-14 per architect-reviewer HIGH finding.
KNOWN_DISPATCH_NAMES = {
    # Agents
    "adversarial-reviewer", "api-designer", "api-security-audit",
    "architect-review", "architect-reviewer",
    "blueprint-mode", "competitive-analyst", "content-marketer", "data-engineer",
    "debugger", "git-flow-manager", "implementation-plan", "llm-architect",
    "mcp-developer", "mcp-registry-navigator", "mcp-server-architect",
    "n8n-reviewer", "n8n-workflow-architect", "n8n-workflow-builder",
    "nosql-specialist", "pm-orchestrator", "postgres-pro", "powershell-7-expert",
    "prompt-engineer", "query-clarifier", "report-generator", "research-analyst",
    "research-coordinator", "research-orchestrator", "research-synthesizer",
    "technical-researcher", "vault-keeper",
    # Skills
    "process-qa", "process-analysis", "process-build", "process-planning",
    "process-research", "process-pentest", "pm", "task-classifier", "verify",
    "ensemble", "architect-loop", "save", "maintain", "index",
}

# Skill/short-name → agent-name aliases (must match agent-dispatch-check.py exactly).
SKILL_AGENT_ALIASES: dict[str, frozenset[str]] = {
    "pm": frozenset({"pm-orchestrator"}),
    "architect-review": frozenset({"architect-reviewer"}),
    "process-planning": frozenset({"implementation-plan", "adversarial-reviewer"}),
    "process-build": frozenset({"blueprint-mode", "architect-reviewer", "implementation-plan"}),
    "process-research": frozenset({"research-orchestrator", "technical-researcher", "research-analyst"}),
    "process-analysis": frozenset({"architect-reviewer", "adversarial-reviewer"}),
    "process-qa": frozenset({"debugger"}),
    "process-pentest": frozenset({"debugger"}),
    "architect-loop": frozenset({"architect-reviewer", "adversarial-reviewer"}),
}


def extract_dispatch_names(raw_text: str) -> list[str]:
    """Extract only known agent/skill names from MUST DISPATCH raw text.

    Filters trailing reasoning text (P0 fix 2026-04-09). "none"/"n/a" returns [].
    Splits on commas, then for each segment tries up to 3-word agent names from
    the start (greedy match) — first hit in KNOWN_DISPATCH_NAMES wins per segment.
    """
    if not raw_text:
        return []
    raw_lower = raw_text.lower().strip()
    if raw_lower.startswith("none") or raw_lower.startswith("n/a"):
        return []

    found: list[str] = []
    for segment in raw_text.split(","):
        segment = segment.strip()
        words = segment.split()
        for i in range(min(3, len(words)), 0, -1):
            candidate = " ".join(words[:i]).strip().lower().rstrip(".,;:")
            if candidate in KNOWN_DISPATCH_NAMES:
                found.append(candidate)
                break
    return found


def strip_fences(text: str) -> str:
    """Remove markdown fenced code blocks to prevent false matches on examples/docs."""
    return re.sub(r'```[\s\S]*?```', '', text)


def find_task_type(text: str) -> str:
    """Return lowercase TASK TYPE token from a classification block, or ''."""
    m = re.search(
        r'(?:TASK TYPE|CLASSIFICATION):\s*' + VALID_TASK_TYPES,
        text,
        re.IGNORECASE,
    )
    if not m:
        return ""
    return m.group(0).split(":", 1)[-1].strip().lower()


def find_must_dispatch_raw(text: str) -> str:
    """Return the raw MUST DISPATCH text (whitespace-collapsed, fence-stripped) or ''."""
    m = re.search(
        r'MUST DISPATCH:\s*(.*?)(?=\n\s*' + FIELD_LABELS + r'\s*:|\Z)',
        text,
        re.DOTALL | re.IGNORECASE,
    )
    if not m:
        return ""
    raw = m.group(1).strip().strip('`')
    return re.sub(r'\s+', ' ', raw)


def compute_missing(
    must_dispatch: list[str],
    dispatched: set[str],
    aliases: dict[str, frozenset[str]] = SKILL_AGENT_ALIASES,
) -> list[str]:
    """Return declared items that were neither dispatched nor satisfied by an alias.

    A declared item is satisfied if EITHER the item itself OR any of its aliases
    are in the dispatched set. E.g., "architect-review" declared, "architect-reviewer"
    dispatched → satisfied via alias.
    """
    missing: list[str] = []
    for item in must_dispatch:
        item_aliases = aliases.get(item, frozenset())
        if item not in dispatched and not (item_aliases & dispatched):
            missing.append(item)
    return missing


def compute_matched_alias_aware(
    must_dispatch: list[str],
    dispatched: set[str],
    aliases: dict[str, frozenset[str]] = SKILL_AGENT_ALIASES,
) -> list[str]:
    """Return declared items satisfied directly OR via alias. Used for DAR logging."""
    matched: list[str] = []
    for item in must_dispatch:
        if item in dispatched:
            matched.append(item)
        else:
            item_aliases = aliases.get(item, frozenset())
            if item_aliases & dispatched:
                matched.append(item)
    return matched


def format_missing_reason(must_dispatch: list[str], missing: list[str]) -> str:
    """Format the block reason for missing dispatches."""
    return (
        f"DISPATCH COMPLIANCE: MUST DISPATCH declared "
        f"[{', '.join(must_dispatch)}] but missing: "
        f"[{', '.join(missing)}]. Invoke them before completing."
    )


def format_empty_dispatch_reason(task_type: str) -> str:
    """Format the block reason for empty MUST DISPATCH on a non-Quick task."""
    return (
        f"DISPATCH COMPLIANCE: MUST DISPATCH is empty ('none') but TASK TYPE "
        f"is '{task_type}'. 'none' is ONLY valid for Quick tasks per the "
        f"classifier spec. Re-classify or populate MUST DISPATCH."
    )


def scan_assistant_text_block(
    text: str,
    state: ScanState,
) -> ScanState:
    """Scan a single assistant-text block and update state if it contains a classification.

    `state` is a ScanState carrying must_dispatch / dispatched / found_contract / task_type.
    Returns the (possibly mutated) state. Pure given a state-dict input.

    A new classification block RESETS must_dispatch, dispatched, and found_contract
    (matching the original hook's reset-per-block behavior).
    """
    tt = find_task_type(text)
    if not tt:
        return state

    new_state = dict(state)
    new_state["task_type"] = tt
    new_state["must_dispatch"] = []
    new_state["dispatched"] = set()
    new_state["found_contract"] = False

    raw = find_must_dispatch_raw(text)
    if raw:
        new_state["must_dispatch"] = extract_dispatch_names(raw)
        new_state["found_contract"] = True
    # dict(state) is statically `dict`, not `ScanState` — cast to keep the
    # declared return type accurate for mypy/pyright (architect-review Finding 2).
    return cast(ScanState, new_state)


def is_terminal_skill(name: str) -> bool:
    """Terminal skills should not overwrite recent_process_skill in the H11 fallback."""
    return name in ("process-qa", "process-pentest")


def is_trackable_process_skill(name: str) -> bool:
    """Skill names that count as 'recent process skill' for the H11 sidecar fallback."""
    if not name:
        return False
    return (name.startswith("process-") or name == "task-classifier") and not is_terminal_skill(name)
