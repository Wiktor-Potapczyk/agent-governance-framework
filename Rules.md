---
date: 2026-04-21
tags: [vault, rules, unclassified-pending, conventions, meta]
status: active
type: reference
scope: vault-wide
---
# Vault Rules

## Style Foundation

This vault optimizes for **clarity, longevity, and Claude-operability** over visual polish. Rules below reflect that priority. When a rule conflicts with a preference, the rule wins. When Claude edits the vault, these conventions bind Claude too — they are not aspirational.

---

## Purpose

Authoritative convention reference for this vault. Covers structure, schema, capture,
templates, navigation, promotion, maintenance, and plugins. Audience: Wiktor + Claude (as operator).

---

## Folder structure

```
Vault/
├── Inbox/            — Zero-ceremony dump zone. Date-named per-day files. /vault-maintain promotes.
├── Notes/            — Flat knowledge base (research, learning, reference, ideas). Tag-organized.
├── Projects/         — Active project workspaces. One folder per project. Self-contained lifecycle.
│   └── {Name}/
│       ├── STATE.md
│       ├── task_plan.md
│       ├── work/
│       └── archive/
├── Resources/        — Standing reference docs (playbooks, API refs). Stable, low-churn.
│   └── KB/           — Seeded MOC files and tag registry.
├── Clippings/        — Web clippings and external articles. Flat. Retained as-captured.
├── Daily Notes/      — Kept. Claude creates YYYY-MM-DD.md only on explicit user request. No automation.
├── Archives/         — Completed / retired content. Two sub-structures only (see below).
│   ├── {Project-Name}/ — Mirror of a former Projects/ folder. Created on project archival only.
│   └── loose/          — Flat bucket for all non-project archived content.
├── Areas/
│   └── Personal/     — Life / identity content. Subfolders: people/, life/. Empty until Inc 1b populates.
└── Templates/        — Seed templates. Exempt from Linter schema enforcement.
```

**Dropped from vault:** `Areas/Learning/` (→ Notes/).

**`Areas/` retained:** `Areas/Personal/` is kept (currently empty; Inc 1b populates). See `## Areas/Personal/ conventions` below.

**KIND-folder rule:** a new top-level folder is justified ONLY when a new artifact kind (a) has a
distinct lifecycle from Notes/, AND (b) would pollute `Notes/**/*.md` glob. Absent both conditions, use a tag.

**Clippings/ rationale:** satisfies the KIND-folder rule — web clippings have a distinct lifecycle (captured-from-elsewhere, rarely edited post-capture) and would pollute `Notes/**/*.md` globs used by /vault-maintain. Pre-registered tag `#clippings` in tag-registry. No frontmatter enforcement required (clippings retain source-preserved structure).

---

## Frontmatter

### Universal required fields

| Field    | Format                                         | Required scope         |
|----------|------------------------------------------------|------------------------|
| `date`   | `YYYY-MM-DD`                                   | Universal              |
| `tags`   | YAML array, no `#` prefix, `[]` allowed        | Universal              |
| `status` | plain-string enum: `draft\|active\|waiting\|done\|archived` | Universal |
| `type`   | plain-string enum (10 values, see below)       | Outside `Inbox/` only  |

**Field order on every note:** `date → type → tags → status → optional fields`.

Optional on all types: `source` / `sources` (string/URL), `aliases` (YAML array),
`summary` (string ≤ 280 chars, 1-2 sentences). No per-type required extensions.

### `type:` enum (10 values)

| Value           | Purpose                                                |
|-----------------|--------------------------------------------------------|
| `inbox`         | Raw capture, pre-promotion                             |
| `learning`      | Concept / technique / conclusion note                  |
| `reference`     | Standing reference doc, API guide, playbook            |
| `project-state` | STATE.md / checkpoint file for a project               |
| `work`          | Project artifact in Projects/X/work/                   |
| `daily-log`     | Promoted dated capture retained as log                 |
| `meeting-note`  | Meeting capture with attendees + actions               |
| `idea`          | Speculative / undeveloped thought                      |
| `design`        | Architecture or system design doc                      |
| `meta`          | Vault governance files (INDEX.md, MOC, Rules.md, etc.) |

