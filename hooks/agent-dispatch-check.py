"""
Agent Dispatch Check - PreToolUse Hook (matcher: Agent)
Validates that the agent being dispatched is in the MUST DISPATCH list.
If MUST DISPATCH is "none" or absent, allows any dispatch.
If MUST DISPATCH lists specific agents, only those are allowed.
Non-specialist dispatches (general-purpose, Explore) are always allowed.

P0 fix (2026-04-09): Use extract_dispatch_names to filter trailing reasoning
text from MUST DISPATCH. Previously used naive comma split which caused
false-positive DENIES on valid dispatches.
Window bump (2026-04-09): 80KB → 200KB to match other hardened hooks.
"""

import sys
import json
import os
import re


# 200KB window: matches other hardened hooks (agent-dispatch bump 2026-04-09)
READ_BYTES = 204800

# Observability v2: shared event-emit helper (silent on import failure)
try:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _event_emit import emit_event  # type: ignore
except Exception:  # pragma: no cover
    emit_event = None  # type: ignore


def _emit_dispatch(session_id, agent_type, must_dispatch, exempted, warn, outcome):
    """Fire event 5 agent_dispatched. Silent on any error."""
    if emit_event is None:
        return
    try:
        emit_event(
            event="agent_dispatched",
            hook="agent-dispatch-check",
            session=session_id,
            extra={
                "agent_type": agent_type,
                "skill_context": must_dispatch or [],
                "exempted_via_registry": bool(exempted),
                "warn_downgrade": bool(warn),
                "outcome": outcome,  # one of: allow, always_allowed, allow_exemption, warn, warn_research_direct, no_classification
            },
        )
    except Exception:
        pass

# Agent types that are always allowed (infrastructure, not specialist routing)
ALWAYS_ALLOWED = {"general-purpose", "explore", "plan", "bash"}

# Process skills that legitimately route to multiple specialists not pre-enumerated
# in classifier MUST DISPATCH. When ANY of these appears in MUST DISPATCH, the main
# session is delegating routing to the skill; any agent in registry.json should be
# allowed through (2026-04-18 fix: architectural bug where allowlist was exclusive).
PROCESS_ROUTING_SKILLS = {
    "process-research", "process-analysis", "process-build",
    "process-planning", "process-qa", "process-pentest",
}

# Family-B (2026-07-15): downstream research-pipeline agents that MUST be
# entered via process-research, never dispatched directly (CLAUDE.md line ~267:
# "Research (enter via process-research, never dispatch downstream directly)").
# Direct dispatch WITHOUT process-research in MUST DISPATCH -> advisory WARN
# (non-blocking, additive; escalation-to-block is a future measurement-gated step).
GUARDED_RESEARCH_AGENTS = {
    "research-orchestrator", "research-analyst", "technical-researcher",
    "research-synthesizer", "report-generator", "research-coordinator",
    "query-clarifier",
}

# Registry path: loaded lazily to list all valid agents (local + plugin)
REGISTRY_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "registry.json"
)

# Step-11 competence gate paths (2026-07-13): module constants so tests can
# repoint them at fixtures (same pattern as REGISTRY_PATH).
GATE_SIDECAR_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "_agent_risk_tiers.json"
)
GATE_LOG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "governance-log.jsonl"
)


