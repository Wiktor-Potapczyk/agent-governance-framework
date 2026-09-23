---
component: "transition-gate-check"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: transition-gate-check

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/transition-gate-check.py`
- **Provenance:** authored-in-harness
- **Reachability:** none recorded; blocked: `BLK-001`
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:** (no edges recorded)
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

transition-gate-check.py — PreToolUse guard for SDLC phase-sentinel advances (Layer 1).

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

A PreToolUse guard on the `Write|Edit|MultiEdit` matcher, but it only concerns itself with SDLC phase sentinels: paths containing `sdlc-phase-` and ending `.json` (.claude/hooks/transition-gate-check.py:59). Any Edit or MultiEdit to a sentinel denies outright, because the write-only contract requires overwriting the whole file (.claude/hooks/transition-gate-check.py:103, .claude/hooks/transition-gate-check.py:115).

For a Write it parses `tool_input.content` as the proposed sentinel state (.claude/hooks/transition-gate-check.py:132), validates `current_phase` against the ten-phase order (.claude/hooks/transition-gate-check.py:37), lets advisory phases advance without evidence (.claude/hooks/transition-gate-check.py:158), and denies an advance into an enforced phase when the prior phase lacks `external_oracle` evidence in `completed_gates` (.claude/hooks/transition-gate-check.py:176). It fails closed when the on-disk sentinel is unreadable (.claude/hooks/transition-gate-check.py:155) but allows the first-ever write (.claude/hooks/transition-gate-check.py:152).

A deny is a stdout `permissionDecision: "deny"` payload (.claude/hooks/transition-gate-check.py:65) plus a `transition_gate_block` event appended to governance-log.jsonl via `_event_emit` (.claude/hooks/transition-gate-check.py:76). Deny rather than ask, because the vault runs universal bypassPermissions where an ask auto-allows (.claude/hooks/transition-gate-check.py:21). Exit code is always 0; the flagless production path runs `main()` and the self-test suite only runs on an explicit `--selftest` (.claude/hooks/transition-gate-check.py:232).
<!-- PROSE:END -->
