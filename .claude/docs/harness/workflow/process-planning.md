---
component: "process-planning"
kind: "workflow"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# workflow: process-planning

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/workflows/process-planning.js`
- **Provenance:** authored-in-harness
- **Reachability:** `EVD-003` (.claude/workflows/process-planning.js)
- **Usage:** Instrumented, observed zero times: a telemetry path exists and has recorded no use yet; runs from before the identity plumbing landed are excluded from this count (sentinel `AWAITING_FIRST_OBSERVATION`). Note: workflow-identity plumbing landed 2026-09-01: zero means 'no identified completion observed since the plumbing', never 'idle'; pre-plumbing pass records carry no workflow identity and are counted only in the header's workflow_pass_unattributed
- **Edges:**
  - inbound mentioned_in_prose CLAUDE.md [unresolved: prose mention only]
  - inbound mentioned_in_prose process-analysis [unresolved: prose mention only]
  - inbound mentioned_in_prose process-build [unresolved: prose mention only]
  - inbound mentioned_in_prose process-research [unresolved: prose mention only]
  - inbound mentioned_in_prose task-classifier [unresolved: prose mention only]
  - outbound invokes adversarial-reviewer
  - outbound invokes architect-reviewer
  - outbound invokes process-planning
  - outbound invokes prompt-engineer
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Deterministic encoding of the process-planning procedure: scope+classify -> (research gate) -> design (implementation-plan) -> mandatory parallel review (architect + adversarial [+ prompt-engineer]) -> capped revise loop -> execution-evidence quality gate. Routing-as-code; agents work freely inside steps.

(machine-filled from rationale-index.json; extraction locus: meta)

## How

The script fixes the dispatch order of the planning procedure: scope, design, parallel review, capped revise, quality gate (.claude/workflows/process-planning.js:12). It halts on malformed args before any agent spawns (.claude/workflows/process-planning.js:153). The scope agent returns typed judgment flags; when research_needed is true and the caller supplied no researchFindings, the research gate halts and hands back, because a workflow cannot invoke the process-research skill (.claude/workflows/process-planning.js:163).

implementation-plan writes the plan to the exact output path extracted from the scope block, under a write-and-verify file contract (.claude/workflows/process-planning.js:217, .claude/workflows/process-planning.js:231). Review always dispatches architect-reviewer and adversarial-reviewer, adding prompt-engineer when the plan involves LLM prompts (.claude/workflows/process-planning.js:290). An empty verdict set counts as review failure, not convergence (.claude/workflows/process-planning.js:307), and the classifyDivergence helper escalates to Wiktor with both verdicts when the two mandatory reviewers disagree across the ship line (.claude/workflows/process-planning.js:80, .claude/workflows/process-planning.js:320). Blocking issues loop back to the designer for at most two rounds (.claude/workflows/process-planning.js:249).

The quality agent re-reads the plan file and reports five evidence booleans; the workflow derives the final pass in code from those sub-fields and ignores the agent's own pass claim (.claude/workflows/process-planning.js:378).
<!-- PROSE:END -->
