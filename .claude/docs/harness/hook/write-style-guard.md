---
component: "write-style-guard"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: write-style-guard

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/write-style-guard.py`
- **Provenance:** authored-in-harness
- **Reachability:** none recorded; blocked: `BLK-001`
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:** (no edges recorded)
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

WHY THIS EXISTS SEPARATELY FROM plain-language-guard.py. That guard runs
PostToolUse. Its own docstring states the consequence plainly: "the write it is
scanning has already landed on disk", and "genuine write-time prevention would
need a separate PreToolUse companion hook, which is explicitly out of Stage 1
scope". This is that companion. The evidence that the distinction matters is in
that guard's own log: 446 in-scope writes, 266 carrying findings, nothing changed,
because a warning after the fact is free to ignore (.claude/hooks/write-style-guard.py:10).

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

A PreToolUse hook on the `Write|Edit|MultiEdit` matcher. It guards only the three documentation surfaces plain-language-guard.py already claims: `Projects/*/work/` excluding `work/backups/`, `Resources/KB/`, and the framework repo's docs and README (.claude/hooks/write-style-guard.py:86). For a Write it evaluates the whole proposed content; for an Edit only the replacement text this write introduces (.claude/hooks/write-style-guard.py:102).

The rule engine is imported from reply-style-guard.py so the reply surface and the file surface share one `strip_noise`, one `BOLD_SPAN`, and one `WORDLIST` and cannot drift (.claude/hooks/write-style-guard.py:76). `evaluate` strips code, tables, and structured blocks, then flags bold density at or above 33 spans per 1000 prose words on files of 50-plus prose words, plus any stock-AI wordlist hit (.claude/hooks/write-style-guard.py:141, .claude/hooks/write-style-guard.py:65).

A violation denies the write before it lands, with a `permissionDecision: "deny"` payload telling the author to rewrite (.claude/hooks/write-style-guard.py:213). The allow path is logged as well as the block path, via `_governance_logger.log_fire`, so the false-negative rate stays measurable (.claude/hooks/write-style-guard.py:115). Fail-open: any internal error logs a skip and allows the write (.claude/hooks/write-style-guard.py:190).
<!-- PROSE:END -->
