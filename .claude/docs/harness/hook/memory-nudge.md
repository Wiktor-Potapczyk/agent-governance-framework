---
component: "memory-nudge"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: memory-nudge

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/memory-nudge.py`
- **Provenance:** authored-in-harness
- **Reachability:** none recorded; blocked: `BLK-001`
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:**
  - inbound mentioned_in_prose CLAUDE.md [unresolved: prose mention only]
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

memory-nudge.py: memory-persistence counter and nudge. Hermes P2 Mechanism B.

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

One file with two registrations, on Stop (empty matcher) and on SessionStart (`startup` and `resume`), branching on the payload's `hook_event_name` (`.claude/hooks/memory-nudge.py:163`).

On Stop it increments `turns_since_memory_write` in `_state/memory-nudge.json` and prints nothing; a payload carrying `stop_hook_active: true` is a Stop-chain continuation and is not counted as a new turn (`.claude/hooks/memory-nudge.py:121`, `.claude/hooks/memory-nudge.py:123`). The counter is reset only by a real memory-folder write, which memory-context-guard.py performs at PreToolUse time (`.claude/hooks/memory-nudge.py:22`).

On SessionStart it emits one `additionalContext` nudge only when the counter has reached 10 and at least 10 turns have passed since the last-nudge watermark (`.claude/hooks/memory-nudge.py:136`, `.claude/hooks/memory-nudge.py:59`); the nudge text explicitly allows "nothing to save" as a correct outcome and forbids manufacturing entries (`.claude/hooks/memory-nudge.py:69`). State writes are atomic tmp-then-replace (`.claude/hooks/memory-nudge.py:107`), and every path exits 0 without ever blocking (`.claude/hooks/memory-nudge.py:44`).
<!-- PROSE:END -->
