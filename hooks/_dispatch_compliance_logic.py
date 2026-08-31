"""Pure logic for dispatch-compliance-check.

Extracted from dispatch-compliance-check.py 2026-05-14 (CC-AUTOMATION-LEARN Step 1).
Functions here have no filesystem or stdin/stdout I/O: they operate on:
- raw MUST DISPATCH text (strings)
- parsed transcript lines (lists of dicts produced by the hook wrapper)
- declared/dispatched sets (regular Python sets)

The hook wrapper handles stdin reading, transcript file I/O, governance-log
writing, and stdout block emission. The logic here is what gets unit-tested.

`vault_root` is not needed by this logic: transcript paths and hook directory
are passed in by the wrapper when needed.

One exception to the no-I/O rule: the KNOWN_DISPATCH_NAMES module-level
constant is populated by a single file read at import time via
_known_dispatch_names_loader (2026-08-19): see the comment at that
assignment below. This mirrors how the constant was already populated (as a
literal) before; only the source of the literal moved.
"""
from __future__ import annotations

import os
import re
import sys
from typing import TypedDict, cast

_HOOK_DIR = os.path.dirname(os.path.abspath(__file__))
if _HOOK_DIR not in sys.path:
    sys.path.insert(0, _HOOK_DIR)


class ScanState(TypedDict):
    """State threaded through scan_assistant_text_block across transcript blocks.

    must_dispatch: declared dispatch names from the latest classification block
    dispatched: dispatch names actually seen (filled by the hook wrapper)
    found_contract: True once a classification block with MUST DISPATCH is seen
    task_type: lowercase TASK TYPE token from the latest classification block
    """
    must_dispatch: list[str]
    dispatched: set[str]
    found_contract: bool
    task_type: str


FIELD_LABELS = r'(?:IMPLIES|TASK TYPE|CLASSIFICATION|DOMAIN|APPROACH|MISSED)'
VALID_TASK_TYPES = r'(?:Quick|Research|Analysis|Content|Build|Planning|Compound)'

# Known agent/skill names: generated from registry.json + a local disk scan
# (2026-08-19, plugin-wiring-investigation fix; see
# .claude/scripts/generate_known_dispatch_names.py for provenance and
# .claude/hooks/_known_dispatch_names_loader.py for the shared read path).
# Used to filter must_dispatch raw text to valid names only, discarding
# trailing reasoning text that would otherwise cause false-positive blocks.
#
# _LAST_KNOWN_GOOD_NAMES is the frozen pre-2026-08-19 hand-maintained
# snapshot (93 names), kept as the fallback for THIS hook specifically. It is
# the highest-stakes of the three consumers: dispatch-compliance-check.py is
# the Stop hook with a real `{"decision":"block"}` branch
# (format_empty_dispatch_reason) that fires whenever MUST DISPATCH extracts
# to empty on a non-Quick task. An EMPTY fallback set would make every
# non-Quick turn's MUST DISPATCH extract to empty regardless of what was
# actually declared, i.e. it would block every non-Quick turn the moment the
# generated file went missing: exactly the "silently over-block" failure
# the fallback exists to prevent. Falling back to the exact set this hook
# already enforced (rather than a superset or an empty set) means a missing
# generated file degrades this hook to TODAY's behavior, no worse.
_LAST_KNOWN_GOOD_NAMES = {
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
    "process-qa", "process-analysis", "process-build", "process-planning",
    "process-research", "process-pentest", "pm", "task-classifier", "verify",
    "ensemble", "architect-loop", "save", "maintain", "index",
    "abstract_bilingual_agent", "agent-creator", "agent-sdk-verifier-py",
    "agent-sdk-verifier-ts", "argument_builder_agent",
    "atomic-explorer", "atomic-reviewer", "bibliography_agent",
    "citation_compliance_agent", "code-architect", "code-explorer",
    "code-reviewer", "collaboration_depth_agent", "comment-analyzer",
    "conversation-analyzer",
    "devils_advocate_agent", "devils_advocate_reviewer_agent", "domain_reviewer_agent",
    "draft_writer_agent", "editor_in_chief_agent", "editorial_synthesizer_agent",
    "eic_agent", "ethics_review_agent", "field_analyst_agent",
    "integrity_verification_agent", "literature_strategist_agent", "meta_analysis_agent",
    "methodology_reviewer_agent", "peer_reviewer_agent",
    "perspective_reviewer_agent", "pipeline_orchestrator_agent", "plugin-validator",
    "pr-test-analyzer", "report_compiler_agent", "research_architect_agent",
    "research_question_agent", "revision_coach_agent", "risk_of_bias_agent",
    "silent-failure-hunter", "skill-reviewer", "socratic_mentor_agent",
    "source_verification_agent", "state_tracker_agent", "structure_architect_agent",
    "synthesis_agent", "type-design-analyzer", "visualization_agent",
}

