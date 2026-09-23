---
component: "process-research"
kind: "workflow"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# workflow: process-research

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/workflows/process-research.js`
- **Provenance:** authored-in-harness
- **Reachability:** `EVD-003` (.claude/workflows/process-research.js)
- **Usage:** Instrumented, observed zero times: a telemetry path exists and has recorded no use yet; runs from before the identity plumbing landed are excluded from this count (sentinel `AWAITING_FIRST_OBSERVATION`). Note: workflow-identity plumbing landed 2026-09-01: zero means 'no identified completion observed since the plumbing', never 'idle'; pre-plumbing pass records carry no workflow identity and are counted only in the header's workflow_pass_unattributed
- **Edges:**
  - inbound mentioned_in_prose CLAUDE.md [unresolved: prose mention only]
  - inbound mentioned_in_prose process-analysis [unresolved: prose mention only]
  - inbound mentioned_in_prose process-planning [unresolved: prose mention only]
  - inbound mentioned_in_prose task-classifier [unresolved: prose mention only]
  - inbound mentioned_in_prose verification-gated-research [unresolved: prose mention only]
  - outbound invokes process-research
  - outbound invokes report-generator
  - outbound invokes research-analyst
  - outbound invokes research-orchestrator
  - outbound invokes research-synthesizer
  - outbound invokes technical-researcher
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Deterministic encoding of the process-research procedure (direct path 3B only): scope -> route (research-analyst / technical-researcher / research-orchestrator based on coverage flag) -> synthesis (research-synthesizer, mandatory if 2+ gatherers, enforced in code) -> report-generator (mandatory) -> quality gate. Ralph Loop path (3A) HALTs-and-hands-back to the main session — workflows cannot invoke the architect-loop skill. Routing-as-code; agents work freely inside steps.

(machine-filled from rationale-index.json; extraction locus: meta)

## How

The script encodes the direct research path only: scope, routed gathering, synthesis, mandatory report, quality gate (.claude/workflows/process-research.js:12). It halts on a missing project or question (.claude/workflows/process-research.js:130). The scope agent classifies a coverage flag and a ralph_loop_indicated flag; when the latter is true the workflow hands back to the main session, because a workflow cannot invoke the architect-loop skill (.claude/workflows/process-research.js:171).

Routing follows the coverage flag: orchestrated scopes go to research-orchestrator alone, otherwise research-analyst and technical-researcher dispatch per coverage, in parallel when both are needed (.claude/workflows/process-research.js:201). When the scope flags live_verification_required, a live-verification mandate is injected into every gatherer prompt requiring resolvable URLs for existence and frontier claims; otherwise the mandate is the empty string, a strict no-op (.claude/workflows/process-research.js:193). Synthesis via research-synthesizer is mandatory at two or more gatherers, enforced from the result count in code (.claude/workflows/process-research.js:254).

report-generator always runs and must write the report to the exact scoped path under a write-and-verify file contract (.claude/workflows/process-research.js:288). The final gate combines the quality agent's evidence booleans with a pure live-citation helper evaluated from the authoritative scope flag, so a gate agent that drops the echo cannot disable it; the pass is derived in code (.claude/workflows/process-research.js:33, .claude/workflows/process-research.js:331).
<!-- PROSE:END -->
