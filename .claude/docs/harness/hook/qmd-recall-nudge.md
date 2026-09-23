---
component: "qmd-recall-nudge"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: qmd-recall-nudge

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/qmd-recall-nudge.py`
- **Provenance:** authored-in-harness
- **Reachability:** `EVD-001` (.claude/settings.json)
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:**
  - inbound registered_in settings.json
  - outbound imports _governance_logger
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

PreToolUse(Grep) nudge — raise qmd-recall consciousness (2026-06-01).

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

Fires on PreToolUse with a `Grep` matcher (registered in `.claude/settings.json`); the code re-checks the tool name and no-ops on anything else (`.claude/hooks/qmd-recall-nudge.py:49`). It inspects `tool_input.path` and classifies it as the memory corpus (a `/memory` directory under `/projects/`) or the agr-kb corpus (`Resources/KB`); any other path returns silently (`.claude/hooks/qmd-recall-nudge.py:31`).

On a corpus hit it logs a "nudge" fire (`.claude/hooks/qmd-recall-nudge.py:62`) and prints `hookSpecificOutput.additionalContext` with a one-line reminder that `mcp__qmd__query` usually serves a search better than raw Grep. The Grep still runs: the hook is warn-only and exits 0 on every path (`.claude/hooks/qmd-recall-nudge.py:80`, contract at `.claude/hooks/qmd-recall-nudge.py:10`).
<!-- PROSE:END -->
