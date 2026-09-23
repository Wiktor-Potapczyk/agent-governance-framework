---
component: "doc-consistency"
kind: "skill"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# skill: doc-consistency

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/skills/doc-consistency`
- **Provenance:** authored-in-harness
- **Reachability:** `EVD-004` (.claude/registry.json)
- **Usage:** Recorded use count 0 (source: `governance-log.jsonl:agent_dispatched.skill_context[]`).
- **Edges:**
  - inbound mentioned_in_prose process-governance-mine [unresolved: prose mention only]
  - inbound cataloged_in registry.json
  - inbound mentioned_in_prose repo-sync [unresolved: prose mention only]
  - outbound mentions_in_prose content-marketer [unresolved: prose mention only]
  - outbound mentions_in_prose index [unresolved: prose mention only]
  - outbound mentions_in_prose maintain [unresolved: prose mention only]
  - outbound mentions_in_prose prose-slop-check [unresolved: prose mention only]
  - outbound mentions_in_prose save [unresolved: prose mention only]
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Use when maintaining a documentation set — after a code/config change that any doc describes, before publishing a repo, or whenever asked to "update the docs" / "keep docs in sync" / "maintain the documentation". Catches the failure where one doc is updated and a sibling is left stale, shipping an internal contradiction (e.g. README says "87 agents", architecture.md says "51", the real on-disk cou

(machine-filled from rationale-index.json; extraction locus: frontmatter)

## How

A Skill-tool invocation fires this on doc-set maintenance: after a code or config change that any doc describes, before publishing a repo, or on "update the docs" phrasing (.claude/skills/doc-consistency/SKILL.md:16). Step 1 is a hard gate: no doc may be read, checked, or edited until a DOC-SET SCOPE block enumerates the complete doc set from the globs, never just the diff-adjacent file (.claude/skills/doc-consistency/SKILL.md:41).

Its tool surface is the enumeration globs (README*, CHANGELOG*, architecture, docs/**, CLAUDE.md) (.claude/skills/doc-consistency/SKILL.md:48), Bash to run the stdlib-only checker `python .claude/skills/doc-consistency/check_doc_consistency.py <manifest>` (.claude/skills/doc-consistency/SKILL.md:81), and Edit only after fixes are approved, unless the invocation was an explicit fix mandate (.claude/skills/doc-consistency/SKILL.md:94).

It must produce the `.doc-consistency.json` manifest mapping each cross-referenced value to an authoritative source (.claude/skills/doc-consistency/SKILL.md:54), a deterministic pre-check run (the checker prints [OK]/[MISMATCH]/[ERROR] and exits 0 only when every doc's claimed value matches, .claude/skills/doc-consistency/SKILL.md:84), and a semantic reconciliation report naming which docs were reconciled and which were left untouched (.claude/skills/doc-consistency/SKILL.md:94). The checker's exit code is the mechanical check on its output; the Step 5 checklist is the procedural one (.claude/skills/doc-consistency/SKILL.md:100).
<!-- PROSE:END -->
