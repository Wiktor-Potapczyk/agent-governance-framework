---
component: "process-step-check"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: process-step-check

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/process-step-check.py`
- **Provenance:** authored-in-harness
- **Reachability:** none recorded; blocked: `BLK-001`
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:**
  - inbound mentioned_in_prose process-qa [unresolved: prose mention only]
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Process Step Check - Stop Hook
L1 exit gate: verifies process skill steps were actually followed.
Complements skill-step-reminder (soft PostToolUse) with hard enforcement.

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

Fires on Stop (registered in `.claude/settings.local.json` with an empty matcher; the Usage line above records zero fires through the activity log, and this hook logs through `governance-log.jsonl` instead). It reads the last 200KB of the transcript (`.claude/hooks/process-step-check.py:25`), finds the most recent process invocation via either a Skill tool_use or a Workflow tool_use whose name or scriptPath maps to a process skill (`.claude/hooks/process-step-check.py:493`), and collects the text and Agent dispatches after it. Only a real user message resets that state; tool_result wrapper entries do not (`.claude/hooks/process-step-check.py:459`).

Hard failures print a JSON block decision: a missing SCOPE block for the invoked skill (`.claude/hooks/process-step-check.py:43`), a missing QA REPORT with PASS or FAIL for process-qa (`.claude/hooks/process-step-check.py:54`), a missing PENTEST REPORT (`.claude/hooks/process-step-check.py:68`), an inline PM CHECKPOINT REPORT with no pm-orchestrator Agent dispatch (`.claude/hooks/process-step-check.py:141`), and a completed multi-step increment (2+ TaskCreate, all completed, pentest seen) with no /pm invocation (`.claude/hooks/process-step-check.py:187`). Soft findings (no synthesizer after 2+ agents, no architect-reviewer for build or planning, zero dispatches) only log (`.claude/hooks/process-step-check.py:610`). The block message names the failed steps (`.claude/hooks/process-step-check.py:645`).

It also runs an advisory observation pass over a larger 4MB window: it counts `CHECK:` clauses on TaskCreate descriptions, classifies each clause, flags weak ones, and emits a `step_check_observation` event stamped with whether the window truncated (`.claude/hooks/process-step-check.py:281`, `.claude/hooks/process-step-check.py:314`). Every verdict lands in `governance-log.jsonl` as block, warn, or pass (`.claude/hooks/process-step-check.py:625`).
<!-- PROSE:END -->
