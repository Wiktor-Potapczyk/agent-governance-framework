---
component: "bias-guard"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: bias-guard

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/bias-guard.py`
- **Provenance:** authored-in-harness
- **Reachability:** `EVD-001` (.claude/settings.json)
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:**
  - inbound mentioned_in_prose process-analysis [unresolved: prose mention only]
  - inbound registered_in settings.json
  - outbound imports _governance_logger
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

SubagentStart hook: inject Blind Analysis Rule reminder into evaluator agents.

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

This SubagentStart hook (registered in settings.json with an empty matcher, so it runs for every subagent) parses the payload's agent_type field (.claude/hooks/bias-guard.py:13) and compares it against a fixed EVALUATORS list of seven evaluator agents such as architect-reviewer and adversarial-reviewer (.claude/hooks/bias-guard.py:35).

On a match it prints hookSpecificOutput.additionalContext carrying the Blind Analysis Rule notice into the starting agent's context; any other agent type gets an empty JSON object instead (.claude/hooks/bias-guard.py:45). Each path records its decision, "inject" or "skip" with the agent type, to hook-activity.jsonl via _governance_logger.log_fire, and the logger never raises (.claude/hooks/bias-guard.py:23).
<!-- PROSE:END -->
