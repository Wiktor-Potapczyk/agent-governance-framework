---
component: "memory-dedup-check"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: memory-dedup-check

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/memory-dedup-check.py`
- **Provenance:** authored-in-harness
- **Reachability:** none recorded; blocked: `BLK-001`
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:** (no edges recorded)
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

PreToolUse hook (matcher: Write) — check for near-duplicate memory files.

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

A PreToolUse hook under the `Write` matcher. It exits silently unless the target is a memory `.md` file other than MEMORY.md under a `.claude/projects/*/memory/` path (`.claude/hooks/memory-dedup-check.py:16`, `.claude/hooks/memory-dedup-check.py:96`).

For a memory write it extracts the `description:` frontmatter field from the incoming content (`.claude/hooks/memory-dedup-check.py:43`), tokenizes words of three or more characters (`.claude/hooks/memory-dedup-check.py:38`), and computes Jaccard similarity against the description of every existing file in the same memory directory (`.claude/hooks/memory-dedup-check.py:64`, `.claude/hooks/memory-dedup-check.py:139`). Overlap at or above 0.65 flags a potential duplicate (`.claude/hooks/memory-dedup-check.py:13`, `.claude/hooks/memory-dedup-check.py:152`).

On a hit it prints an `additionalContext` warning naming the most similar existing file and suggesting an update instead of a new file; it never blocks the write (`.claude/hooks/memory-dedup-check.py:164`). Every verdict (warn, allow, or a skip with its reason) is logged via `log_fire`, placed after the memory-path gate on purpose so the flood of non-memory writes measures nothing (`.claude/hooks/memory-dedup-check.py:100`).
<!-- PROSE:END -->
