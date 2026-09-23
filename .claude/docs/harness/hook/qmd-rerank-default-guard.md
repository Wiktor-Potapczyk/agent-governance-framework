---
component: "qmd-rerank-default-guard"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: qmd-rerank-default-guard

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/qmd-rerank-default-guard.py`
- **Provenance:** authored-in-harness
- **Reachability:** none recorded; blocked: `BLK-001`
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:** (no edges recorded)
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

qmd-rerank-default-guard.py: PreToolUse guard enforcing rerank:false on mcp__qmd__query.

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

Fires on PreToolUse with an exact `mcp__qmd__query` matcher (registered in `.claude/settings.local.json`); the code no-ops on any other tool name as a matcher-scope leak guard (`.claude/hooks/qmd-rerank-default-guard.py:104`). It parses `tool_input`, decoding a JSON-string form if needed (`.claude/hooks/qmd-rerank-default-guard.py:108`), and denies when `rerank` is absent or anything but the boolean `false`; an explicit `rerank: true` still denies, since true is exactly the hang-triggering value (`.claude/hooks/qmd-rerank-default-guard.py:85`).

The deny is emitted as `hookSpecificOutput.permissionDecision: "deny"` with a reason explaining the CPU-only rerank hang and instructing the caller to reissue with `rerank: false` (`.claude/hooks/qmd-rerank-default-guard.py:48`). Each deny also emits a governance-log event carrying a marker for whether rerank was absent or present but not false (`.claude/hooks/qmd-rerank-default-guard.py:115`). A compliant call passes silently, and the exit code is 0 on every path, fail-open (`.claude/hooks/qmd-rerank-default-guard.py:122`, `.claude/hooks/qmd-rerank-default-guard.py:99`).
<!-- PROSE:END -->