**Extension rule:** a new `type:` value requires (1) ≥ 3 notes that would use it AND (2) at least
one concrete in-scope consumer (Dataview query, `/vault-maintain` routing rule, or Linter check).
Until both conditions met, use a tag. `/vault-maintain` proposes reclassification when a tag-cluster
reaches the threshold.

### Linter enforcement scope

| Folder scope                               | Enforced rules                                                                           |
|--------------------------------------------|------------------------------------------------------------------------------------------|
| `Inbox/`                                   | `date` format only; `type`, `tags`, `status` **exempt**; whitespace + EOF normalization  |
| `Notes/`, `Projects/`, `Resources/`, `Archives/` | `date` format, `type` enum, `tags` array, `status` enum, field-order; full enforcement |
| `Templates/`                               | **Fully exempt** (placeholder values)                                                     |
| `**/source-data/`, `**/source-assets/`, `**/repo/`, `**/framework-repo/` | **Fully exempt** (external content or nested git repos — see External content exemption below) |

`lintOnSave: true`. Field order: `date → type → tags → status`. `Inbox/` exemption implemented via
mechanism determined in Step 0a (see migration plan). If native per-folder scoping unsupported, a
fallback is recorded in STATE.md.

### External content exemption

Files Wiktor did not author — received materials, source data, stakeholder attachments, external dumps, nested git repos — are exempt from universal frontmatter.

**Conventions:**
- `Projects/[Name]/source-data/` — markdown/text dumps
- `Projects/[Name]/source-assets/` — binary attachments (PDFs, images, etc.)
- `Projects/[Name]/repo/` or `framework-repo/` — nested git repos (e.g., cloned external code, public sibling repos inside the vault)

The folder name is the signal: it encodes provenance and opts content out of schema enforcement for both Linter and `/vault-maintain`. Exempt files are NOT promotion candidates — §Promotion DoD does not apply. `/vault-maintain` Phase 2 MOC freshness and Phase 4 `summary:` auto-fill MUST skip these paths (path exclusion belongs in the skill implementation). Dataview queries that audit schema drift MUST exclude any path containing `/source-data`, `/source-assets`, or `/repo`.

**Enforcement state (as of 2026-04-22):**
- Dataview `dataview-queries.md` missing-frontmatter query — EXCLUSIONS APPLIED
- Linter `foldersToIgnore` config — NOT YET UPDATED (deferred to Vault-Maintenance project)
- `/vault-maintain` skill scaffold Phase 2/4 path exclusions — NOT YET ENCODED (Vault-Maintenance project scope)

Until Linter + skill catch up, only the Dataview layer honors the exemption.

**Known gap:** the current Dataview exclusion uses substring match on `/source-data`, `/source-assets`, `/repo`. This catches the documented conventions but would NOT catch arbitrary future exempt folder names (e.g., `external-repo/`, `vendor/`, `third-party-code/`). A proper `.vault-ignore` mechanism or explicit allowlist is a Vault-Maintenance intake item; until then, stick to the 4 documented folder conventions above.

### `summary:` field

Optional, all types. Never Linter-enforced. **Writer precedence:**
1. Manual value (never overwritten by `/vault-maintain`)
2. `/vault-maintain` Phase 4 auto-fill on absence (excludes `type: inbox`)

### Frontmatter examples

**(a) Inbox note — minimal, type exempt:**

```yaml
---
date: 2026-04-21
tags: []
status: active
---
```

**(b) Learning note — with summary (post auto-fill):**

```yaml
---
date: 2026-04-20
type: learning
tags: [n8n, javascript]
status: done
summary: "DataTable insert returns the inserted row, not the input data — breaks serial fan-outs where downstream nodes expect the original payload."
---
```

**(c) MOC — meta type:**

```yaml
---
date: 2026-04-21
type: meta
tags: [moc, agent-governance]
status: active
---
```

---

## Tags

### Taxonomy

Three namespaces. All flat (single-level prefix only).

**Project tags** — scope a note to a specific project:
- `#project/agent-governance-research`
- `#project/n8n-error-handling`
- `#project/<name>`
- `#project/<other-name>`
- (add per active project)

**Topic tags** — cross-project, reusable:
- `#agent-governance`, `#n8n-patterns`, `#hook-design`, `#rag-prep`
- `#research`, `#decision`, `#finding`
- `#learning`, `#reference`, `#daily`, `#meeting`, `#idea`, `#reading`
- `#automation`, `#ai-agents`, `#claude-code`, `#hooks`, `#memory`, `#mcp`

