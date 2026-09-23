---
component: "memory-context-guard"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: memory-context-guard

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/memory-context-guard.py`
- **Provenance:** authored-in-harness
- **Reachability:** none recorded; blocked: `BLK-001`
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:**
  - inbound mentioned_in_prose CLAUDE.md [unresolved: prose mention only]
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

memory-context-guard.py: PreToolUse advisory guard (matcher: Write|Edit|MultiEdit)
for writes into the memory folder. Hermes P2 Mechanism A.

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

A PreToolUse advisory guard under the `Write|Edit|MultiEdit` matcher. Any target outside the memory folder exits 0 immediately; the scope test is a normalized prefix match with a trailing separator, so a sibling folder like `memory-extra` never matches (`.claude/hooks/memory-context-guard.py:92`, `.claude/hooks/memory-context-guard.py:273`).

For an in-scope write it classifies the context in two tiers: the payload `agent_type` field first, then a scrape of the agent frontmatter at the head of `transcript_path` as fallback (`.claude/hooks/memory-context-guard.py:153`, `.claude/hooks/memory-context-guard.py:108`). It appends exactly one JSONL record per event, warn and clean alike, to `aggregates/memory-context-warnings.jsonl` (`.claude/hooks/memory-context-guard.py:188`, `.claude/hooks/memory-context-guard.py:280`), and zeroes the persistence counter that memory-nudge.py reads, with an atomic tmp-then-replace write (`.claude/hooks/memory-context-guard.py:199`).

A subagent context gets `permissionDecision: "allow"` plus a caution that the memory folder is main-session-owned; it is never a deny (`.claude/hooks/memory-context-guard.py:228`). A main-session write gets the log record only, no message (`.claude/hooks/memory-context-guard.py:277`). Any internal exception fails toward allow with exit 0 (`.claude/hooks/memory-context-guard.py:295`).
<!-- PROSE:END -->
