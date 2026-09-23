---
component: "_haiku_summarize"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: _haiku_summarize

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/_haiku_summarize.py`
- **Provenance:** authored-in-harness
- **Reachability:** none recorded; blocked: `BLK-001`
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:** (no edges recorded)
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

_haiku_summarize.py: standalone worker, the Haiku error-event summarizer.

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

Standalone worker, not wired to any hook event: it is invoked explicitly as python _haiku_summarize.py with --session or --since-ts, and it refuses to run without one of those filters (.claude/hooks/_haiku_summarize.py:10, .claude/hooks/_haiku_summarize.py:456). It reads governance-log.jsonl and selects block, deny, qa_fail_reported, dark-zone, and warn events in scope (.claude/hooks/_haiku_summarize.py:80), skipping the current session when CLAUDE_SESSION_ID is set (.claude/hooks/_haiku_summarize.py:486).

For each event not already summarized (dedup key session:ts:event:hook, .claude/hooks/_haiku_summarize.py:147) it builds a prompt with few-shot examples and an untrusted-input fence, calls the pinned Haiku model through the claude CLI subprocess with a 60 s timeout (.claude/hooks/_haiku_summarize.py:75, .claude/hooks/_haiku_summarize.py:332), then cleans the reply and caps it at 30 words (.claude/hooks/_haiku_summarize.py:307).

Each summary is emitted back into the governance log as an error_summary event through _event_emit (.claude/hooks/_haiku_summarize.py:397). Haiku calls are hard-capped at 20 per run (.claude/hooks/_haiku_summarize.py:85), failures land in haiku-summarize.log, and the process always exits 0 so it never disrupts a caller (.claude/hooks/_haiku_summarize.py:545).
<!-- PROSE:END -->
