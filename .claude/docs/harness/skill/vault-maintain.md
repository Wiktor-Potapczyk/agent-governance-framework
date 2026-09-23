---
component: "vault-maintain"
kind: "skill"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# skill: vault-maintain

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/skills/vault-maintain`
- **Provenance:** authored-in-harness
- **Reachability:** `EVD-004` (.claude/registry.json)
- **Usage:** Recorded use count 0 (source: `governance-log.jsonl:agent_dispatched.skill_context[]`).
- **Edges:**
  - inbound mentioned_in_prose maintain [unresolved: prose mention only]
  - inbound cataloged_in registry.json
  - outbound mentions_in_prose index [unresolved: prose mention only]
  - outbound mentions_in_prose maintain [unresolved: prose mention only]
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Use when the user says /vault-maintain or asks for vault-wide maintenance — tag hygiene, MOC freshness, cross-project link integrity, or summary auto-fill. Runs all 4 phases in sequence or a single phase via /vault-maintain phase:N. Don't use for single-project work file cleanup — use /maintain instead.

(machine-filled from rationale-index.json; extraction locus: frontmatter)

## How

Invoked via the Skill tool on `/vault-maintain` for all four phases in sequence, or `/vault-maintain phase:N` for a single phase (`.claude/skills/vault-maintain/SKILL.md:33-34`); the phases are independent and the user may want only one (line 28).

The work is vault scanning and report writing: a tag frequency map with Levenshtein near-duplicate pairs over Inbox/, Notes/, Projects/, and Resources/ (`.claude/skills/vault-maintain/SKILL.md:39-45`), MOC freshness resolved through each MOC's embedded Dataview query against baselines in `.maintain-cache.json`, updated atomically via tmp-then-rename (lines 48-54), wiki-link resolution with a report written to `Projects/vault-maintenance/work/` (lines 57-59), and frontmatter-only `summary:` auto-fill (lines 63-67).

The contract and its enforcement are the invariants: no note body modified, nothing moved, renamed, or deleted, `date:` unchanged in every file, valid cache JSON after every run, date-prefixed reports, idempotent re-runs (`.claude/skills/vault-maintain/SKILL.md:70-77`). Near-duplicate tags are flagged but never auto-merged (Wiktor merges via Tag Wrangler), and link problems are reported, never auto-fixed (lines 27, 45, 60).
<!-- PROSE:END -->
