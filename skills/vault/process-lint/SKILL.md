---
name: process-lint
description: "Use when running periodic wiki layer health-check. Validates source citations (file existence + SHA hash match + anchor + content overlap), finds orphan wiki pages, gaps in index.md, log continuity, stale pages. Read-only at wiki layer — flags findings, never edits. Implements Karpathy LLM-Wiki Lint operation + M2 crypto hash verification (Layer 3 fabrication mitigation)."
---

# process-lint — Karpathy LLM-Wiki Lint Operation

You have been routed here for periodic wiki-layer health check. Read every wiki page, validate citations, flag drift. Output: structured lint report.

## Use-when

- User says `/process-lint` or "run lint" or "check wiki health"
- Periodic scheduled check (manual trigger — no file-watcher assumed)
- After bulk ingest activity (10+ new wiki pages) to catch drift before it compounds
- Before promoting bootstrap entries to ratified

## Do-NOT-use-when

- Wiki has zero pages — nothing to lint
- A single specific claim needs verification — that's `process-qa`, not Lint (Lint scans entire wiki)
- You intend to FIX problems — Lint is read-only at wiki layer; fixes go through `process-ingest` re-run on the source

## Gotchas

- **Lint NEVER edits wiki pages directly.** Findings only. Fixes happen via re-ingest from source, not via Lint touching wiki content.
- **Hash mismatch ≠ wiki page wrong.** It means source has changed since ingest. The wiki page may still be correct for the OLD source; re-ingest decides if claims need update.
- **Noun-overlap content-match (Pass A) is heuristic.** False positives on short summary pages; false negatives on heavily paraphrased claims. Accept WEAK_CITATION as advisory, not error.
- **Bootstrap-tagged pages get LIGHT pass.** Pass A applies, Pass B is downgraded (MISSING_SOURCE on bootstrap is expected if upgrading from pre-Karpathy pages).

## Steps

### Step 1 — Inventory wiki layer

Scan all files with `#wiki` tag in frontmatter:
- `Resources/KB/*.md`
- `Notes/**/*.md` where `tags:` contains `#wiki`
- `Projects/*/archive/*.md` where `tags:` contains `#wiki`

Count: total wiki pages, by `wiki_status` (bootstrap vs ratified), by directory.

### Step 2 — Pass A: Citation Validation

For each wiki page with `source:` field:

For each entry in `source:` array:

1. **File existence:** Check `source[].path` resolves to existing file. Missing → `ORPHAN_CITATION` (error).

2. **SHA hash match (M2 Layer 3):** If `sha256` field present, recompute SHA of current file bytes. Compare to committed hash. Mismatch → `SOURCE_DRIFT` (warning — source has changed since ingest, but wiki page may still be valid for original content).

3. **Anchor heading check:** If `anchor` field present, Read the source file. Find the heading. Missing → `MISSING_ANCHOR` (warning).

4. **Content overlap check:** Extract section text under anchor (or first 500 chars if no anchor). Compare to wiki page's first paragraph (the summary). Check ≥1 shared key noun (proper noun, lowercase 4+ char common noun). Match → `CITATION_VALID`. No match → `WEAK_CITATION` (warning — citation file exists but content doesn't visibly support claim).

Compute metric: `citation_resolve_rate = CITATION_VALID / total source entries`.

### Step 3 — Pass B: Orphan wiki pages

For each `#wiki`-tagged file:
- If no `source:` field at all → `MISSING_SOURCE` (error for ratified; warning for bootstrap).
- If `source:` is empty array → `MISSING_SOURCE` (same).

Retroactively-tagged MOC pages are expected MISSING_SOURCE on first lint until bootstrap-debt closure. Report but don't escalate as critical for those.

### Step 4 — Pass C: Index completeness

Read `Resources/KB/index.md`. For each `#wiki`-tagged file from Step 1:
- Is there a row in index.md whose Path column matches?
- If no row → `INDEX_GAP` (error).

For each row in index.md:
- Does the referenced wiki page still exist?
- If file missing → `INDEX_ORPHAN` (warning — index references deleted page).

### Step 5 — Pass D: Log continuity

Read `log.md` (workspace root). Extract every `Wiki pages updated:` value from Ingest entries.

For each `#wiki`-tagged page from Step 1:
- Does any log Ingest entry mention this page's path in `Wiki pages updated`?
- If no → `UNLOGGED_PAGE` (warning — page exists but no ingest log; may be pre-Karpathy or hand-created).

### Step 6 — Pass E: Stale pages

For each `#wiki` page with `source:` entries:
- Compare `source[].sha256` recomputed vs committed.
- If hash changed → also check: is the wiki page's `updated` date older than the source file's mtime?
- If yes → `STALE_PAGE` (advisory — page may need re-ingest).

### Step 7 — Write report

Save lint report to the active project's `work/` directory as `YYYY-MM-DD-lint-report.md`. Default to `Projects/[your-project]/work/` if no other project context is active.

Frontmatter:

```yaml
---
date: YYYY-MM-DD
tags: [lint-report, vault-stewardship]
status: "#active"
type: lint-report
total_wiki_pages: <count>
citation_resolve_rate: <0.0-1.0>
findings_by_severity:
  error: <count>
  warning: <count>
  advisory: <count>
---
```

Body sections:
- `## Summary` — counts per finding code, KPI verdict, top 5 most-cited sources
- `## Errors` — ORPHAN_CITATION, MISSING_SOURCE (ratified pages only), INDEX_GAP — table with file + finding + suggested fix
- `## Warnings` — SOURCE_DRIFT, MISSING_ANCHOR, WEAK_CITATION, INDEX_ORPHAN, MISSING_SOURCE (bootstrap), UNLOGGED_PAGE
- `## Advisories` — STALE_PAGE
- `## Findings by file` — alphabetical list with all findings per file

### Step 8 — Append log.md entry

Append a LINT entry to `log.md` (workspace root):

```markdown
## YYYY-MM-DD HH:MM — Lint — LINT-NNN

**Operation:** Lint
**Source:** scheduled lint (full wiki layer)
**Agent:** process-lint-v1
**Duration:** <seconds>
**Wiki pages updated:** N/A
**Index updated:** N/A
**Citations written:** N/A
**Lint findings:** errors=<X>, warnings=<Y>, advisories=<Z>, citation_resolve_rate=<rate>
**Status:** SUCCESS
**Notes:** Report at work/YYYY-MM-DD-lint-report.md

---
```

## Rules

- **Read-only at wiki layer.** Never Edit any `#wiki`-tagged file from inside this skill.
- **Findings only.** Fixes happen via re-ingest, not Lint.
- **Heuristic content-match accepts noise.** WEAK_CITATION is warning not error.
- **Append-only on log.md.**
- **Output report path goes to active-project work/.** Default to a sensible project work/ if no project context.
- **`MISSING_SOURCE` is downgraded to warning for bootstrap-status pages.** Retroactively-tagged MOCs are expected to be MISSING_SOURCE until backfill closes it.

## Output

End with a short summary line + path to full report:

```
LINT REPORT
Total wiki pages: <count>
citation_resolve_rate: <%>
Errors: <count> (ORPHAN_CITATION, MISSING_SOURCE-ratified, INDEX_GAP)
Warnings: <count>
Advisories: <count>
Report: <path>
log.md: LINT-NNN
```