# NOTE: declared as a regular `set`, not `frozenset`, so the pre-existing
# cross-file drift guard at `test_known_dispatch_names_drift.py` (which uses
# `assertIsInstance(x, set)`) continues to fire: frozenset is not a subclass
# of set. Restored 2026-05-14 per architect-reviewer HIGH finding.
from _known_dispatch_names_loader import load_known_dispatch_names  # noqa: E402

KNOWN_DISPATCH_NAMES = load_known_dispatch_names(
    fallback=set(_LAST_KNOWN_GOOD_NAMES), warn_label="dispatch-compliance-check"
)

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
    the start (greedy match): first hit in KNOWN_DISPATCH_NAMES wins per segment.
    """
    if not raw_text:
        return []
    raw_lower = raw_text.lower().strip()
    if raw_lower.startswith(("none", "n/a")):
        return []

    found: list[str] = []
    # Separator handling (2026-08-22, owner-approved). This used to split on
    # commas only, so "process-qa and pm" declared just process-qa and the
    # obligation on every name after the "and" was never checked: a silent
    # bypass of the harness's own mandatory-dispatch rule, reachable by
    # ordinary English phrasing rather than by intent. "and" requires
    # whitespace on both sides so it cannot split a name that merely contains
    # the letters (e.g. "brand"). This makes the gate STRICTER: more declared
    # names means more names that must actually be dispatched.
    for segment in re.split(r",|;|\s+and\s+|\s*&\s*", raw_text):
        segment = segment.strip()
        words = segment.split()
        for i in range(min(3, len(words)), 0, -1):
            candidate = " ".join(words[:i]).strip().lower().rstrip(".,;:")
            if candidate in KNOWN_DISPATCH_NAMES:
                found.append(candidate)
                break
            # Defect 5 (2026-08-07): a plugin-namespaced dispatch name (e.g.
            # "pr-review-toolkit:silent-failure-hunter") is a single
            # whitespace-free token, so the word-count loop above never sees
            # it split apart. registry.json's own agent names are plain
            # (unqualified), so recognize the token by its post-colon suffix
            # instead of requiring every specific plugin's namespace prefix
            # to be hardcoded here.
            if ":" in candidate:
                suffix = candidate.rsplit(":", 1)[-1].strip()
                if suffix in KNOWN_DISPATCH_NAMES:
                    found.append(suffix)
                    break
    return found


def normalize_dispatched_name(name: str) -> str:
    """Normalize a raw tool_use dispatch identifier to the bare form used
    throughout KNOWN_DISPATCH_NAMES / must_dispatch.

    Defect 5 follow-up (2026-08-07): extract_dispatch_names already reduces a
    plugin-namespaced DECLARATION (e.g. "pr-review-toolkit:silent-failure-hunter")
    to its post-colon suffix before it enters must_dispatch. The wrapper's
    dispatched-name construction did not apply the same reduction, so a real
    Agent dispatch under its namespaced runtime name never matched a bare
    declaration (or even an identically-namespaced one, since the declared
    side had already been normalized down to the suffix and the dispatched
    side had not). This is the smaller of the two possible fixes named in the
    finding: normalize the dispatched side to match the declared side, rather
    than requiring every declaration to spell out a plugin namespace the
    classifier has no reliable way to know.
    """
    if name and ":" in name:
        return name.rsplit(":", 1)[-1].strip()
    return name


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
    # dict(state) is statically `dict`, not `ScanState`: cast to keep the
    # declared return type accurate for mypy/pyright (architect-review Finding 2).
    return cast(ScanState, new_state)


def is_terminal_skill(name: str) -> bool:
    """Terminal skills should not overwrite recent_process_skill in the H11 fallback."""
    return name in ("process-qa", "process-pentest")


def is_trackable_process_skill(name: str) -> bool:
    """Skill names that count as 'recent process skill' for the H11 sidecar fallback."""
    if not name:
        return False
    # "pm" added 2026-08-31 (owner-ruled O5 fix): its DISPATCHES.json existed
    # but this gate never armed it, so the pm contract was dead weight.
    trackable = name.startswith("process-") or name in ("task-classifier", "pm")
    return trackable and not is_terminal_skill(name)


def merged_sidecar_contract(skills, mandatory_lookup):
    """Union the sidecar contracts of every trackable skill seen, in order.

    H11 fallback helper (architect finding 2026-08-31): last-wins overwrite let
    a terminal-position pm dispatch replace the substantive skill's contract in
    the fallback, so the check enforced only pm-orchestrator. The fallback now
    enforces the UNION of all trackable skills' contracts. A lookup failure for
    one skill drops only that skill's names, never the others'.
    """
    merged: list[str] = []
    for skill in skills:
        try:
            names = mandatory_lookup(skill) or []
        except Exception:
            names = []
        for n in names:
            if n not in merged:
                merged.append(n)
    return merged
