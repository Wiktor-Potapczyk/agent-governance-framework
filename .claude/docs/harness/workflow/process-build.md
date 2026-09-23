---
component: "process-build"
kind: "workflow"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# workflow: process-build

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/workflows/process-build.js`
- **Provenance:** authored-in-harness
- **Reachability:** `EVD-003` (.claude/workflows/process-build.js)
- **Usage:** Instrumented, observed zero times: a telemetry path exists and has recorded no use yet; runs from before the identity plumbing landed are excluded from this count (sentinel `AWAITING_FIRST_OBSERVATION`). Note: workflow-identity plumbing landed 2026-09-01: zero means 'no identified completion observed since the plumbing', never 'idle'; pre-plumbing pass records carry no workflow identity and are counted only in the header's workflow_pass_unattributed
- **Edges:**
  - inbound mentioned_in_prose CLAUDE.md [unresolved: prose mention only]
  - inbound mentioned_in_prose ensemble [unresolved: prose mention only]
  - inbound mentioned_in_prose process-analysis [unresolved: prose mention only]
  - inbound mentioned_in_prose process-planning [unresolved: prose mention only]
  - inbound mentioned_in_prose task-classifier [unresolved: prose mention only]
  - outbound invokes adversarial-reviewer
  - outbound invokes architect-reviewer
  - outbound invokes process-build
  - outbound invokes prompt-engineer
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Deterministic encoding of the process-build procedure: scope -> implementation-plan (plan) -> blueprint-mode (build) -> mandatory parallel review (architect-reviewer + adversarial-reviewer [+ prompt-engineer if llm_prompts]) -> capped revise loop -> execution-evidence quality gate. Routing-as-code; agents work freely inside steps.

(machine-filled from rationale-index.json; extraction locus: meta)

## How

The script drives a six-phase build: Scope, Plan, Build, Review, Revise, Quality (.claude/workflows/process-build.js:12). It halts before spawning agents unless args carry a non-empty project and spec (.claude/workflows/process-build.js:149). The scope agent returns typed flags that gate routing: underspecified hands the task back to process-planning (.claude/workflows/process-build.js:189), and n8n_domain hands back to the Two-Phase Orchestration path rather than re-encoding it here (.claude/workflows/process-build.js:195).

implementation-plan writes the plan file under a non-negotiable file contract (.claude/workflows/process-build.js:207). A fabrication guard then verifies that every input file the plan cites exists on disk and halts before build if any is a ghost (.claude/workflows/process-build.js:244). blueprint-mode implements to the exact scoped artifact path and must verify the write before returning (.claude/workflows/process-build.js:252).

Review always runs architect-reviewer and adversarial-reviewer in parallel, adding prompt-engineer when the artifact carries LLM prompts (.claude/workflows/process-build.js:326). When the two mandatory reviewers land on opposite sides of the ship line, the classifyDivergence helper escalates with both verdicts instead of converging (.claude/workflows/process-build.js:92, .claude/workflows/process-build.js:355). Blocking issues route back to blueprint-mode for at most two revise rounds (.claude/workflows/process-build.js:284). The final quality verdict is derived in code from three evidence booleans, never from the gate agent's self-report (.claude/workflows/process-build.js:410).
<!-- PROSE:END -->