**Meta tags** — vault governance only:
- From v2 §4.2: `#state`, `#index`, `#ground-truth`, `#moc`
- Post-v2 additions (must be entered in `Resources/KB/tag-registry.md` before use): `#tag-registry`, `#skill`

### Pluralization

Tags are **plural** — `#preferences` not `#preference`, `#decisions` not `#decision`, `#ideas` not `#idea`. Exception: proper-noun tags (`#n8n`, `#claude-code`). Eliminates Phase 1 Levenshtein false positives from singular/plural drift.

Historical note: some existing tags are singular (see tag-registry.md). /vault-maintain Phase 1 flags singular/plural pairs as drift candidates; migrate singular → plural only on Wiktor confirmation.

### Status is NEVER a tag

`status:` is always the frontmatter field. Never create `#active`, `#done`, `#archived`, etc.

### New tag introduction flow

1. **Pre-check (advisory):** `LIST FROM "" WHERE contains(string(file.tags), "candidate-tag")`
   — checks if the tag already exists in the vault.
2. **Register:** add entry to `Resources/KB/tag-registry.md` (tag | scope | first-used note).
3. **Authority:** `/vault-maintain` Phase 1 Levenshtein drift check (distance ≤ 2 on stems) is
   the authoritative near-duplicate detection mechanism. The pre-addition substring check above
   is advisory only. (MINOR-3)

---

## Capture flow

### Primary hotkey: `Ctrl+Shift+N` (bare-append)

**Appends to today's `Inbox/YYYY-MM-DD.md` WITHOUT template injection.** If the file does not
exist, QuickAdd creates it empty (date filename only, no frontmatter injected). First line of
appended content is a `## HH:MM` timestamp heading. (MINOR-5)

### Secondary hotkeys (template-backed)

- `Ctrl+Shift+M` → `Templates/meeting-note.md` (frontmatter + attendees/agenda/decisions/actions)
- `Ctrl+Shift+R` → `Templates/reading-note.md` (frontmatter + source URL + notes scaffold)

Both use Templater for date injection (`<% tp.date.now("YYYY-MM-DD") %>`). Wiktor presses the
hotkey; date populates; template opens. No manual frontmatter editing required.

### Obsidian built-in Daily Notes MUST be disabled

The core "Daily notes" plugin auto-creates `Daily Notes/YYYY-MM-DD.md` on vault open, bypassing
the "Claude creates on request only" policy. Disable: Settings → Core plugins → "Daily notes"
toggle **OFF**. (MINOR-4)

### Where captures go first

All captures land in `Inbox/`. Promoted to target folder by `/vault-maintain` Phase 4
(auto-fill + classification hints) or by Wiktor manually.

---

## Templates

All templates live in `Templates/`. Fully exempt from Linter schema checks.

### Tier 1 — Atomic note-level (capture)

For capture via QuickAdd hotkeys. Minimal frontmatter, section scaffold.

| Template            | Scaffold sections                              | When to use           |
|---------------------|------------------------------------------------|-----------------------|
| `capture.md`        | `## Raw`                                       | Any thought; primary hotkey |
| `daily-log-entry.md`| `## Done`, `## Next`, `## Notes`              | End-of-session log    |
| `meeting-note.md`   | `## Attendees`, `## Agenda`, `## Decisions`, `## Actions` | Before/during meeting |
| `reading-note.md`   | `## Summary`, `## Key Points`, `## Questions` | Reading article/doc/book |
| `idea-seed.md`      | `## Core idea`, `## Why it matters`, `## Next if pursued` | Sudden idea parking |

### Tier 2 — Document-level (authoring)

Claude-authored. Wiktor seeds topic/goal; Claude writes. Never filled manually.

| Template            | Scaffold sections                                              | When to use            |
|---------------------|----------------------------------------------------------------|------------------------|
| `research-note.md`  | Question, Findings, Evidence, Open Questions, Related         | After research loop    |
| `reference-doc.md`  | Summary, Detail, Examples, Caveats                            | Capturing reusable fact |
| `project-state.md`  | Status, Last action, Next step, Blockers, Decisions log       | Project start + milestones |
| `spec.md`           | Goal, Constraints, Design, Open Questions, Changelog          | Locking a decision     |

