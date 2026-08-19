---
name: process-lint
description: Use when running periodic wiki layer health-check. Validates source citations (file existence + SHA hash match + anchor + content overlap), finds orphan wiki pages, gaps in index.md, log continuity, stale pages. Read-only at wiki layer: flags findings, never edits. Implements Karpathy LLM-Wiki Lint operation + M2 crypto hash verification (Layer 3 fabrication mitigation).
---

# process-lint: Karpathy LLM-Wiki Lint Operation

You have been routed here for periodic wiki-layer health check. Read every wiki page, validate citations, flag drift. Output: structured lint report.

## Use-when

- User says `/process-lint` or "run lint" or "check wiki health"
- Periodic scheduled check (manual trigger only: no file-watcher on OneDrive per Karpathy plan CON-005)
- After bulk ingest activity (10+ new wiki pages) to catch drift before it compounds
- Before promoting bootstrap entries to ratified

## Do-NOT-use-when

- Wiki has zero pages: nothing to lint
- A single specific claim needs verification: that's `process-qa`, not Lint (Lint scans entire wiki)
- You intend to FIX problems: Lint is read-only at wiki layer; fixes go through `process-ingest` re-run on the source

## Gotchas

- **Lint NEVER edits wiki pages directly.** Findings only. Fixes happen via re-ingest from source, not via Lint touching wiki content.
- **Hash mismatch ≠ wiki page wrong.** It means source has changed since ingest. The wiki page may still be correct for the OLD source; re-ingest decides if claims need update.
- **Noun-overlap content-match (Pass A) is heuristic.** False positives on short summary pages; false negatives on heavily paraphrased claims. Accept WEAK_CITATION as advisory, not error.
- **Bootstrap-tagged pages get LIGHT pass.** Pass A applies, Pass B is downgraded (MISSING_SOURCE on bootstrap is expected if upgrading from pre-Karpathy pages).

## Steps

### Step 1: Inventory wiki layer

Scan all files with `#wiki` tag in frontmatter:
- `Resources/KB/*.md`
- `Notes/**/*.md` where `tags:` contains `#wiki`
- `Projects/*/archive/*.md` AND `Projects/*/*/archive/*.md` where `tags:` contains `#wiki`: projects nest one level below `Projects/` (a directory IS a project iff it directly contains `STATE.md`), so a single-star glob silently misses every nested project's archive, for example `Projects/Personal/Finance/archive/`

Count: total wiki pages, by `wiki_status` (bootstrap vs ratified), by directory.

### Step 2: Pass A: Citation Validation

For each wiki page with `source:` field:

For each entry in `source:` array:

1. **File existence:** Check `source[].path` resolves to existing file. Missing → `ORPHAN_CITATION` (error).

2. **SHA hash match (M2 Layer 3):** If `sha256` field present, recompute SHA of current file bytes. Compare to committed hash. Mismatch → `SOURCE_DRIFT` (warning: source has changed since ingest, but wiki page may still be valid for original content). **Skip this check entirely when the entry's `type: generated`**: auto-generated sources (script outputs like `registry.json`) intentionally omit `sha256`; SHA-pinning them is perpetual false drift (step-1 path-existence still applies). See CLAUDE.md `type: generated` exemption.

3. **Anchor heading check:** If `anchor` field present, Read the source file. Find the heading. Missing → `MISSING_ANCHOR` (warning).

4. **Content overlap check:** Extract section text under anchor (or first 500 chars if no anchor). Compare to wiki page's first paragraph (the summary). Check ≥1 shared key noun (proper noun, lowercase 4+ char common noun). Match → `CITATION_VALID`. No match → `WEAK_CITATION` (warning: citation file exists but content doesn't visibly support claim).

Compute metric: `citation_resolve_rate = CITATION_VALID / total source entries`.

### Step 3: Pass B: Orphan wiki pages

For each `#wiki`-tagged file:
- If no `source:` field at all → `MISSING_SOURCE` (error for ratified; warning for bootstrap).
- If `source:` is empty array → `MISSING_SOURCE` (same).

The 5 retroactively-tagged MOCs in this vault are expected MISSING_SOURCE on first lint until bootstrap-debt closure (M4). Report but don't escalate as critical for those.

### Step 4: Pass C: Index completeness

Read `Resources/KB/index.md`. For each `#wiki`-tagged file from Step 1:
- Is there a row in index.md whose Path column matches?
- If no row → `INDEX_GAP` (error).

For each row in index.md:
- Does the referenced wiki page still exist?
- If file missing → `INDEX_ORPHAN` (warning: index references deleted page).

