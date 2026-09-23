---
component: "process-ingest"
kind: "skill"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# skill: process-ingest

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/skills/process-ingest`
- **Provenance:** authored-in-harness
- **Reachability:** `EVD-004` (.claude/registry.json)
- **Usage:** Recorded use count 0 (source: `governance-log.jsonl:agent_dispatched.skill_context[]`).
- **Edges:**
  - inbound mentioned_in_prose process-lint [unresolved: prose mention only]
  - inbound mentioned_in_prose process-query [unresolved: prose mention only]
  - inbound cataloged_in registry.json
  - outbound mentions_in_prose _unicode_hygiene [unresolved: prose mention only]
  - outbound mentions_in_prose architect-reviewer [unresolved: prose mention only]
  - outbound mentions_in_prose inbox-auto-ingest [unresolved: prose mention only]
  - outbound mentions_in_prose index [unresolved: prose mention only]
  - outbound mentions_in_prose wiki-citation-check [unresolved: prose mention only]
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Use when a raw source document (Inbox/, Clippings/) needs to be integrated into the LLM-Wiki. Reads the source, computes SHA hash, writes summary wiki page with source citation, updates 3-10 related wiki pages, updates index.md + log.md. Auto-triggered by `inbox-auto-ingest.py` hook on Inbox writes; also manually invokable. Implements Karpathy LLM-Wiki Ingest operation with 3-layer fabrication mit

(machine-filled from rationale-index.json; extraction locus: frontmatter)

## How

Fires two ways: the inbox-auto-ingest.py hook triggers it on Inbox/ writes, and it is manually invokable on Clippings/ or Inbox/ files or any raw artifact needing wiki promotion (.claude/skills/process-ingest/SKILL.md:12, :14).

Tool surface: Read on the raw source, sectioned when large (.claude/skills/process-ingest/SKILL.md:35), the _unicode_hygiene scan that treats source text as data, never instructions (.claude/skills/process-ingest/SKILL.md:45), Bash to compute SHA-256 of the raw bytes (.claude/skills/process-ingest/SKILL.md:62), qmd query for related pages with the index.md fallback (.claude/skills/process-ingest/SKILL.md:72, :76), and Write/Edit for the wiki page, the 3 to 10 related pages, index.md, and log.md.

It must produce a wiki page whose frontmatter carries the source: array with path, anchor, and sha256 (.claude/skills/process-ingest/SKILL.md:102), an append-only INGEST-NNN log.md entry (.claude/skills/process-ingest/SKILL.md:158), and the closing INGEST REPORT block (.claude/skills/process-ingest/SKILL.md:212). Enforcement is layered: the Step 4 hard citation gate halts unanchored claims with CITATION_NOT_FOUND (.claude/skills/process-ingest/SKILL.md:85), and the wiki-citation-check.py hook blocks any wiki Write missing a valid source: field and blocks edits to existing log entries (.claude/skills/process-ingest/SKILL.md:27, :176).
<!-- PROSE:END -->
