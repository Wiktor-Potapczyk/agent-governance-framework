---
component: "hook-write-regression-gate"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: hook-write-regression-gate

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/hook-write-regression-gate.py`
- **Provenance:** authored-in-harness
- **Reachability:** none recorded; blocked: `BLK-001`
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:**
  - inbound mentioned_in_prose process-governance-mine [unresolved: prose mention only]
  - inbound mentioned_in_prose process-lint [unresolved: prose mention only]
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

hook-write-regression-gate.py — PostToolUse Write|Edit regression gate for harness hook edits.

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

The hook fires on PostToolUse under the `Write|Edit` matcher (registered in `.claude/settings.local.json` with a 90s timeout). `main()` ignores every other tool (`.claude/hooks/hook-write-regression-gate.py:275`) and takes a fast exit unless the edited path is a `.py` file under `.claude/hooks/` outside the excluded `_state`, `archive`, `aggregates`, and `__pycache__` segments (`.claude/hooks/hook-write-regression-gate.py:46`, `.claude/hooks/hook-write-regression-gate.py:143`).

On a gated edit it acquires an atomic re-entrancy lock (`.claude/hooks/hook-write-regression-gate.py:101`), then runs the full pytest suite against the hooks directory with `-p no:cacheprovider` and a pinned `--rootdir`, capped at 120 seconds (`.claude/hooks/hook-write-regression-gate.py:192`, `.claude/hooks/hook-write-regression-gate.py:51`). If another gate run already holds the lock it logs a skip and stays silent, so concurrent edits do not fork-bomb the suite (`.claude/hooks/hook-write-regression-gate.py:285`).

Output is advisory only. A red suite emits a loud PostToolUse `additionalContext` warning carrying the pytest exit code and the last 12 log lines (`.claude/hooks/hook-write-regression-gate.py:315`); a gate failure (timeout, unrunnable pytest) warns as well (`.claude/hooks/hook-write-regression-gate.py:307`); a green suite logs `quiet`, or attaches generated asset-matrix findings when those exist (`.claude/hooks/hook-write-regression-gate.py:302`, `.claude/hooks/hook-write-regression-gate.py:296`). Every path exits 0 and never blocks (`.claude/hooks/hook-write-regression-gate.py:30`); each verdict lands in hook-activity.jsonl via `log_fire` (`.claude/hooks/hook-write-regression-gate.py:228`).
<!-- PROSE:END -->