### Step 5: Pass D: Log continuity

Read `Vault/log.md`. Extract every `Wiki pages updated:` value from Ingest entries.

For each `#wiki`-tagged page from Step 1:
- Does any log Ingest entry mention this page's path in `Wiki pages updated`?
- If no → `UNLOGGED_PAGE` (warning: page exists but no ingest log; may be pre-Karpathy or hand-created).

### Step 6: Pass E: Stale pages

For each `#wiki` page with `source:` entries:
- Compare `source[].sha256` recomputed vs committed.
- If hash changed → also check: is the wiki page's `updated` date older than the source file's mtime?
- If yes → `STALE_PAGE` (advisory: page may need re-ingest).

### Step 6.5: Pass F: MOC density

For each `#moc`-tagged file in `Resources/KB/`:
- Count `[[wikilink]]` entries under any `## Members` section.
- If count > 50 → `DENSE_MOC` (advisory: MOC is past the dual-mode cap; consider splitting into sub-MOCs by sub-topic).
- The 6 MOCs the earlier structure wave capped at 50 (for example moc-active, moc-agent-governance, moc-n8n-patterns, moc-research-findings, plus two domain MOCs) are expected DENSE_MOC findings until splits land.

### Step 6.6: Pass G: Wiki page sparsity

For each `#wiki`-tagged file:
- Body length (post-frontmatter, post-codeblock) < 200 chars AND `source:` array has <1 entry → `SPARSE_WIKI_PAGE` (warning: page has neither substance nor citation; likely a forward-compat placeholder or premature ingest).
- Forward-compat MOCs (e.g., moc-life, moc-people) that have an explicit empty-by-design note in body are excluded from this finding.

### Step 6.7: Pass H: Status decay (Increment 3, 2026-06-12)

For files in `Notes/` and project status files (`Projects/X/{STATE,PROJECT,task_plan}.md`) with `status: active`:
- If file untouched > 14 days (mtime heuristic: OneDrive-unreliable, so advisory-only) → `STATUS_DECAY` (advisory: propose flipping to `waiting`/`done`).
- Scope deliberately narrow: vault-wide active+old would drown the report; the audit's empirical finding was the Notes/ corpus claiming active for months.

### Step 6.8: Pass I: Template-schema parity (Increment 3, 2026-06-12)

For every `Templates/*.md`:
- Frontmatter must declare `date:`, `type:`, `tags:`, `status:`, and `type` must be in the Rules.md 10-value enum → `TEMPLATE_PARITY` (warning).
- Rationale (audit 2026-06-10 lesson 3): every note born from a stale template silently accrues FIX debt: templates are schema, not scaffolding.

### Step 6.9: Pass J: Broken wikilinks (Increment 5, 2026-06-18 purpose pass)

Scan every non-excluded, non-`.claude/`, non-doc-illustration vault `.md` for `[[...]]` targets that resolve to nothing. The resolution set MUST be every real vault note (Archives included as valid targets, even though archived files are not link SOURCES) PLUS the memory folder, then drop placeholder/bash/relative shapes → `BROKEN_WIKILINK` (advisory).

- **Resolve against the memory folder.** `[[reference_*]]`, `[[feedback_*]]`, `[[finding_*]]`, `[[decision_*]]` point at `~/.claude/projects/<enc>/memory/`, which is OUTSIDE the vault root. Obsidian cannot follow them, but they are INTENTIONAL cross-references, not rot. Resolving against the memory folder (portably derived; prefix-regex fallback when absent) is what keeps the count honest. See `reference_vault_wikilinks_to_memory_always_read_broken` (memory).
- **Resolve against ALL vault notes, not the lint source set.** A link to an archived note is not broken. Building the resolution set from the archive-filtered source list was the original bug (made every link-to-archived-file read as broken: 982 false vs 99 real).
- **Rationale (audit 2026-06-18 lesson):** a naive vault graph scan reported 962 broken links; after memory-resolution and archive-inclusion the true count is ~99 genuine strays (deleted drafts, hook-name references that are `.py` not notes, file-path links). NEVER mass-"fix" memory pointers; the only genuinely-fixable links are intra-vault references to renamed/moved notes (there were zero of those). Advisory only.

### Step 6.10: Pass K: Doctrine drift (dispatchable agents) (GAP-8, 2026-07-10)

Set-comparison of agent names CLAUDE.md references as dispatchable vs the union of what actually exists:

