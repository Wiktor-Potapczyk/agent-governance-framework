---
component: "verify"
kind: "skill"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# skill: verify

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/skills/verify`
- **Provenance:** authored-in-harness
- **Reachability:** `EVD-004` (.claude/registry.json)
- **Usage:** Recorded use count 0 (source: `governance-log.jsonl:agent_dispatched.skill_context[]`).
- **Edges:**
  - inbound mentioned_in_prose CLAUDE.md [unresolved: prose mention only]
  - inbound mentioned_in_prose architect-loop [unresolved: prose mention only]
  - inbound mentioned_in_prose db-migration-plan [unresolved: prose mention only]
  - inbound mentioned_in_prose ensemble [unresolved: prose mention only]
  - inbound mentioned_in_prose maintain [unresolved: prose mention only]
  - inbound mentioned_in_prose n8n-review [unresolved: prose mention only]
  - inbound mentioned_in_prose process-governance-mine [unresolved: prose mention only]
  - inbound mentioned_in_prose process-lint [unresolved: prose mention only]
  - inbound mentioned_in_prose process-planning [unresolved: prose mention only]
  - inbound mentioned_in_prose process-postmortem [unresolved: prose mention only]
  - inbound mentioned_in_prose process-query [unresolved: prose mention only]
  - inbound cataloged_in registry.json
  - inbound mentioned_in_prose repo-sync [unresolved: prose mention only]
  - inbound mentioned_in_prose review-queue [unresolved: prose mention only]
  - inbound mentioned_in_prose task-classifier [unresolved: prose mention only]
  - inbound mentioned_in_prose verification-gated-research [unresolved: prose mention only]
  - outbound mentions_in_prose ensemble [unresolved: prose mention only]
  - outbound mentions_in_prose task-classifier [unresolved: prose mention only]
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

CoVe-based step-level verification of reasoning. Invoke when asked to verify reasoning, when the user says "/verify" or "verify this", when task-classifier routes with MECHANISM CoVe, or when Claude identifies medium/low confidence in its own reasoning steps.

(machine-filled from rationale-index.json; extraction locus: frontmatter)

## How

Invoked via the Skill tool when the user says `/verify` or "verify this", when task-classifier routes with MECHANISM CoVe, or when medium or low confidence is identified in the model's own reasoning steps (`.claude/skills/verify/SKILL.md:3`, lines 10-13).

It uses no external tools: the mechanism is a fixed CoVe prompt applied to the preceding reasoning: rate each step's confidence, independently re-derive every medium or low step without referencing the original reasoning, flag contradictions, and propagate revisions to downstream steps (`.claude/skills/verify/SKILL.md:32-43`; the context-isolation requirement is line 24).

The contract: apply once per response, never re-run on its own output, and escalate to ensemble or external verification if still uncertain (`.claude/skills/verify/SKILL.md:45-47`). Output rules are strict: "No issues found." in one line when clean, one line per issue otherwise, and `[NEEDS RESEARCH]` for a claim depending on data it does not have (lines 49-53). No hook checks this skill's output; the one-round limit and the calibration gotchas are its own enforcement (lines 23-26).
<!-- PROSE:END -->
