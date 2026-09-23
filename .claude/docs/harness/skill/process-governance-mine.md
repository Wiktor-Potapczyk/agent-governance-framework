---
component: "process-governance-mine"
kind: "skill"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# skill: process-governance-mine

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/skills/process-governance-mine`
- **Provenance:** authored-in-harness
- **Reachability:** `EVD-004` (.claude/registry.json)
- **Usage:** Recorded use count 0 (source: `governance-log.jsonl:agent_dispatched.skill_context[]`).
- **Edges:**
  - inbound mentioned_in_prose CLAUDE.md [unresolved: prose mention only]
  - inbound cataloged_in registry.json
  - outbound mentions_in_prose _irreversible_surface [unresolved: prose mention only]
  - outbound mentions_in_prose agent-dispatch-check [unresolved: prose mention only]
  - outbound mentions_in_prose doc-consistency [unresolved: prose mention only]
  - outbound mentions_in_prose ensemble [unresolved: prose mention only]
  - outbound mentions_in_prose governance-log [unresolved: prose mention only]
  - outbound mentions_in_prose governance-log.jsonl [unresolved: prose mention only]
  - outbound mentions_in_prose hook-write-regression-gate [unresolved: prose mention only]
  - outbound mentions_in_prose lint-cadence-trigger [unresolved: prose mention only]
  - outbound mentions_in_prose mine_governance [unresolved: prose mention only]
  - outbound mentions_in_prose n8n-patterns [unresolved: prose mention only]
  - outbound mentions_in_prose process-lint [unresolved: prose mention only]
  - outbound mentions_in_prose process-qa [unresolved: prose mention only]
  - outbound mentions_in_prose reviewer-scope-violation-check [unresolved: prose mention only]
  - outbound mentions_in_prose verify [unresolved: prose mention only]
  - outbound mentions_in_prose work-verification-check [unresolved: prose mention only]
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Weekly skill that mines governance-log.jsonl for recurring failure patterns and emits a proposal artifact. Read-only except for one output file. Complements /hookify (reactive) with a retrospective/aggregate view. Use-when: User says `/process-governance-mine` or "run governance mine" or "what recurring failures are in the log?"

(machine-filled from rationale-index.json; extraction locus: frontmatter)

## How

Invoked via the Skill tool on /process-governance-mine, or when the weekly cadence reminder from lint-cadence-trigger.py fires at SessionStart (.claude/skills/process-governance-mine/SKILL.md:23). Its hard invariant is proposal-only: the complete write set is one dated proposal file plus its cadence timestamp; any other write is unauthorized and hook-blocked (.claude/skills/process-governance-mine/SKILL.md:10, :15).

Tool surface: Bash running python .claude/hooks/mine_governance.py, or importing mine() programmatically (.claude/skills/process-governance-mine/SKILL.md:51, :63), a glob over prior proposal files to compute surfaced_count (.claude/skills/process-governance-mine/SKILL.md:83), mine_warns() for the warn-tier section (.claude/skills/process-governance-mine/SKILL.md:148), and Write for the two permitted files only.

It must emit per-sig proposal blocks in the exact schema (.claude/skills/process-governance-mine/SKILL.md:119), the warn-tier candidates section carrying its fixed proposal-only footer on every block (.claude/skills/process-governance-mine/SKILL.md:182), a one-line summary to Wiktor (.claude/skills/process-governance-mine/SKILL.md:194), and the cadence state file that suppresses the next reminder (.claude/skills/process-governance-mine/SKILL.md:201). The write-boundary hooks are the enforcement; no organ auto-applies its proposals, and the Gate-1 deny surface is out of scope by construction (.claude/skills/process-governance-mine/SKILL.md:179).
<!-- PROSE:END -->