1. Extract every agent name referenced as dispatchable in `CLAUDE.md` (the Agent Registry section lists plus Delegation Examples).
2. Build the existence set as the UNION of (a) `.claude/agents/*.md` filenames (stem = agent name) and (b) plugin-agent entries in `.claude/registry.json`. Plugin agents legitimately have no agents-dir file, so membership in EITHER set clears a name.
3. A name in NEITHER set → `DOCTRINE_DRIFT` finding. Severity: **advisory** (doctrine text names an agent that cannot be dispatched; propose correcting CLAUDE.md or restoring the agent, never auto-edit).
4. **Allowlist: deprecated-alias strikethroughs.** A CLAUDE.md name wrapped in `~~strikethrough~~` (e.g. the struck 2026-05-25 orchestrator alias kept as a deprecation safety net) is documented history, not a live dispatch claim, and is NOT a `DOCTRINE_DRIFT` finding. Rationale: the strikethrough is itself the drift marker; flagging it would demand deleting an intentional audit trail.
5. **R1 drift candidate (frozen Gate-1 fallback):** the Pass may also compare `bash-safety-guard.py` `_IRREVERSIBLE_FALLBACK_SNAPSHOT` against `_irreversible_surface.py` `IRREVERSIBLE_BASH_PATTERNS` (the snapshot is a frozen copy per the GAP-11 docstring drift note); divergence → advisory `DOCTRINE_DRIFT` on the snapshot.

### Step 6.11: Pass L, asset-matrix findings (contract C5, 2026-08-01)

The periodic half of the C5 gate. Its per-edit half already runs inside `hook-write-regression-gate.py`, which only fires when a hook file is written; this pass catches drift introduced any other way, such as a settings-file edit that registers a hook nobody added, or a hook renamed without its emitted name following.

Run the generator and read its findings:

```
python .claude/scripts/hook_activity_report.py --findings
```

Exit code 0 means clean; 1 means findings, each printed as `KIND  hook  detail`. The three kinds:

1. `MISSING_SOURCE`: a hook registered in a settings file has no `.py` on disk. Severity: **error**. A registered hook that cannot load is a silently disarmed gate.
2. `DARK_HOOK`: a registered hook writes to no sink of any kind (contract C1). Severity: **warning**. The vault reached 0 dark on 2026-08-01, so any occurrence is a regression rather than a backlog item.
3. `HOOK_NAME_DRIFT`: a hook emits a `hook:` value that is not its own filename. Severity: **warning**. Convergence on the shared writer does not prevent this, because the writer takes `hook` as an unchecked caller string; see [[2026-08-01-governance-log-writer-audit]].

Two hooks are grandfathered in `HOOK_NAME_GRANDFATHERED` (`dispatch-compliance-check` emits `dispatch-compliance`, `verifier-gate-check` emits `verifier-gate`). Do not propose renaming them as routine cleanup: consumers filter on the emitted name and the historical records keep it, so a rename is a log-continuity decision for the owner, not a fix to make a check pass.

Do NOT edit hooks or settings from this pass. Report and propose, per this skill's proposal-only posture.

### Step 6.12: Pass T, telemetry vocabulary and coverage (Hermes P3, 2026-08-18)

The weekly half of the telemetry-integrity check ([[2026-08-17-hermes-p3-telemetry-integrity-plan]]). Offline inside this sweep; nothing here runs per event, and no sink is ever written, coerced, or migrated by this pass.

Run both commands via the full Python314 path (reference_windows_python_path_order):

```
"C:\Program Files\Python314\python.exe" .claude\scripts\hook_activity_report.py --findings
"C:\Program Files\Python314\python.exe" .claude\scripts\hook_activity_report.py --matrix
```

`--findings` exit 0 means clean; 1 means findings. Beyond the three Pass L kinds it now prints a VOCAB block:

1. `UNDECLARED_VALUE`: a real-session record carries a value outside the declared vocabulary (`.claude/hooks/aggregates/telemetry-vocabulary.json`) for its sink and axis. Severity: **warning**. Advisory only, never a block: the record stays untouched (the anti-coercion rule). The default cutoff is the vocabulary artifact's generation stamp, so the stream measures new drift; `--since=all` gives the full-history count.
2. `STALE_VOCABULARY`: a production writer file is newer than the artifact. Severity: **advisory**. Propose regenerating with `--vocab-write` (a build action, not a lint action; mtime heuristic, OneDrive-unreliable).

`--matrix` prints three sections: hooks (Pass L semantics, unchanged), skills, and agents. The skills and agents dark-surface lists are printed in full and are MEASUREMENT ONLY, wired to no gate; do not turn them into cleanup mandates. `REGISTRY_DISK_DRIFT` warn lines inside the output name on-disk assets missing from `registry.json`; propose a registry regeneration.

