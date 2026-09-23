---
component: "_governance_logger"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: _governance_logger

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/_governance_logger.py`
- **Provenance:** authored-in-harness
- **Reachability:** `EVD-005` (.claude/hooks/bias-guard.py), `EVD-005` (.claude/hooks/checkpoint.py), `EVD-005` (.claude/hooks/post-compact.py), `EVD-005` (.claude/hooks/pre-compact.py), `EVD-005` (.claude/hooks/prose-codes-check.py), `EVD-005` (.claude/hooks/qmd-recall-nudge.py)
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:**
  - inbound imports bias-guard
  - inbound imports checkpoint
  - inbound imports post-compact
  - inbound imports pre-compact
  - inbound imports prose-codes-check
  - inbound imports qmd-recall-nudge
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Shared hook self-logging helper (E1, silent-zero instrumentation fix, 2026-05-30).

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

The shared self-logging helper behind hook-activity.jsonl. It does nothing on its own: a host hook calls log_fire(hook, decision, detail, session), and one JSON record with ts, event "hook_fire", the hook name, the decision, detail truncated to 200 chars, and the session is appended (.claude/hooks/_governance_logger.py:153). It never raises and never writes stderr, because hook stderr surfaces into session transcripts (.claude/hooks/_governance_logger.py:172).

Destination resolution mirrors _event_emit: a HOOK_ACTIVITY_LOG_PATH override wins; otherwise a call from inside an un-redirected unittest.TestCase falls back to a per-process temp file, added after one hooks-suite run was measured writing 117 synthetic records into the live stream (.claude/hooks/_governance_logger.py:92).

session_from(payload) recovers a real session id from a hook payload, trying session_id first and then the transcript filename stem, and returns None rather than a placeholder when the payload carries no identity (.claude/hooks/_governance_logger.py:123).
<!-- PROSE:END -->
