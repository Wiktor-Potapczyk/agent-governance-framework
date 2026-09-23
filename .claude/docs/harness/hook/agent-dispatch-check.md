---
component: "agent-dispatch-check"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: agent-dispatch-check

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/agent-dispatch-check.py`
- **Provenance:** authored-in-harness
- **Reachability:** none recorded; blocked: `BLK-001`
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:**
  - inbound mentioned_in_prose process-governance-mine [unresolved: prose mention only]
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Agent Dispatch Check - PreToolUse Hook (matcher: Agent)
Validates that the agent being dispatched is in the MUST DISPATCH list.
If MUST DISPATCH is "none" or absent, allows any dispatch.
If MUST DISPATCH lists specific agents, only those are allowed.
Non-specialist dispatches (general-purpose, Explore) are always allowed.

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

PreToolUse hook with matcher Agent, registered in settings.local.json (.claude/settings.local.json:339). It reads the hook payload from stdin, lowercases tool_input.subagent_type, and always allows the infrastructure types general-purpose, explore, plan, and bash (.claude/hooks/agent-dispatch-check.py:79, .claude/hooks/agent-dispatch-check.py:309). For a named specialist it first runs the advisory-only Step-11 competence gate, which may print a stderr warning and append a competence_gate_decision trace to governance-log.jsonl but is structurally incapable of denying (.claude/hooks/agent-dispatch-check.py:117).

It then tail-reads up to 200 KB of the transcript, finds the last valid classification block, and extracts the MUST DISPATCH names against the generated known-names set (.claude/hooks/agent-dispatch-check.py:21, .claude/hooks/agent-dispatch-check.py:335). No extracted names means allow (.claude/hooks/agent-dispatch-check.py:376). A guarded downstream research agent dispatched without process-research in MUST DISPATCH draws a non-blocking warn_research_direct stderr advisory and a log event (.claude/hooks/agent-dispatch-check.py:386).

Declared names are expanded through skill-agent aliases; an off-list agent is still allowed via the registry exemption when a process-* routing skill is declared, and otherwise gets a stderr "AGENT DISPATCH (advisory)" warning plus a warn event. Every code path ends in an allow, and each outcome is emitted to governance-log.jsonl as an agent_dispatched event (.claude/hooks/agent-dispatch-check.py:407, .claude/hooks/agent-dispatch-check.py:62).
<!-- PROSE:END -->
