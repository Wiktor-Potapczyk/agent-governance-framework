---
component: "aggregate-write-guard"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: aggregate-write-guard

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/aggregate-write-guard.py`
- **Provenance:** authored-in-harness
- **Reachability:** none recorded; blocked: `BLK-001`
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:**
  - inbound mentioned_in_prose CLAUDE.md [unresolved: prose mention only]
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

aggregate-write-guard.py: PreToolUse guard (matcher: Write|Edit|MultiEdit)
protecting the memory-layer aggregates from a wholesale-loss write.

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

This PreToolUse guard fires on Write, Edit, and MultiEdit; main() re-checks the tool name and exits silently for anything else (.claude/hooks/aggregate-write-guard.py:421). It acts only on three exact normalized paths, classified by classify_target: the MEMORY.md head index and the two append-only jsonl aggregate logs (.claude/hooks/aggregate-write-guard.py:162). For each call it computes the effective post-write content for all three tool shapes instead of branching on tool identity, applying Edit and MultiEdit edits in sequence against the current on-disk bytes (.claude/hooks/aggregate-write-guard.py:208).

For MEMORY.md it collects the citations the write would drop and denies only when a dropped citation's target file still exists on disk and no sibling memory file cites it, which makes "write the topic file first, then shrink the head" the enforced safe order (.claude/hooks/aggregate-write-guard.py:312). For the jsonl logs it applies one rule regardless of tool: the proposed content must keep the current content as an exact prefix, so growth is tail-only with order preserved (.claude/hooks/aggregate-write-guard.py:330).

A deny is emitted as hookSpecificOutput.permissionDecision "deny" with a permissionDecisionReason (.claude/hooks/aggregate-write-guard.py:345). Both allow and deny verdicts on a protected path are logged to hook-activity.jsonl via _governance_logger.log_fire (.claude/hooks/aggregate-write-guard.py:392), and the exit code is 0 always: any unexpected exception fails toward allow (.claude/hooks/aggregate-write-guard.py:469).
<!-- PROSE:END -->
