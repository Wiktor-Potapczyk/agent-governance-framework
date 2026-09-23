---
component: "post-compact"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: post-compact

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/post-compact.py`
- **Provenance:** authored-in-harness
- **Reachability:** `EVD-001` (.claude/settings.json)
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:**
  - inbound registered_in settings.json
  - outbound imports _event_emit
  - outbound imports _governance_logger
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

PostCompact hook — record compaction completion + staleness marker (Phase D dim1-C5).

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

Fires on PostCompact (registered in `.claude/settings.json` with an empty matcher), after a context compaction completes. It reads the compaction reason and session id from the stdin payload (`.claude/hooks/post-compact.py:35`). It deliberately injects no context: PostCompact rejects `additionalContext`, so this hook only records and flags (`.claude/hooks/post-compact.py:13`).

It emits three things: a `log_fire` record with decision "compacted" into `hook-activity.jsonl` (`.claude/hooks/post-compact.py:46`), a schema v2 "compaction" event into `governance-log.jsonl` via `_event_emit` (`.claude/hooks/post-compact.py:54`), and a staleness marker at `_state/last-compact.json` telling SessionStart and process-lint that the qmd index and STATE.md may be stale (`.claude/hooks/post-compact.py:66`).

Output is an empty JSON object on stdout and exit 0 always; every step is individually wrapped so the hook never crashes the session (`.claude/hooks/post-compact.py:78`).
<!-- PROSE:END -->
