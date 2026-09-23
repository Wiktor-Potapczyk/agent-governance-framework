---
component: "_unicode_hygiene"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: _unicode_hygiene

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/_unicode_hygiene.py`
- **Provenance:** authored-in-harness
- **Reachability:** none recorded; blocked: `BLK-001`
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:**
  - inbound mentioned_in_prose process-ingest [unresolved: prose mention only]
  - inbound mentioned_in_prose process-lint [unresolved: prose mention only]
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

_unicode_hygiene.py - shared Unicode-hygiene detector (Hermes P5, 2026-08-18).

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

Shared detector for the invisible and bidirectional character classes that make a raw file a prompt-injection carrier; its consumers are the unicode-hygiene-check PostToolUse hook, process-lint Pass M, and process-ingest Step 1.5 (.claude/hooks/_unicode_hygiene.py:7). One class table defines eight classes (bidi overrides and isolates, bidi marks, zero-width characters, BOM by position, soft hyphen, remaining category-Cf) with warning or advisory severity (.claude/hooks/_unicode_hygiene.py:34).

scan_text returns one finding per occurrence with class, codepoint, and 1-based line and column (.claude/hooks/_unicode_hygiene.py:97). scan_file reads raw bytes with one Windows long-path retry through the extended-length prefix and returns readable=False with the error instead of raising, so callers must surface an unscanned file rather than silently skip it (.claude/hooks/_unicode_hygiene.py:157, .claude/hooks/_unicode_hygiene.py:135).

sanitize_text removes every target-class character from in-memory text and returns a removal manifest with the same coordinates scan_text reports. The module deliberately has no file-write API: the raw layer on disk is never modified (.claude/hooks/_unicode_hygiene.py:182).
<!-- PROSE:END -->