Append both summaries (findings block plus the three per-section Generated footers and dark lists) to the lint report under a `## Telemetry (Pass T)` section, then stamp the state file `.claude/hooks/_state/telemetry-check-cadence.json`:

```json
{
  "last_iso": "YYYY-MM-DDTHH:MM:SSZ",
  "findings": {"matrix": <count>, "vocab": <count>},
  "report_path": "Projects/<active>/work/YYYY-MM-DD-lint-report.md"
}
```

The stamp file is SEPARATE from `lint-cadence.json` by design: folding it in would let a partial lint run that skips Pass T stamp the telemetry check as done; a separate stamp makes skipping visible. `lint-cadence-trigger.py` reads it at SessionStart and reminds when the check is more than 7 days stale.

### Step 6.13: Pass M: raw-layer Unicode hygiene (Hermes P5, 2026-08-18)

Scan the raw layer at rest for invisible and bidirectional characters (the prompt-injection carrier classes). Scope: every file in `Inbox/`, `Clippings/`, and untagged `Notes/` (the raw layer minus retired Daily Notes). `Projects/*/source-data/` is a pre-registered v2 extension, out of scope here.

Call `scan_file` from `.claude/hooks/_unicode_hygiene.py` on each file. That module is the single source of the class table; this pass never re-implements it. Rides the existing weekly sweep: no new cadence, no state file changes.

Findings:

1. `BIDI_CONTROL` (warning): any hit in classes `bidi-override`, `bidi-isolate`, `bidi-mark`, or `feff-midfile`. Note: `bidi-mark` is advisory at class level but grouped under this warning-level finding by design; keep the per-class severity visible in the finding detail.
2. `INVISIBLE_UNICODE` (advisory): any hit in every other class except `bom-at-0`, which produces no lint finding at all (benign encoding artifact, named so it never inflates a real finding).
3. `UNSCANNED_RAW_FILE` (warning): any file `scan_file` reports as `readable: False`. A file the scanner could not read is a finding, never a skip: a scanner that silently skips unreadable files reports a clean corpus it never read.

Report the per-directory file count alongside the findings so corpus growth is visible in the report rather than silent. Baseline 2026-08-17: 68 files, 0 findings. Any finding above 0 is high-signal (zero base rate) and goes to the owner; read-only, findings only, never auto-acted on.

### Step 7: Write report

Save lint report to `Projects/your-project/work/YYYY-MM-DD-lint-report.md` (or `work/` of currently active project if obvious).

Frontmatter:

```yaml
---
date: YYYY-MM-DD
tags: [lint-report, vault-stewardship, project/your-project]
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
- `## Summary`: counts per finding code, KPI verdict, top 5 most-cited sources
- `## Errors`: ORPHAN_CITATION, MISSING_SOURCE (ratified pages only), INDEX_GAP, MISSING_SOURCE (Pass L, a registered hook with no file), in a table with file + finding + suggested fix
- `## Warnings`: SOURCE_DRIFT, MISSING_ANCHOR, WEAK_CITATION, INDEX_ORPHAN, MISSING_SOURCE (bootstrap), UNLOGGED_PAGE, SPARSE_WIKI_PAGE, DARK_HOOK, HOOK_NAME_DRIFT, BIDI_CONTROL, UNSCANNED_RAW_FILE
- `## Advisories`: STALE_PAGE, DENSE_MOC, STATUS_DECAY, BROKEN_WIKILINK, INVISIBLE_UNICODE
- `## Findings by file`: alphabetical list with all findings per file

### Step 7.5: Write last-run state file

Write `.claude/hooks/_state/lint-cadence.json`:

```json
{
  "last_iso": "YYYY-MM-DDTHH:MM:SSZ",
  "report_path": "Projects/<active>/work/YYYY-MM-DD-lint-report.md",
  "errors": <count>,
  "warnings": <count>,
  "advisories": <count>,
  "citation_resolve_rate": <0.0-1.0>
}
```

Used by `lint-cadence-trigger.py` SessionStart hook to surface a "consider running /process-lint" suggestion when last run is >7 days old.

### Step 8: Append log.md entry

Append a LINT entry to `Vault/log.md`:

```markdown
## YYYY-MM-DD HH:MM: Lint: LINT-NNN

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
- **Output report path goes to active-project work/.** Default to AGR work/ if no project context.
- **`MISSING_SOURCE` is downgraded to warning for bootstrap-status pages.** The 5 retroactively-tagged MOCs are expected to be MISSING_SOURCE until M4 backfill closes it.

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
