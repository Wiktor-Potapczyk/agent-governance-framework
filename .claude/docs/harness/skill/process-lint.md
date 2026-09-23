---
component: "process-lint"
kind: "skill"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# skill: process-lint

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/skills/process-lint`
- **Provenance:** authored-in-harness
- **Reachability:** `EVD-004` (.claude/registry.json)
- **Usage:** Recorded use count 0 (source: `governance-log.jsonl:agent_dispatched.skill_context[]`).
- **Edges:**
  - inbound mentioned_in_prose CLAUDE.md [unresolved: prose mention only]
  - inbound mentioned_in_prose process-governance-mine [unresolved: prose mention only]
  - inbound mentioned_in_prose process-qa [unresolved: prose mention only]
  - inbound mentioned_in_prose process-query [unresolved: prose mention only]
  - inbound cataloged_in registry.json
  - outbound mentions_in_prose _daily_aggregate [unresolved: prose mention only]
  - outbound mentions_in_prose _irreversible_surface [unresolved: prose mention only]
  - outbound mentions_in_prose _unicode_hygiene [unresolved: prose mention only]
  - outbound mentions_in_prose bash-safety-guard [unresolved: prose mention only]
  - outbound mentions_in_prose dispatch-compliance-check [unresolved: prose mention only]
  - outbound mentions_in_prose governance-log [unresolved: prose mention only]
  - outbound mentions_in_prose governance-log.jsonl [unresolved: prose mention only]
  - outbound mentions_in_prose hook-write-regression-gate [unresolved: prose mention only]
  - outbound mentions_in_prose index [unresolved: prose mention only]
  - outbound mentions_in_prose lint-cadence-trigger [unresolved: prose mention only]
  - outbound mentions_in_prose n8n-patterns [unresolved: prose mention only]
  - outbound mentions_in_prose process-ingest [unresolved: prose mention only]
  - outbound mentions_in_prose process-qa [unresolved: prose mention only]
  - outbound mentions_in_prose tag-variant-check [unresolved: prose mention only]
  - outbound mentions_in_prose vault-structure-check [unresolved: prose mention only]
  - outbound mentions_in_prose verifier-gate-check [unresolved: prose mention only]
  - outbound mentions_in_prose verify [unresolved: prose mention only]
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Use when running periodic wiki layer health-check. Validates source citations (file existence + SHA hash match + anchor + content overlap), finds orphan wiki pages, gaps in index.md, log continuity, stale pages. Read-only at wiki layer — flags findings, never edits. Implements Karpathy LLM-Wiki Lint operation + M2 crypto hash verification (Layer 3 fabrication mitigation).

(machine-filled from rationale-index.json; extraction locus: frontmatter)

## How

Invoked via the Skill tool on /process-lint or "check wiki health"; the weekly cadence is nudged by lint-cadence-trigger.py at SessionStart, which reads the state file this skill writes and reminds when the last run is more than 7 days old (.claude/skills/process-lint/SKILL.md:12, :240).

It reads the whole #wiki-tagged layer (.claude/skills/process-lint/SKILL.md:34) and runs Bash helpers for the later passes: hook_activity_report.py with --findings and --matrix for the asset-matrix and telemetry checks (.claude/skills/process-lint/SKILL.md:140, :160) and scan_file from _unicode_hygiene.py for the raw-layer hygiene pass (.claude/skills/process-lint/SKILL.md:187). Its writes are bounded: the lint report, the two cadence state files, and an append-only log.md entry; it never edits any #wiki file (.claude/skills/process-lint/SKILL.md:265).

It must deliver the coded findings of passes A through M (ORPHAN_CITATION, SOURCE_DRIFT, INDEX_GAP, DOCTRINE_DRIFT, and the rest), a report file with severity counts and citation_resolve_rate in frontmatter (.claude/skills/process-lint/SKILL.md:203), a LINT-NNN log.md entry (.claude/skills/process-lint/SKILL.md:247), and the closing LINT REPORT summary block (.claude/skills/process-lint/SKILL.md:277). Findings only: fixes go through re-ingest, never through Lint touching wiki content (.claude/skills/process-lint/SKILL.md:266).
<!-- PROSE:END -->
