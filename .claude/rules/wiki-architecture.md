---
date: 2026-09-02
tags: [hooks, reference, wiki, vault]
status: active
paths:
  - "Resources/KB/**"
  - "Inbox/**"
  - "Clippings/**"
  - "Notes/**"
  - "log.md"
---

# Wiki Architecture (Karpathy LLM-Wiki) and Wiki Layer Invariants

Both sections moved verbatim from vault-root CLAUDE.md (O16 trim, ruling rows S5 and S9
of [[2026-09-02-o16-row-rulings-merged]]); they describe one mechanism, the wiki schema
and its three enforcement layers. One internal cross-reference was retargeted during the
move (Pass T pointer, previously aimed at the Conventions cadence bullet that is now a
one-liner); nothing else is reworded.

## Karpathy LLM-Wiki Architecture (2026-05-10)

The vault adopts Andrej Karpathy's LLM-Wiki pattern (gist: https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f). Three layers + three operations + utility files. **Doctrine-only — no physical rename of existing directories.**

### Layer mapping

| Karpathy layer | Existing vault directories | Ownership |
|---|---|---|
| **raw/** (immutable curated sources) | `Inbox/`, `Clippings/`, `Daily Notes/`, `Projects/*/work/` (research artifacts), `Projects/*/source-data/`, `Notes/` (Wiktor-authored, untagged) | Wiktor or external; never LLM-edited |
| **wiki/** (LLM-generated, cross-referenced) | `Resources/KB/`, `Notes/` files tagged `#wiki`, `Projects/*/archive/` (synthesized summaries only) | LLM-owned; Wiktor reviews but rarely edits |
| **schema** (behavioral spec) | `CLAUDE.md`, `.claude/skills/`, `.claude/agents/`, `.claude/hooks/` | Co-evolved Wiktor + LLM |

**`#wiki` tag disambiguates** LLM-owned wiki notes from Wiktor's own notes inside `Notes/`. Without `#wiki`, a note in Notes/ is treated as raw-layer (input material, not LLM-managed).

### Operations

- **Ingest** — `process-ingest` skill. Triggered by `inbox-auto-ingest.py` hook on Inbox/ writes OR manual invocation. Reads raw doc → searches wiki → writes summary page (with `source:` field) → updates 3-10 related wiki pages → updates `Resources/KB/index.md` → appends entry to `log.md` → moves raw source to destination.
- **Query** (v2, deferred) — `process-query` skill. Reads wiki, synthesizes answer with citations, optionally files answer back as new wiki page.
- **Lint** — `process-lint` skill. Periodic health check: source: validation (file exists + SHA matches + content match), orphan wiki pages, index gaps, log continuity, stale pages.
  - Pass T (2026-08-18, Hermes P3): weekly telemetry vocabulary and coverage check over the three governance sinks; see `process-lint/SKILL.md` Pass T. Origin: [[2026-08-17-hermes-p3-telemetry-integrity-plan]].

### Utility files

- **`Resources/KB/index.md`** — content catalog of every `#wiki`-tagged page; updated on every Ingest
- **`log.md`** at vault root — chronological append-only record; never edit existing entries
- **MOCs in `Resources/KB/`** — topical hubs; each is a wiki-layer page

### Source citation requirement (`source:` field)

Every wiki page (file tagged `#wiki`) MUST carry a `source:` frontmatter field — array of objects pointing to the raw-layer documents the page synthesizes. Schema:

```yaml
source:
  - path: "Clippings/some-article.md"     # vault-relative path to raw doc
    type: clipping                          # clipping | work-artifact | daily-note | external | inbox-item | wiki-derived | generated
    anchor: "## Section Title"              # optional heading within source
    sha256: "a1b2c3d4..."                   # SHA-256 of source bytes at ingest time (M2 crypto binding); OMIT for type: generated
    ingested_at: "2026-05-10T20:30:00Z"
```

This is enforced at three layers (see Wiki Layer Invariants below).

**`type: generated` exemption (2026-05-30, ensemble decision):** auto-generated source files (script outputs like `registry.json`) are LIVE DATA, not immutable curated sources — SHA-pinning them produces perpetual false `SOURCE_DRIFT` on every regeneration. A source entry with `type: generated` omits `sha256`; all three enforcement layers skip the SHA truth-gate for it while still enforcing path-existence (a generated source must still exist on disk). The citation system stays strict for every real curated source. Rationale + alternatives weighed: [[finding_volatile_files_unsuitable_as_source]].


## Wiki Layer Invariants

Three enforcement layers protect wiki integrity against LLM fabrication (the empirically-documented risk in this vault — see `feedback_main_session_can_fabricate_inventory.md` and siblings):

1. **Skill-level (`process-ingest` Step-4 hard gate)** — skill computes SHA of raw source bytes via Read tool BEFORE writing wiki page; commits hash to source: field. Cannot find supporting text → halts with `CITATION_NOT_FOUND` rather than synthesizing.
2. **Hook-level (`wiki-citation-check.py` PostToolUse Write)** — on every Write to a `#wiki`-tagged file: verifies source: field present + non-empty + each `path` exists on disk + recomputes SHA and compares to committed `sha256`. Mismatch → advisory `SOURCE_DRIFT` warning via additionalContext, non-blocking (ruled advisory by Wiktor 2026-08-22 on the 29.2%-would-block measurement in `.claude/scripts/wiki_citation_baseline.py`; doctrine synced to the hook's actual behavior 2026-08-31).
3. **Lint-level (`process-lint` Pass A)** — periodic re-verification of all wiki pages: file existence + hash match + anchor heading + noun-overlap content match. Findings: `ORPHAN_CITATION`, `MISSING_ANCHOR`, `WEAK_CITATION`, `MISSING_SOURCE`, `SOURCE_DRIFT`.

**Bootstrap mode (`wiki_status: bootstrap`):** new `#wiki` pages start as `bootstrap`. Wiktor reviews and promotes to `wiki_status: ratified`. When ≥10 ratified entries exist, process-ingest unlocks full LLM-authorship mode. Until then: each new wiki page is bootstrap-marked and surfaces for Wiktor's review.