def _competence_gate(session_id, agent_type):
    """ADVISORY-ONLY Step-11 competence gate (spec 2026-07-10, DQ-1..DQ-5).

    Computes the per-agent STRUCTURAL RELIABILITY signal (not semantic
    competence) for high-tier agents only, emits one competence_gate_decision
    trace event, and on a BELOW verdict prints a stderr warning. Structurally
    incapable of denying: no stdout write, no decision object, no effect on
    the caller's control flow. Entirely fail-open: any exception is a
    silent allow (Gate-1 remains the only fail-closed layer).
    """
    try:
        with open(GATE_SIDECAR_PATH, "r", encoding="utf-8") as f:
            tiers = json.load(f)
        tier_entry = tiers.get(agent_type)
        if not isinstance(tier_entry, dict) or tier_entry.get("tier") != "high":
            return  # non-high tier: no gate work at all (no event, no log read)

        import _competence_signal  # lazy: only high-tier dispatches pay for it

        result = _competence_signal.get_verdict(GATE_LOG_PATH, agent_type)
        verdict = result.get("verdict", "NO_SIGNAL")
        score = result.get("score")
        n = result.get("n", 0)

        action_taken = "none"
        if verdict == "BELOW":
            action_taken = "warn"
            print(
                f"COMPETENCE GATE (advisory): structural reliability signal "
                f"for '{agent_type}' is BELOW threshold: score={score:.2f} "
                f"over n={n} scored completions (threshold "
                f"{_competence_signal.ADVISORY_THRESHOLD}). Advisory only - "
                f"dispatch proceeds.",
                file=sys.stderr,
            )

        # Decision trace event: deliberately NOT routed through _event_emit
        # (contract C7). GATE_LOG_PATH is also the path this gate READS its own
        # history from, and the tests repoint that constant to isolate a run.
        # Emitting through the shared helper would resolve a different path and
        # break read-your-writes for the gate and its tests alike.
        try:
            from datetime import datetime
            entry = json.dumps({
                "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "schema": 2,
                "event": "competence_gate_decision",
                "hook": "agent-dispatch-check",
                "session": session_id,
                "agent_type": agent_type,
                "risk_tier": "high",
                "score": score,
                "n": n,
                "verdict": verdict,
                "mode": "advisory",
                "action_taken": action_taken,
            })
            with open(GATE_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(entry + "\n")
        except Exception:
            pass
    except Exception:
        pass


def load_registry_agents():
    """Return set of valid agent names from .claude/registry.json (lowercase).
    Registry schema: agents is a dict keyed by agent name.
    """
    try:
        with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        agents = data.get("agents", {})
        if isinstance(agents, dict):
            return {name.lower() for name in agents.keys() if name}
        # Fallback: list-of-dicts schema (legacy)
        if isinstance(agents, list):
            return {
                (a.get("name") or "").lower()
                for a in agents
                if isinstance(a, dict) and a.get("name")
            }
        return set()
    except Exception:
        return set()

# Skill/short-name → agent-name aliases (bug fix 2026-04-10)
# When a skill or short name appears in MUST DISPATCH, dispatching its
# underlying agent(s) should also be allowed. Previously the hook did an
# exact string match, which blocked legit dispatches like:
#   MUST DISPATCH: [pm] → dispatch pm-orchestrator → BLOCKED (false positive)
#   MUST DISPATCH: [architect-review] → dispatch architect-reviewer → BLOCKED
SKILL_AGENT_ALIASES = {
    # Skills that dispatch agents with different names
    "pm": {"pm-orchestrator"},
    "architect-review": {"architect-reviewer"},
    # Process skills dispatch their primary agents
    "process-planning": {"implementation-plan", "adversarial-reviewer"},
    "process-build": {"blueprint-mode", "architect-reviewer", "implementation-plan"},
    "process-research": {"research-orchestrator", "technical-researcher", "research-analyst"},
    "process-analysis": {"architect-reviewer", "adversarial-reviewer"},
    # PRE-I2-A (2026-04-12): 3 additional aliases from plan v2 audit
    "process-qa": {"debugger"},  # dispatched conditionally on QA failure
    "process-pentest": {"debugger"},  # pentest dispatches debugger on findings, not architect-reviewer (skill says "execute yourself")
    "architect-loop": {"architect-reviewer", "adversarial-reviewer"},  # Ralph Loop dispatches reviewers
    # NOTE: process-research does NOT alias research-synthesizer/report-generator: # those are dispatched by research-orchestrator internally, not by the main session.
    # Direct dispatch of downstream agents without process-research is a process violation.
}

# Known agent/skill names: generated from registry.json + a local disk scan
# (2026-08-19, plugin-wiring-investigation fix; see
# .claude/scripts/generate_known_dispatch_names.py for provenance and
# .claude/hooks/_known_dispatch_names_loader.py for the shared read path).
# Was a hand-maintained 93-entry literal duplicated across this file,
# _dispatch_compliance_logic.py, and governance-log.py: of the 54 plugin
# agents in the registry only 47 were listed, and of 138 plugin skills, zero.
#
# Fallback direction for THIS hook if the generated file is missing/unreadable:
# empty set. This hook never denies (see module docstring): every code path
# below ends in allow, always_allowed, allow_exemption, or warn. An empty
# KNOWN_DISPATCH_NAMES just means extract_dispatch_names() recognizes
# nothing, so must_dispatch comes back empty and every dispatch takes the
# existing "no_classification" -> allow path, identical to a classification
# that declared "none" today. Fail-open matches this hook's already-permissive
# posture; a bundled snapshot would add complexity without adding safety here.
from _known_dispatch_names_loader import load_known_dispatch_names
KNOWN_DISPATCH_NAMES = load_known_dispatch_names(
    fallback=set(), warn_label="agent-dispatch-check"
)


def extract_dispatch_names(raw_text):
    """Extract only known agent/skill names from MUST DISPATCH raw text.
    Same logic as governance-log.py and dispatch-compliance-check.py.
    Returns list of valid names (empty list for none/n/a/empty)."""
    if not raw_text:
        return []
    raw_lower = raw_text.lower().strip()
    if raw_lower.startswith("none") or raw_lower.startswith("n/a"):
        return []

    found = []
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


def main():
    payload_text = sys.stdin.read()
    if not payload_text:
        return

    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError:
        return

    # Get the agent being dispatched
    tool_input = payload.get("tool_input", {})
    if isinstance(tool_input, str):
        try:
            tool_input = json.loads(tool_input)
        except (json.JSONDecodeError, TypeError):
            tool_input = {}

    agent_type = (tool_input.get("subagent_type") or "").lower()
    transcript_path = payload.get("transcript_path")
    from _governance_logger import session_from
    session_id = session_from(payload)

    if not agent_type:
        _emit_dispatch(session_id, "", [], False, False, "no_type")
        return  # No type specified = general-purpose, allow

    # Always allow infrastructure agents
    if agent_type in ALWAYS_ALLOWED:
        _emit_dispatch(session_id, agent_type, [], False, False, "always_allowed")
        return

    # Step-11 competence gate (2026-07-13, wired this line): advisory-only
    # structural reliability signal for high-tier named agents. Generic types
    # have already returned above, so the gate sees only named specialist
    # dispatches. Never denies, never returns early, never writes stdout: # see _competence_gate docstring.
    _competence_gate(session_id, agent_type)

    # Read transcript for last MUST DISPATCH
    if not transcript_path or not os.path.exists(transcript_path):
        _emit_dispatch(session_id, agent_type, [], False, False, "no_transcript")
        return  # Can't verify, allow

    file_size = os.path.getsize(transcript_path)
    read_bytes = min(READ_BYTES, file_size)  # 200KB (bumped 2026-04-09)

    with open(transcript_path, "r", encoding="utf-8") as f:
        f.seek(max(0, file_size - read_bytes))
        tail = f.read()

    # Find the last MUST DISPATCH in a valid classification block
    must_dispatch = []
    valid_types = re.compile(
        r'TASK TYPE:\s*(?:Quick|Research|Analysis|Content|Build|Planning|Compound)',
        re.IGNORECASE
    )

    for line in tail.split("\n"):
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
                if valid_types.search(text):
                    # New classification resets
                    must_dispatch = []
                    m = re.search(r'MUST DISPATCH:\s*(.+)', text)
                    if m:
                        raw = m.group(1).strip().strip('`')
                        # P0 fix (2026-04-09): extract only known names,
                        # filter trailing reasoning text to prevent false DENIES
                        must_dispatch = extract_dispatch_names(raw)

    # If no MUST DISPATCH or it's empty/none, allow any agent
    if not must_dispatch:
        _emit_dispatch(session_id, agent_type, [], False, False, "no_classification")
        return

    # Family-B warn (2026-07-15, additive/non-blocking): a guarded downstream
    # research-pipeline agent dispatched DIRECTLY without process-research in the
    # MUST DISPATCH routing context is a process violation (CLAUDE.md line ~267).
    # Warn only: dispatch proceeds; escalation-to-block is a future measurement-
    # gated step. Distinct outcome label keeps this window separable from the
    # pre-existing off-contract 'warn'. Fail-open: never stdout/exit/deny.
    if agent_type in GUARDED_RESEARCH_AGENTS and "process-research" not in must_dispatch:
        print(
            f"RESEARCH DISPATCH (advisory): '{agent_type}' is a downstream "
            f"research-pipeline agent dispatched directly without 'process-research' "
            f"in MUST DISPATCH {must_dispatch}. Doctrine: enter research via "
            f"process-research, never dispatch downstream directly. Logged for review.",
            file=sys.stderr,
        )
        try:
            emit_event(
                event="warn_research_direct",
                hook="agent-dispatch-check",
                session=session_id,
                extra={"agent_type": agent_type, "must_dispatch": must_dispatch},
            )
        except Exception:
            pass
        _emit_dispatch(session_id, agent_type, must_dispatch, False, True, "warn_research_direct")
        # NO return: fall through to the existing allow/deny/exemption logic so
        # the dispatch still proceeds exactly as before. Additive signal only.

    # Expand must_dispatch with skill→agent aliases (bug fix 2026-04-10).
    # If user declared [pm, architect-review], the allowed set should also
    # include [pm-orchestrator, architect-reviewer] which are the agents
    # those skills/short-names actually dispatch.
    allowed = set(must_dispatch)
    for declared in list(must_dispatch):
        if declared in SKILL_AGENT_ALIASES:
            allowed.update(SKILL_AGENT_ALIASES[declared])

    # Check if this agent is in the MUST DISPATCH list (or aliased from it)
    if agent_type not in allowed:
        # B: conditional exemption: if MUST DISPATCH contains any process-* routing
        # skill, the session is legitimately delegating routing to the skill. Any
        # agent listed in registry.json is valid in that context.
        has_process_skill = any(d in PROCESS_ROUTING_SKILLS for d in must_dispatch)
        registry_agents = load_registry_agents() if has_process_skill else set()
        if has_process_skill and agent_type in registry_agents:
            try:
                emit_event(
                    event="allow_process_skill_exemption",
                    hook="agent-dispatch-check",
                    session=session_id,
                    extra={"agent_type": agent_type, "must_dispatch": must_dispatch},
                )
            except Exception:
                pass
            _emit_dispatch(session_id, agent_type, must_dispatch, True, False, "allow_exemption")
            return  # Allowed via process-skill routing exemption

        # A: warn-downgrade: not blocked, but logged and surfaced to stderr.
        # Preserves observability of off-contract dispatches without breaking flow.
        # Original deny mode was too strict (2026-04-18 fix).
        reason = (
            f"AGENT DISPATCH (advisory): '{agent_type}' is not in MUST DISPATCH list "
            f"[{', '.join(must_dispatch)}] and no process-* skill is present to "
            f"authorize specialist routing. Logged for review."
        )
        print(reason, file=sys.stderr)
        # Log warn event (schema: event=warn, not deny)
        try:
            emit_event(
                event="warn",
                hook="agent-dispatch-check",
                session=session_id,
                extra={"agent_type": agent_type, "must_dispatch": must_dispatch},
            )
        except Exception:
            pass
        _emit_dispatch(session_id, agent_type, must_dispatch, False, True, "warn")
        return  # No deny: advisory only

    # Agent is in the list: allow
    _emit_dispatch(session_id, agent_type, must_dispatch, False, False, "allow")
    return


if __name__ == "__main__":
    main()
