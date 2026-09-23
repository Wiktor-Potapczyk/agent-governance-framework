---
name: vault-maintain
description: Use when the user says /vault-maintain or asks for vault-wide maintenance — tag hygiene, MOC freshness, cross-project link integrity, or summary auto-fill. Runs all 4 phases in sequence or a single phase via /vault-maintain phase:N. Don't use for single-project work file cleanup — use /maintain instead.
date: 2026-04-21
type: meta
tags: [skill, unclassified-pending, vault-maintain]
status: active
---
# Skill: /vault-maintain

Vault-wide maintenance skill. Distinct from project-level `/maintain` skill.

## Use-when

- User says `/vault-maintain` (full sequence) or `/vault-maintain phase:N` (single phase)
- Quarterly or post-major-milestone vault hygiene — tag drift, MOC freshness, orphans
- After a wave of new captures (research sprint, external intake) where tag inconsistency is likely

## Do-NOT-use-when

- Project-level work file cleanup is the goal — use `/maintain` (different scope: single project's `work/` directory)
- Single-tag rename or single-orphan cleanup — do that manually with Tag Wrangler
- Vault has just been maintained (within ~7 days) — Phase 1 tag scan churn isn't valuable yet

## Gotchas

- **NO auto-merge on near-duplicate tags** — the skill flags pairs at Levenshtein distance ≤ 2 but Wiktor merges via Tag Wrangler manually. Auto-merge would corrupt intentional pairs (e.g., `#research` vs `#researched`).
- **Phases are independent** — Phase 1 can run without Phase 2-4; output is per-phase. Don't assume the user wants the full sequence unless they say so.
- **Frontmatter is note-style, not skill-style** — this skill uses `date`/`type`/`tags`/`status` (vault-note convention) instead of the `name`/`description` skill convention. Body content is what defines the skill behavior; routing happens via the `name: vault-maintain` extracted from the heading.

## Invocation

`/vault-maintain` — runs all 4 phases in sequence.
`/vault-maintain phase:1` — runs Phase 1 only (tag hygiene).

## Phases

### Phase 1 — Tag hygiene
- Scan Inbox/, Notes/, Projects/, Resources/ for all tag values.
- Build frequency map (case-normalized, hash stripped).
- Compute Levenshtein distance on tag stems for all pairs.
- FLAG: pairs with distance ≤ 2 that are not known intentional pairs.
- FLAG: tags in tag-registry.md with frequency 0 (orphans).
- Output: inline report, two sections (near-duplicates, orphans).
- NO auto-merge. Wiktor uses Tag Wrangler manually.

### Phase 2 — MOC freshness check
- Identify all MOC files (type: meta OR moc tag) in Notes/ and Resources/.
- For each: extract embedded Dataview query, resolve against current vault state.
- Compare result set against prior-run baseline in .maintain-cache.json.
- FLAG: zero results where prior baseline ≥ 1.
- FLAG: identical result set AND MOC date > 30 days old.
- Update .maintain-cache.json (atomic: write to .tmp then rename).
- Output: flagged MOCs with last-known vs current count.

### Phase 3 — Cross-project link integrity
- Resolve every `[[wiki-link]]` in Projects/ + Notes/ against vault file index.
- Classify: (a) resolved, (b) orphaned, (c) one-way.
- Write report to Projects/vault-maintenance/work/YYYY-MM-DD-link-integrity.md.
- NO auto-fix. Wiktor reviews manually.

### Phase 4 — summary: auto-fill
- Scan Notes/ + Projects/ where summary: absent AND type != inbox.
- Read body text (exclude frontmatter).
- Generate 1-2 sentence summary from headings + first paragraph.
- Write summary: to frontmatter ONLY; no body modification.
- Skip notes with existing summary: (idempotency).
- Output: list of notes updated.

## Invariants

- No note body modified.
- No note moved/renamed/deleted.
- date: unchanged in every file.
- .maintain-cache.json is valid JSON after every run.
- All report files date-prefixed (YYYY-MM-DD-).
- Idempotent: running twice produces same final state.

## Out of scope (Inc 2)

- Inbox triage + promotion
- Tag auto-merge
- MOC auto-generation from tag clusters
- Wiki-link enrichment (adding reverse links)
- Full-body content summarization for type: project-state

## Cache

.maintain-cache.json at vault root. Schema:
{
  "last_run": "YYYY-MM-DD",
  "moc_baselines": {
    "Resources/KB/moc-active.md": { "result_count": 0, "date": "YYYY-MM-DD" }
  }
}
Created on first run (Step 11). Never hand-edit.
