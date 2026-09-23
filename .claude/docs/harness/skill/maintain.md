---
component: "maintain"
kind: "skill"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# skill: maintain

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/skills/maintain`
- **Provenance:** authored-in-harness
- **Reachability:** `EVD-004` (.claude/registry.json)
- **Usage:** Recorded use count 0 (source: `governance-log.jsonl:agent_dispatched.skill_context[]`).
- **Edges:**
  - inbound mentioned_in_prose CLAUDE.md [unresolved: prose mention only]
  - inbound mentioned_in_prose doc-consistency [unresolved: prose mention only]
  - inbound cataloged_in registry.json
  - inbound mentioned_in_prose repo-sync [unresolved: prose mention only]
  - inbound mentioned_in_prose save [unresolved: prose mention only]
  - inbound mentioned_in_prose vault-maintain [unresolved: prose mention only]
  - outbound mentions_in_prose vault-maintain [unresolved: prose mention only]
  - outbound mentions_in_prose verify [unresolved: prose mention only]
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Clean up and organize a project's work files. Inventories work/ directory, reads each file to classify it (keep/archive/merge), executes moves, and updates STATE.md. Use when the user says "maintain", "clean up files", "organize work directory", "archive stale files", "file maintenance", or after a major project milestone when files have accumulated. Also trigger when the user says "/maintain" or 

(machine-filled from rationale-index.json; extraction locus: frontmatter)

## How

Invoked via the Skill tool on /maintain, "clean up files", and the other file-maintenance phrasings, scoped to one project's work/ directory; vault-wide passes route to /vault-maintain instead (.claude/skills/maintain/SKILL.md:12, :18).

The main session reads only the project's STATE.md (.claude/skills/maintain/SKILL.md:31), then spawns one Agent-tool dispatch with subagent_type "general-purpose" carrying the full classification rule set; reading work files inline is forbidden because it trashes main-session context (.claude/skills/maintain/SKILL.md:8, :36).

The dispatched agent must present a KEEP/ARCHIVE/MERGE/DELETE classification table (.claude/skills/maintain/SKILL.md:58), execute moves with no unconfirmed deletes (.claude/skills/maintain/SKILL.md:77), update STATE.md's Work Files section (.claude/skills/maintain/SKILL.md:79), and report kept/archived/merged counts (.claude/skills/maintain/SKILL.md:81). Enforcement is procedural: the main session reviews the summary, discusses questionable calls with the user, and does not re-read the files to verify (.claude/skills/maintain/SKILL.md:88).
<!-- PROSE:END -->
