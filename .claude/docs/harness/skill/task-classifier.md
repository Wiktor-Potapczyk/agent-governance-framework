---
component: "task-classifier"
kind: "skill"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# skill: task-classifier

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/skills/task-classifier`
- **Provenance:** authored-in-harness
- **Reachability:** `EVD-004` (.claude/registry.json)
- **Usage:** Recorded use count 0 (source: `governance-log.jsonl:agent_dispatched.skill_context[]`).
- **Edges:**
  - inbound mentioned_in_prose CLAUDE.md [unresolved: prose mention only]
  - inbound mentioned_in_prose ensemble [unresolved: prose mention only]
  - inbound mentioned_in_prose process-analysis [unresolved: prose mention only]
  - inbound mentioned_in_prose process-build [unresolved: prose mention only]
  - inbound mentioned_in_prose process-planning [unresolved: prose mention only]
  - inbound mentioned_in_prose process-qa [unresolved: prose mention only]
  - inbound mentioned_in_prose process-research [unresolved: prose mention only]
  - inbound cataloged_in registry.json
  - inbound mentioned_in_prose verify [unresolved: prose mention only]
  - outbound mentions_in_prose adversarial-reviewer [unresolved: prose mention only]
  - outbound mentions_in_prose api-designer [unresolved: prose mention only]
  - outbound mentions_in_prose api-security-audit [unresolved: prose mention only]
  - outbound mentions_in_prose architect-loop [unresolved: prose mention only]
  - outbound mentions_in_prose architect-reviewer [unresolved: prose mention only]
  - outbound mentions_in_prose bash-safety-guard [unresolved: prose mention only]
  - outbound mentions_in_prose blueprint [unresolved: prose mention only]
  - outbound mentions_in_prose blueprint-mode [unresolved: prose mention only]
  - outbound mentions_in_prose checkpoint [unresolved: prose mention only]
  - outbound mentions_in_prose classifier-field-check [unresolved: prose mention only]
  - outbound mentions_in_prose competitive-analyst [unresolved: prose mention only]
  - outbound mentions_in_prose content-marketer [unresolved: prose mention only]
  - outbound mentions_in_prose ensemble [unresolved: prose mention only]
  - outbound mentions_in_prose impeccable [unresolved: prose mention only]
  - outbound mentions_in_prose implementation-plan [unresolved: prose mention only]
  - outbound mentions_in_prose llm-architect [unresolved: prose mention only]
  - outbound mentions_in_prose mcp-developer [unresolved: prose mention only]
  - outbound mentions_in_prose mcp-irreversible-guard [unresolved: prose mention only]
  - outbound mentions_in_prose mcp-server-architect [unresolved: prose mention only]
  - outbound mentions_in_prose n8n-workflow-architect [unresolved: prose mention only]
  - outbound mentions_in_prose n8n-workflow-builder [unresolved: prose mention only]
  - outbound mentions_in_prose nosql-specialist [unresolved: prose mention only]
  - outbound mentions_in_prose pm [unresolved: prose mention only]
  - outbound mentions_in_prose pm-orchestrator [unresolved: prose mention only]
  - outbound mentions_in_prose postgres-pro [unresolved: prose mention only]
  - outbound mentions_in_prose powershell-7-expert [unresolved: prose mention only]
  - outbound mentions_in_prose process-analysis [unresolved: prose mention only]
  - outbound mentions_in_prose process-build [unresolved: prose mention only]
  - outbound mentions_in_prose process-pentest [unresolved: prose mention only]
  - outbound mentions_in_prose process-planning [unresolved: prose mention only]
  - outbound mentions_in_prose process-qa [unresolved: prose mention only]
  - outbound mentions_in_prose process-research [unresolved: prose mention only]
  - outbound mentions_in_prose prompt-engineer [unresolved: prose mention only]
  - outbound mentions_in_prose research-analyst [unresolved: prose mention only]
  - outbound mentions_in_prose research-orchestrator [unresolved: prose mention only]
  - outbound mentions_in_prose technical-researcher [unresolved: prose mention only]
  - outbound mentions_in_prose verify [unresolved: prose mention only]
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Classify the current task before any work begins. Determines task type and recommended approach. Invoke at the start of every substantive task. Use-when: Start of every substantive task — runs before any other skill or agent dispatch

(machine-filled from rationale-index.json; extraction locus: frontmatter)

## How

The dispatch contract invokes it via the Skill tool at the start of every substantive task, before any other skill or agent dispatch, and again on scope change, blocker report, or pivot (`.claude/skills/task-classifier/SKILL.md:12-13`). It never runs from inside a process skill already executing classified work, which would loop (line 18).

It edits no files; its product is the rigid labeled-slot announcement block: IMPLIES, TASK TYPE, DOMAIN, REVERSIBILITY, DETECTABILITY, APPROACH, MISSED, MUST DISPATCH (`.claude/skills/task-classifier/SKILL.md:223-240`), with every slot mandatory as a written line even when the value is none or N/A (line 242). It then routes: the TYPE table sends non-Quick work to a process skill via the Skill tool with the classification block passed as args (lines 263-273), and Step 6 requires TaskCreate with a one-line `CHECK:` clause per step for multi-step increments (lines 299-301).

Enforcement: a missing labeled field is caught by the classifier-field hook and blocks the response (`.claude/skills/task-classifier/SKILL.md:221`, line 242); MUST DISPATCH is the enforcement contract the dispatch-compliance Stop hook verifies item by item (lines 25, 246); REVERSIBILITY and DETECTABILITY are advisory pre-warnings captured by `classifier-field-check.py`, while the hard stop remains the Gate-1 PreToolUse deny (line 221).
<!-- PROSE:END -->
