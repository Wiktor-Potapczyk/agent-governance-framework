---
component: "ensemble"
kind: "skill"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# skill: ensemble

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/skills/ensemble`
- **Provenance:** authored-in-harness
- **Reachability:** `EVD-004` (.claude/registry.json)
- **Usage:** Recorded use count 0 (source: `governance-log.jsonl:agent_dispatched.skill_context[]`).
- **Edges:**
  - inbound mentioned_in_prose process-governance-mine [unresolved: prose mention only]
  - inbound cataloged_in registry.json
  - inbound mentioned_in_prose task-classifier [unresolved: prose mention only]
  - inbound mentioned_in_prose verify [unresolved: prose mention only]
  - outbound mentions_in_prose process-build [unresolved: prose mention only]
  - outbound mentions_in_prose save [unresolved: prose mention only]
  - outbound mentions_in_prose task-classifier [unresolved: prose mention only]
  - outbound mentions_in_prose verify [unresolved: prose mention only]
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Run 4 parallel agents with different thinking lenses on a framing/design question. Produces a divergence map showing where lenses agree and disagree. Use when task-classifier outputs MECHANISM Ensemble, user says "/ensemble", or a design/architecture decision needs multiple perspectives. NOT for reasoning tasks (use /verify), NOT for Quick tasks.

(machine-filled from rationale-index.json; extraction locus: frontmatter)

## How

Invoked via the Skill tool when the user says /ensemble, when task-classifier outputs MECHANISM: Ensemble, or when a framing or design question needs multiple perspectives (.claude/skills/ensemble/SKILL.md:12). It refuses Quick tasks, and reasoning tasks route to /verify instead (.claude/skills/ensemble/SKILL.md:19).

Tool surface: the Agent tool, spawning all 4 lens agents (reframing, decomposition, stakeholder, adversarial) in a single message so they run in parallel (.claude/skills/ensemble/SKILL.md:33), and AskUserQuestion for the mandatory Step 1.5 approval of the de-biased question before any dispatch (.claude/skills/ensemble/SKILL.md:52).

It must produce the divergence-map block (one-line position per lens, DIVERGENCE, CONVERGENCE, SHARPEST INSIGHT) (.claude/skills/ensemble/SKILL.md:82) plus a GROUNDING CHECK section flagging each consequential claim as SUPPORTED, CONTRADICTED, UNGROUNDED, or NEEDS RESEARCH (.claude/skills/ensemble/SKILL.md:107). Enforcement is in-skill: the user-approval gate and the fixed output format; full agent outputs stay on demand only (.claude/skills/ensemble/SKILL.md:111).
<!-- PROSE:END -->
