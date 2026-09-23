---
component: "process-analysis"
kind: "workflow"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# workflow: process-analysis

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/workflows/process-analysis.js`
- **Provenance:** authored-in-harness
- **Reachability:** `EVD-003` (.claude/workflows/process-analysis.js)
- **Usage:** Instrumented, observed zero times: a telemetry path exists and has recorded no use yet; runs from before the identity plumbing landed are excluded from this count (sentinel `AWAITING_FIRST_OBSERVATION`). Note: workflow-identity plumbing landed 2026-09-01: zero means 'no identified completion observed since the plumbing', never 'idle'; pre-plumbing pass records carry no workflow identity and are counted only in the header's workflow_pass_unattributed
- **Edges:**
  - inbound mentioned_in_prose CLAUDE.md [unresolved: prose mention only]
  - inbound mentioned_in_prose process-build [unresolved: prose mention only]
  - inbound mentioned_in_prose process-postmortem [unresolved: prose mention only]
  - inbound mentioned_in_prose process-research [unresolved: prose mention only]
  - inbound mentioned_in_prose task-classifier [unresolved: prose mention only]
  - outbound invokes adversarial-reviewer
  - outbound invokes api-designer
  - outbound invokes api-security-audit
  - outbound invokes architect-reviewer
  - outbound invokes data-engineer
  - outbound invokes debugger
  - outbound invokes n8n-workflow-architect
  - outbound invokes process-analysis
  - outbound invokes prompt-engineer
  - outbound invokes report-generator
  - outbound invokes research-synthesizer
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Deterministic encoding of the process-analysis procedure (Evaluation + Investigation modes). Decomposition mode HALTs-and-hands-back — it invokes other process skills, which a workflow cannot do. Scope -> mode branch -> specialist fan-out -> synthesis (research-synthesizer, mandatory if 2+ specialists, enforced in code) -> report (conditional on complex flag) -> quality gate. Routing-as-code; agents work freely inside steps.

(machine-filled from rationale-index.json; extraction locus: meta)

## How

The script is a routing-as-code procedure: the code fixes the dispatch sequence and agents reason freely inside each step. It refuses to spawn anything until args arrive as a JSON object with a non-empty project and subject (.claude/workflows/process-analysis.js:111). A scope agent then reads project state and returns a typed object holding the ANALYSIS SCOPE block, the mode (evaluation, investigation, or decomposition), the specialist list, the rubric, a complex flag, and the output path (.claude/workflows/process-analysis.js:34). Decomposition mode never proceeds: the workflow returns the sub-task list to the main session, because a workflow cannot invoke other process skills (.claude/workflows/process-analysis.js:155).

Execution fans out from the scope. Each listed specialist is dispatched in parallel with the scope block and rubric as its prompt (.claude/workflows/process-analysis.js:184). Every prompt starts with the literal first line WORKFLOW-ID: process-analysis, which lets the SubagentStop observer attribute completions to this workflow (.claude/workflows/process-analysis.js:27). When two or more specialists return, a research-synthesizer pass is mandatory; the threshold is checked in code from the result count, not left to agent judgment (.claude/workflows/process-analysis.js:215).

Output lands on disk either via report-generator when the complex flag is set (.claude/workflows/process-analysis.js:241) or via a plain writing agent for the simple case (.claude/workflows/process-analysis.js:266). A final quality agent re-reads the file, and the workflow derives pass or fail in code from its three evidence booleans, ignoring the agent's own pass field (.claude/workflows/process-analysis.js:304).
<!-- PROSE:END -->
