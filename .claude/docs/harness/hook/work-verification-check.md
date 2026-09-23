---
component: "work-verification-check"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: work-verification-check

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/work-verification-check.py`
- **Provenance:** authored-in-harness
- **Reachability:** none recorded; blocked: `BLK-001`
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:**
  - inbound mentioned_in_prose CLAUDE.md [unresolved: prose mention only]
  - inbound mentioned_in_prose process-governance-mine [unresolved: prose mention only]
  - inbound mentioned_in_prose process-pentest [unresolved: prose mention only]
  - inbound mentioned_in_prose process-qa [unresolved: prose mention only]
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Work Verification Check - Stop Hook
Forces actual execution and autonomous exhaustion before completing.

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

A Stop hook. It reads the last 200 KB of the transcript (.claude/hooks/work-verification-check.py:25, .claude/hooks/work-verification-check.py:103), reconstructs the last assistant turn's tool_use list, and skips retries via `stop_hook_active` (.claude/hooks/work-verification-check.py:85). Every invocation logs a fire record through `_governance_logger` (.claude/hooks/work-verification-check.py:91).

Three checks block by printing `{"decision": "block", "reason": ...}`. CHECK 1 blocks a QA or PENTEST report produced via the process skill with zero execution tools in the turn, suppressed when the QA ran inside a Workflow whose tools are invisible to the main transcript (.claude/hooks/work-verification-check.py:343, .claude/hooks/work-verification-check.py:369). CHECK 1b blocks an inline QA or pentest verdict on a non-Quick task that never invoked the matching process skill (.claude/hooks/work-verification-check.py:390). CHECK 2 blocks a response that asks the user for help after fewer than 3 tool uses, injecting the self-interrogation questions (.claude/hooks/work-verification-check.py:615).

The rest is telemetry. CHECK 4 detects write-claims with no matching Write trace and no file on disk, emitting `fabrication_detected` events and a stderr warning, non-blocking by design (.claude/hooks/work-verification-check.py:441, .claude/hooks/work-verification-check.py:607). CHECK 3 logs a soft warn event when a non-Quick turn used zero tools (.claude/hooks/work-verification-check.py:645). Events go to governance-log.jsonl via `_event_emit` (.claude/hooks/work-verification-check.py:70).
<!-- PROSE:END -->
