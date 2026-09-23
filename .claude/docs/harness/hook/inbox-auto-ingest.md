---
component: "inbox-auto-ingest"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: inbox-auto-ingest

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/inbox-auto-ingest.py`
- **Provenance:** authored-in-harness
- **Reachability:** none recorded; blocked: `BLK-001`
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:**
  - inbound mentioned_in_prose CLAUDE.md [unresolved: prose mention only]
  - inbound mentioned_in_prose process-ingest [unresolved: prose mention only]
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

inbox-auto-ingest.py — PostToolUse Write|Edit hook (M1 auto-trigger).

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

The hook fires on PostToolUse under the `Write|Edit` matcher. It exits unless the tool is Write or Edit (`.claude/hooks/inbox-auto-ingest.py:62`) and the target resolves to a vault-relative path starting with `Inbox/` or `Clippings/` (`.claude/hooks/inbox-auto-ingest.py:27`, `.claude/hooks/inbox-auto-ingest.py:71`). Housekeeping names such as `.gitkeep` and `desktop.ini` are excluded (`.claude/hooks/inbox-auto-ingest.py:28`).

On a match it appends a trigger record (timestamp, file, tool) to `.claude/hooks/aggregates/inbox-ingest-triggers.jsonl` (`.claude/hooks/inbox-auto-ingest.py:26`) and prints one PostToolUse `additionalContext` JSON line telling the next turn to invoke the `process-ingest` skill on the file, with the ingest steps spelled out (`.claude/hooks/inbox-auto-ingest.py:84`). It always returns 0 and cannot block the write (`.claude/hooks/inbox-auto-ingest.py:104`).
<!-- PROSE:END -->