### Tier 3 — MOC / hierarchy-level (navigation)

Dataview-powered indices. Claude writes once; Dataview auto-refreshes. Never edited manually.
Live in `Resources/KB/`, not `Templates/`.

| Template              | Primary query type            | When to use              |
|-----------------------|-------------------------------|--------------------------|
| `index.md`            | `LIST FROM #tag`              | Single-tag topic index   |
| `topic-map.md`        | `LIST FROM #concept-tag`      | Concept exploration      |
| `project-portfolio.md`| `TABLE status, date FROM "Projects"` | Active project dashboard |
| `area-overview.md`    | `TABLE status, date FROM "X"` | Area-level rollup        |

**Decision rule:** Tier 1 = capturing; Tier 2 = authoring; Tier 3 = navigating.

---

## Knowledge base & navigation

### MOCs (Maps of Content)

Eight seeded MOCs at `Resources/KB/`. Do not edit Dataview query blocks manually.

| MOC file                    | Query basis           | Refresh mode    |
|-----------------------------|-----------------------|-----------------|
| `moc-agent-governance.md`   | `FROM #agent-governance` | Dataview-auto (A) |
| `moc-n8n-patterns.md`       | `FROM #n8n-patterns OR #n8n` | Dataview-auto (A) |
| `moc-research-findings.md`  | `TABLE summary, date FROM #research` + archived section `FROM "Archives/"` | Dataview-auto (A) |
| `moc-active.md`             | `FROM "Projects" OR "Notes" WHERE status = "active"` | Dataview-auto (A) |
| `moc-decisions.md`          | `FROM #decisions`     | Dataview-auto (A) |
| `moc-cross-project.md`      | `FROM "" WHERE length(file.outlinks) > 0` | `/vault-maintain` (S) — results materialized into body |
| `moc-people.md`             | `FROM "Areas/Personal/people"` | Dataview-auto (A) — expected-empty until Inc 1b |
| `moc-life.md`               | `FROM "Areas/Personal/life" OR "Areas/Personal/reflection"` | Dataview-auto (A) — expected-empty until Inc 1b |

**Refresh modes:**
- **(A) Dataview-auto:** query renders live every vault open / file change.
- **(S) /vault-maintain:** `/vault-maintain` Phase 2 explicitly writes current query results into
  the MOC body (materialized, for offline/export use). Live query also stays. (MINOR-2)

### Wiki-links: path-based convention

Use full path relative to vault root:

```markdown
[[Projects/Agent-Governance-Research/work/2026-04-19-obs-v2-design]]
```

NOT filename-based (`[[2026-04-19-obs-v2-design]]`) — path-based survives renames and is indexed
by Dataview `file.outlinks`. Aliases are NOT indexed by Dataview `file.outlinks`.

Rules:
- No `.md` extension (Obsidian appends automatically)
- Path separator `/` (vault root relative)
- No `../` traversal

### Archive retrieval

Use folder-path filtering: `FROM "Archives/"` or `FROM "Projects" OR "Archives"`.

Archived notes retain their tags and are Dataview-queryable by path + tag. **No `archived:`
frontmatter field exists.** The folder path is the signal. Live-only filter: `FROM "Projects"`
(excludes Archives/).

---

## Areas/Personal/ conventions

For life / identity content (people, places, tastes, reflection). Subfolders:

- `Areas/Personal/people/` — one note per person, frontmatter `type: person`, tag `[people]`
- `Areas/Personal/life/` — life events, reflections, journaling. Free-form. Tag `[life]`.

Not in scope for `/vault-maintain` Phase 1 tag drift (Personal content is personal taxonomy). Phase 2 MOC freshness applies (moc-people, moc-life).

---

## Promotion Definition of Done

> **Authoring note:** the criteria below extend v2 design decisions (architecture at v2 §7 defines Archives/ sub-structure; v2 does not specify formal transition gates). The specific thresholds here (e.g., 60-day staleness for Notes→Archives) are first-draft defaults to be refined against observed behavior in Inc 1b `/vault-maintain` runs. Treat as working rules, not immutable policy.

### Inbox/ → Notes/ or Resources/ or Projects/

Promotion-ready when **ALL** of the following:

- Frontmatter has `date`, `tags`, `status`, `type` (type must be non-`inbox`)
- Tagged with at least one topic or project tag
- Filename follows kebab-case + YYYY-MM-DD prefix convention
- Content is substantive (> 2 lines of body)

**Exempt paths are not promotion candidates.** Files in `source-data/`, `source-assets/`, `repo/`, or `framework-repo/` (see §Frontmatter External content exemption) bypass this gate entirely — they were never in the promotion pipeline.

### Notes/ → Archives/loose/

Promotion-ready when **ANY** of the following:

- `status: done` AND no modifications in ≥ 60 days
- Topic has been superseded by a newer note referencing this one as `[[archived]]`
- Project that owned the note is itself archived

### Projects/X/ → Archives/X/

Promotion-ready when **ALL** of the following:

- Project lifecycle complete (all `task_plan.md` items done or explicitly dropped)
- `STATE.md` has final summary + `status: archived`
- `/vault-maintain` Phase 3 shows 0 broken inbound links (or acceptable link-preservation plan documented)

**Archives/ sub-structure rules:**
- `Archives/{Project-Name}/` — mirror of a former `Projects/{Project-Name}/` folder. Same internal
  layout (STATE.md, task_plan.md, work/, archive/). Name matches former Projects/ folder exactly.
- `Archives/loose/` — flat bucket for all non-project archived content. Files retain original names;
  YYYY-MM-DD prefix added if undated.
- Creating `Archives/{Name}/` for content that was never a `Projects/{Name}/` workspace is **prohibited**
  — send to `Archives/loose/` instead.
- Every `Archives/{Project-Name}/` must have a STATE.md or README.md with: what the project was,
  when archived, current-status summary.

---

## Maintenance

### `/vault-maintain` skill — 4 phases

Invocable as `/vault-maintain` (all phases) or `/vault-maintain phase:1` (single phase).

**Phase 1 — Tag hygiene:**
Collect all tag values across Inbox/, Notes/, Projects/, Resources/ (case-normalized, hash stripped).
Build frequency map. Compute Levenshtein distance on stems (strip `#`, lowercase, strip trailing `s`)
for all pairs. FLAG: pairs with distance ≤ 2 not in known-intentional list. FLAG: orphan tags
(in tag-registry.md but frequency 0). Emit inline two-section report (near-duplicates, orphans).
**No auto-merge.** Wiktor uses Tag Wrangler to execute fixes manually.

