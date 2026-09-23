---
component: "mcp-qmd-health-probe"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: mcp-qmd-health-probe

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/mcp-qmd-health-probe.py`
- **Provenance:** authored-in-harness
- **Reachability:** none recorded; blocked: `BLK-001`
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:** (no edges recorded)
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

mcp-qmd-health-probe.py: SessionStart health probe for the qmd recall layer.

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

A SessionStart probe on the `startup` and `resume` matchers (45-second registration timeout). It resolves the qmd CLI dynamically from `.mcp.json` on every run, taking the configured command, the first `.js` args element, and the server's env block (`.claude/hooks/mcp-qmd-health-probe.py:88`); if resolution fails it emits a loud "recall-layer health UNKNOWN" warning rather than passing silently (`.claude/hooks/mcp-qmd-health-probe.py:330`).

The status probe runs `qmd status` with a 20-second cap (`.claude/hooks/mcp-qmd-health-probe.py:55`, `.claude/hooks/mcp-qmd-health-probe.py:158`). On failure it appends an ISO failure timestamp into the shared circuit-breaker state file, in the exact shape `mcp-circuit-breaker.py` consumes, plus a `last_probe_failure` detail key (`.claude/hooks/mcp-qmd-health-probe.py:223`), and warns via SessionStart `additionalContext` that the recall layer is unreachable and Grep/Read is the fallback (`.claude/hooks/mcp-qmd-health-probe.py:342`). Success stamps `last_probe_ok_at` and leaves the failures list untouched (`.claude/hooks/mcp-qmd-health-probe.py:243`).

Only after a passing status check does it run a second, independent query-path probe, `query "hook" --no-rerank -c agr-kb`, under its own 19-second cap (`.claude/hooks/mcp-qmd-health-probe.py:138`, `.claude/hooks/mcp-qmd-health-probe.py:81`). A query failure records a `last_query_probe_failure` sibling key without touching the shared failures list (`.claude/hooks/mcp-qmd-health-probe.py:268`) and emits its own warning (`.claude/hooks/mcp-qmd-health-probe.py:379`). Every branch exits 0, and every verdict is logged via `log_fire` (`.claude/hooks/mcp-qmd-health-probe.py:304`).
<!-- PROSE:END -->
