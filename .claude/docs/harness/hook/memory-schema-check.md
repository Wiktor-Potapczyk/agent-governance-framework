---
component: "memory-schema-check"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: memory-schema-check

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/memory-schema-check.py`
- **Provenance:** authored-in-harness
- **Reachability:** none recorded; blocked: `BLK-001`
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:** (no edges recorded)
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

PostToolUse hook (matcher: Write|Edit) — check memory file schema.

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

A PostToolUse hook under the `Write|Edit` matcher. It exits silently unless the target is a memory `.md` file other than MEMORY.md (`.claude/hooks/memory-schema-check.py:36`, `.claude/hooks/memory-schema-check.py:258`).

It then checks the file just written, in two steps. Step 1 validates that the YAML frontmatter parses (PyYAML when available, fail-open otherwise); a parse error emits a `[MEMORY YAML INVALID]` warning with line and column and skips the field check (`.claude/hooks/memory-schema-check.py:75`, `.claude/hooks/memory-schema-check.py:282`). Step 2 checks the schema: the six required fields, valid `type` and `confidence` values, date formats, and the optional `superseded_by`, `last_accessed`, and `status` lifecycle fields (`.claude/hooks/memory-schema-check.py:24`, `.claude/hooks/memory-schema-check.py:162`).

All findings are joined into one `additionalContext` line; a clean file prints `{}` and nothing more (`.claude/hooks/memory-schema-check.py:315`, `.claude/hooks/memory-schema-check.py:318`). The hook never blocks (`.claude/hooks/memory-schema-check.py:8`), and each verdict (`yaml-invalid`, `no-frontmatter`, `warn`, `ok`) is logged to hook-activity.jsonl via `log_fire` (`.claude/hooks/memory-schema-check.py:216`).
<!-- PROSE:END -->
