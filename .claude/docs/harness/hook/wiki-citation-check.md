---
component: "wiki-citation-check"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: wiki-citation-check

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/wiki-citation-check.py`
- **Provenance:** authored-in-harness
- **Reachability:** none recorded; blocked: `BLK-001`
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:**
  - inbound mentioned_in_prose process-ingest [unresolved: prose mention only]
  - inbound mentioned_in_prose process-query [unresolved: prose mention only]
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

wiki-citation-check.py — PostToolUse Write hook (M2 Layer 2).

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

A PostToolUse hook on the `Write|Edit` matcher that re-checks the tool name (.claude/hooks/wiki-citation-check.py:83) and resolves the written path relative to the vault, exiting unless it is a wiki-layer path (.claude/hooks/wiki-citation-check.py:92). Resources/KB/ counts unconditionally; Notes/ and Projects/*/archive/ count only when the content carries the #wiki tag (.claude/hooks/wiki-citation-check.py:121). The pure logic lives in `_wiki_citation_logic.py`; this file is the thin I/O wrapper (.claude/hooks/wiki-citation-check.py:42).

It reads the written file back from disk, parses its `source:` frontmatter entries, and validates each one: field present and non-empty, cited path exists on disk, and the recorded SHA-256 matches the source file's current bytes, a truth gate rather than a format gate (.claude/hooks/wiki-citation-check.py:132, .claude/hooks/wiki-citation-check.py:12).

Findings emit one stdout `additionalContext` warning (.claude/hooks/wiki-citation-check.py:139); every decision is appended to `.claude/hooks/aggregates/wiki-citation-violations.jsonl` (.claude/hooks/wiki-citation-check.py:57) and a verdict record goes to hook-activity.jsonl (.claude/hooks/wiki-citation-check.py:100). The hook is advisory: it always returns 0 and the hard-block exit is disabled pending an empirical baseline (.claude/hooks/wiki-citation-check.py:21).
<!-- PROSE:END -->
