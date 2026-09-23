---
component: "n8n-review"
kind: "skill"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# skill: n8n-review

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/skills/n8n-review`
- **Provenance:** authored-in-harness
- **Reachability:** `EVD-004` (.claude/registry.json)
- **Usage:** Recorded use count 0 (source: `governance-log.jsonl:agent_dispatched.skill_context[]`).
- **Edges:**
  - inbound mentioned_in_prose CLAUDE.md [unresolved: prose mention only]
  - inbound mentioned_in_prose n8n-patterns [unresolved: prose mention only]
  - inbound cataloged_in registry.json
  - inbound mentioned_in_prose review-queue [unresolved: prose mention only]
  - outbound mentions_in_prose debugger [unresolved: prose mention only]
  - outbound mentions_in_prose n8n-review-worker [unresolved: prose mention only]
  - outbound mentions_in_prose n8n-workflow-architect [unresolved: prose mention only]
  - outbound mentions_in_prose n8n-workflow-builder [unresolved: prose mention only]
  - outbound mentions_in_prose save [unresolved: prose mention only]
  - outbound mentions_in_prose verify [unresolved: prose mention only]
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Review n8n workflows against team quality guidelines. Validates naming, visual chain, sticky notes, execution data, error handling, security, and credentials. Use when a user wants to audit, review, or check an n8n workflow for quality and compliance.

(machine-filled from rationale-index.json; extraction locus: frontmatter)

## How

Invoked via the Skill tool on audit, review, check, or validate requests for an n8n workflow (.claude/skills/n8n-review/SKILL.md:12); rename and documentation asks route to n8n-reviewer, and build asks route to the architect/builder pair (.claude/skills/n8n-review/SKILL.md:18).

Tool surface: n8n_get_workflow with full=true, never a stale JSON dump (.claude/skills/n8n-review/SKILL.md:43), n8n_list_workflows for name lookups (.claude/skills/n8n-review/SKILL.md:44), a claude-in-chrome screenshot taken before dispatch so the visual-chain and sticky-note sections are graded by looking, not from coordinates (.claude/skills/n8n-review/SKILL.md:27), and one Sonnet Agent-tool dispatch carrying the complete workflow JSON plus the complete guidelines text, untruncated (.claude/skills/n8n-review/SKILL.md:55, :60).

It must produce a findings report in the fixed template with mandatory Pre-Analysis counts in the header (.claude/skills/n8n-review/SKILL.md:77), saved to Projects/n8n-guidelines/reviews/{workflow-name}-{YYYY-MM-DD}.md (.claude/skills/n8n-review/SKILL.md:113). It is report-only and never modifies the workflow (.claude/skills/n8n-review/SKILL.md:209); if the visual check did not happen, the report must say so rather than score those sections from JSON (.claude/skills/n8n-review/SKILL.md:27).
<!-- PROSE:END -->