**Phase 2 — MOC freshness check:**
For each MOC (type: meta or #moc tag) in Notes/ and Resources/: extract embedded Dataview query,
resolve against current vault. Compare result set against `.maintain-cache.json` baseline. FLAG:
zero results where prior ≥ 1. FLAG: identical result set AND MOC `date:` > 30 days old. Update
`.maintain-cache.json` (atomic: write to .tmp, then rename). For `moc-research-findings.md` and
`moc-cross-project.md`: write current query results into MOC body (materialized). (MINOR-2)

**Phase 3 — Cross-project link integrity:**
Resolve every `[[wiki-link]]` in Projects/ + Notes/ against vault file index. Classify: (a) resolved,
(b) orphaned, (c) one-way. Write report to `Projects/vault-maintenance/work/YYYY-MM-DD-link-integrity.md`.
**No auto-fix.** Wiktor reviews manually.

**Phase 4 — `summary:` auto-fill:**
Scan Notes/ + Projects/ where `summary:` absent AND `type:` ≠ `inbox`. **Exclude any path containing `/source-data`, `/source-assets`, `/repo`, or `/framework-repo`** (external content exemption — see §Frontmatter). Read body (exclude frontmatter). Generate 1-2 sentence summary from headings + first paragraph. Write `summary:` to frontmatter ONLY; body untouched. Notes with existing `summary:` are skipped (idempotency). Writer-precedence rule: manual `summary:` is never overwritten.

### Maintenance invariants

- Never modify note body content
- Never move, rename, or delete files
- Never change `date:` on existing notes
- `.maintain-cache.json` must be valid JSON after every run
- All report files date-prefixed (YYYY-MM-DD-)
- Idempotent: running twice produces same final state

### Cadence

On-demand (Wiktor invokes `/vault-maintain`). Phases 1–3 safe for nightly automation; Phase 4
is manual-only (writes frontmatter to unbounded note set; quality should be spot-checked).

### Reserved for Increment 2 (out of scope now)

- Inbox triage + promotion (per-block `## HH:MM` classify + propose destinations + execute moves)
- Tag auto-merge (Phase 1 detects; auto-merge deferred)
- MOC auto-generation from tag-cluster analysis
- Wiki-link enrichment (adding reverse links)
- Full-body content summarization for type: project-state + type: inbox

---

## Plugins

### Installed — 9 plugins

| Plugin                          | Role                                                                |
|---------------------------------|---------------------------------------------------------------------|
| **Dataview**                    | All Tier 3 MOC queries; ad-hoc note lookups                         |
| **Templater**                   | Date injection + content slot in meeting-note + reading-note hotkeys |
| **QuickAdd**                    | Capture hotkey dispatch (primary bare-append + secondary template-backed) |
| **Linter**                      | Folder-scoped required-field enforcement; YAML normalization        |
| **Omnisearch**                  | Full-text BM25 search when tags unknown                             |
| **Find Orphaned Files & Broken Links** | On-demand orphan/broken-link report (complements Phase 3)    |
| **Tasks**                       | Vault-wide checkbox aggregation (`- [ ]` pattern)                   |
| **Strange New Worlds**          | Inline backlink badges on `[[wiki-links]]`                          |
| **Tag Wrangler**                | Vault-wide tag rename/merge (executes Phase 1 reports manually)     |

**Composure note:** QuickAdd routes; Templater substitutes dates in template-backed hotkeys.
They compose cleanly — no redundancy conflict.

### Deferred (install-later)

- **Smart Connections** — RAG-prep future scope; needs embedding API decision (cost + vendor).
  Install once RAG approach locked in Inc 2.
- **Metadata Menu** — GUI frontmatter editing; adds ceremony. Promote to install-now ONLY if
  Wiktor reports friction manually updating `status:` via YAML post-Inc 1.

---

## Archive loose retrieval

`Archives/loose/README.md` describes categories of files flattened into loose. **README is updated
POST-migration** after contents are known. Do not pre-author content descriptions before files
move in. (MINOR-6)

---

## Conventions checklist

Quick reference for day-to-day use.

- Files named kebab-case; dates as YYYY-MM-DD prefix (e.g., `2026-04-21-note-title.md`)
- All notes in English
- Frontmatter always includes `date`, `tags`, `status`; `type` required outside `Inbox/`
- Field order: `date → type → tags → status → optional fields`
- Never create `#active`, `#done`, `#archived`, `#draft` tags — `status:` is the frontmatter field
- No `#` prefix inside tag values: `tags: [learning, n8n]` not `tags: [#learning, #n8n]`
- Tags are **plural** (`#ideas`, `#decisions`) — see `### Pluralization` above
- Wiki-links use full vault-root path, not filename: `[[Projects/X/work/YYYY-MM-DD-title]]`
- No `.md` extension in wiki-links; no `../` traversal
- Primary capture = `Ctrl+Shift+N` bare-append (no template injection)
- Obsidian built-in Daily Notes core plugin stays **disabled**
- MOCs are Dataview queries — never hand-curate the lists inside them
- `Archives/` is queryable — notes there retain tags and are discoverable via `FROM "Archives/"`
- No per-note `archived:` field; folder path `Archives/` is the signal
- `/vault-maintain` runs on-demand; never auto-destructive without confirmation
- Promotion Inbox→Notes requires: type ≠ inbox, at least one topic/project tag, kebab-case + date prefix, substantive body
- `Projects/X/` archives when task_plan complete + STATE.md finalized + Phase 3 shows 0 broken links
- New tags: pre-check advisory (Dataview), register in tag-registry.md, Phase 1 Levenshtein is the authoritative drift authority (MINOR-3)
- Templates grouped: Tier 1 (capture via hotkey) / Tier 2 (Claude-authored, document-level) / Tier 3 (Dataview MOC, navigation)
- `summary:` auto-fill by Phase 4; manual values are never overwritten
- `Archives/{Project-Name}/` mirrors Projects/ structure; `Archives/loose/` for everything else
- KIND-folder rule: new top-level folder only when lifecycle AND glob-pollution both apply
- `Areas/Personal/` retained; subfolders `people/` and `life/` populate in Inc 1b
