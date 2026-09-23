---
component: "process-qa"
kind: "skill"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# skill: process-qa

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/skills/process-qa`
- **Provenance:** authored-in-harness
- **Reachability:** `EVD-003` (.claude/workflows/process-qa.js), `EVD-004` (.claude/registry.json)
- **Usage:** Recorded use count 0 (source: `governance-log.jsonl:agent_dispatched.skill_context[]`).
- **Edges:**
  - inbound mentioned_in_prose CLAUDE.md [unresolved: prose mention only]
  - inbound mentioned_in_prose process-build [unresolved: prose mention only]
  - inbound mentioned_in_prose process-governance-mine [unresolved: prose mention only]
  - inbound mentioned_in_prose process-lint [unresolved: prose mention only]
  - inbound mentioned_in_prose process-pentest [unresolved: prose mention only]
  - inbound mentioned_in_prose process-postmortem [unresolved: prose mention only]
  - inbound invokes process-qa
  - inbound cataloged_in registry.json
  - inbound mentioned_in_prose task-classifier [unresolved: prose mention only]
  - outbound mentions_in_prose _command_class [unresolved: prose mention only]
  - outbound mentions_in_prose architect-reviewer [unresolved: prose mention only]
  - outbound mentions_in_prose classifier-field-check [unresolved: prose mention only]
  - outbound mentions_in_prose process-lint [unresolved: prose mention only]
  - outbound mentions_in_prose process-pentest [unresolved: prose mention only]
  - outbound mentions_in_prose process-step-check [unresolved: prose mention only]
  - outbound mentions_in_prose task-classifier [unresolved: prose mention only]
  - outbound mentions_in_prose task-plan-auto-sync [unresolved: prose mention only]
  - outbound mentions_in_prose work-verification-check [unresolved: prose mention only]
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Minimal QA — verify claims empirically with real tool calls, report PASS/FAIL in a single compact block. Invoke when task-classifier marks QA compound yes. Use-when: A non-Quick task is complete and produced verifiable claims

(machine-filled from rationale-index.json; extraction locus: frontmatter)

## How

Invoked via the Skill tool whenever task-classifier marks the QA compound yes, which puts `process-qa` in MUST DISPATCH for every non-Quick task (`.claude/skills/process-qa/SKILL.md:3`). For a non-Quick task the prose is a thin invoker: it calls the Workflow tool with `.claude/workflows/process-qa.js` and an explicitly enumerated `claims` array; the script dispatches one execute-agent per claim and computes PASS/FAIL in code from typed evidence fields, never from agent self-report (line 10). The prose path is the spec of record and the fallback (line 16).

Execution requires real tools per claim type: Bash or MCP for code, hook, workflow, and API behavior; Read or Grep only for file-content claims; MCP queries for live system state (`.claude/skills/process-qa/SKILL.md:64-68`). Reading a script is not testing it; a claim that needed execution but only received Read/Grep auto-FAILs (line 70).

The contractual output is a QA SCOPE block and a QA REPORT with PASS, FAIL, and a mandatory Untested line, both emitted left-aligned as plain unfenced text (`.claude/skills/process-qa/SKILL.md:48-52`, 78-83). Two Stop hooks check it: `process-step-check.py` matches the literal block strings after fence-stripping, so a fenced block is invisible and blocks completion (lines 12, 22), and `work-verification-check` hard-blocks any QA REPORT filed with zero real tool calls (line 70).
<!-- PROSE:END -->
