---
component: "process-qa"
kind: "workflow"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# workflow: process-qa

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/workflows/process-qa.js`
- **Provenance:** authored-in-harness
- **Reachability:** `EVD-003` (.claude/workflows/process-qa.js)
- **Usage:** Instrumented, observed zero times: a telemetry path exists and has recorded no use yet; runs from before the identity plumbing landed are excluded from this count (sentinel `AWAITING_FIRST_OBSERVATION`). Note: workflow-identity plumbing landed 2026-09-01: zero means 'no identified completion observed since the plumbing', never 'idle'; pre-plumbing pass records carry no workflow identity and are counted only in the header's workflow_pass_unattributed
- **Edges:**
  - inbound mentioned_in_prose CLAUDE.md [unresolved: prose mention only]
  - inbound mentioned_in_prose process-build [unresolved: prose mention only]
  - inbound mentioned_in_prose process-governance-mine [unresolved: prose mention only]
  - inbound mentioned_in_prose process-lint [unresolved: prose mention only]
  - inbound mentioned_in_prose process-pentest [unresolved: prose mention only]
  - inbound mentioned_in_prose process-postmortem [unresolved: prose mention only]
  - inbound mentioned_in_prose task-classifier [unresolved: prose mention only]
  - outbound invokes process-qa
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Terminal execution-class workflow: scope -> per-claim execute-agents (each runs real Bash/MCP/Read and returns typed evidence) -> PASS/FAIL computed IN CODE from evidence fields (auto-FAIL if execution-class claim verified by Read/Grep only) -> QA SCOPE + QA REPORT text assembled in code for transcript relay. Args: {project, claims, source?, constraints?}.

(machine-filled from rationale-index.json; extraction locus: meta)

## How

A terminal execution-class workflow: given a project and a claims array, it verifies each claim with a real tool run and computes the verdict in code. It halts before spawning agents when project or a non-empty claims array is missing (.claude/workflows/process-qa.js:102). String claims are normalized to objects (.claude/workflows/process-qa.js:112), and a scope agent assigns each claim a class of execute, read, or mcp, under the rule that code or hook behavior is never a read-class claim (.claude/workflows/process-qa.js:142).

One agent per claim runs in parallel and must return the actual tool it used plus literal evidence output (.claude/workflows/process-qa.js:176). The script then overrides agent self-reports: an execute-class claim verified without Bash, PowerShell, or an MCP tool auto-fails (.claude/workflows/process-qa.js:228), a result without evidence auto-fails (.claude/workflows/process-qa.js:234), and a coverage rule pads any missing result as FAIL so N claims in always yield N results out (.claude/workflows/process-qa.js:249).

Pass, fail, and untested counts are derived in code (.claude/workflows/process-qa.js:264), and the workflow assembles qa_scope_text and qa_report_text as plain strings the main session must relay verbatim, because process-step-check.py matches those literal blocks in the transcript (.claude/workflows/process-qa.js:284).
<!-- PROSE:END -->
