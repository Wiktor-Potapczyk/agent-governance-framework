---
component: "process-analysis"
kind: "skill"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# skill: process-analysis

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/skills/process-analysis`
- **Provenance:** authored-in-harness
- **Reachability:** `EVD-003` (.claude/workflows/process-analysis.js), `EVD-004` (.claude/registry.json)
- **Usage:** Recorded use count 0 (source: `governance-log.jsonl:agent_dispatched.skill_context[]`).
- **Edges:**
  - inbound mentioned_in_prose CLAUDE.md [unresolved: prose mention only]
  - inbound invokes process-analysis
  - inbound mentioned_in_prose process-build [unresolved: prose mention only]
  - inbound mentioned_in_prose process-postmortem [unresolved: prose mention only]
  - inbound mentioned_in_prose process-research [unresolved: prose mention only]
  - inbound cataloged_in registry.json
  - inbound mentioned_in_prose task-classifier [unresolved: prose mention only]
  - outbound dispatches adversarial-reviewer
  - outbound dispatches api-designer
  - outbound dispatches api-security-audit
  - outbound dispatches architect-reviewer
  - outbound mentions_in_prose bias-guard [unresolved: prose mention only]
  - outbound mentions_in_prose content-marketer [unresolved: prose mention only]
  - outbound dispatches data-engineer
  - outbound dispatches debugger
  - outbound dispatches n8n-workflow-architect
  - outbound mentions_in_prose process-build [unresolved: prose mention only]
  - outbound mentions_in_prose process-planning [unresolved: prose mention only]
  - outbound mentions_in_prose process-research [unresolved: prose mention only]
  - outbound dispatches prompt-engineer
  - outbound dispatches report-generator
  - outbound dispatches research-synthesizer
  - outbound mentions_in_prose save [unresolved: prose mention only]
  - outbound mentions_in_prose task-classifier [unresolved: prose mention only]
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Analysis process template. Follow this procedure for all Analysis-type tasks after task-classifier routes here. Covers evaluation, investigation, diagnosis, and reasoning about causes or behavior. Use-when: Task-classifier returned `TASK TYPE: Analysis`

(machine-filled from rationale-index.json; extraction locus: frontmatter)

## How

Entered when task-classifier returns TASK TYPE: Analysis (.claude/skills/process-analysis/SKILL.md:26). For non-Quick tasks the procedure is workflow-enforced: call the Workflow tool with scriptPath .claude/workflows/process-analysis.js and the task brief as args; the prose steps are the spec of record and the explicit fallback when the Workflow tool is unavailable (.claude/skills/process-analysis/SKILL.md:10, :14).

The script drives Agent-tool dispatches: one specialist per subject from the Step 2 table (prompt-engineer, architect-reviewer, debugger, api-designer, data-engineer, n8n-workflow-architect, api-security-audit) (.claude/skills/process-analysis/SKILL.md:65), research-synthesizer mandatory whenever 2 or more specialists ran (.claude/skills/process-analysis/SKILL.md:86), and report-generator for complex multi-agent output (.claude/skills/process-analysis/SKILL.md:96). Decomposition mode HALTs and hands the numbered sub-task list back, because a workflow cannot invoke skills (.claude/skills/process-analysis/SKILL.md:12).

Required output: the ANALYSIS SCOPE block before any work (.claude/skills/process-analysis/SKILL.md:49) and an assessment passing the Step 5 checklist, saved to the scoped path (.claude/skills/process-analysis/SKILL.md:100). Enforcement: skipped synthesis is a process violation caught by the Stop hook (.claude/skills/process-analysis/SKILL.md:86), the bias-guard hook blocks agent prompts carrying hypotheses (.claude/skills/process-analysis/SKILL.md:42), and DISPATCHES.json stays the read-only H11 verification source (.claude/skills/process-analysis/SKILL.md:14).
<!-- PROSE:END -->
