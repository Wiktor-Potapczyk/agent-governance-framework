---
component: "proactivity-check"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: proactivity-check

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/proactivity-check.py`
- **Provenance:** authored-in-harness
- **Reachability:** none recorded; blocked: `BLK-001`
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:** (no edges recorded)
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Stop hook: detect idle-wait verdicts and block them when reversible task_plan items exist.

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

Fires on Stop (registered in `.claude/settings.local.json` with an empty matcher). It reads `transcript_path` from the Stop payload (`.claude/hooks/proactivity-check.py:188`), rebuilds the text of the most recent assistant turn only, bounded by the last user message (`.claude/hooks/proactivity-check.py:102`), and searches it for idle-wait markers such as STAND-DOWN, "awaiting Wiktor", or "Standing by" (`.claude/hooks/proactivity-check.py:45`).

On a marker hit it applies two overrides before acting: a user stop directive within about 200 characters of the marker legitimizes the idle-wait (`.claude/hooks/proactivity-check.py:148`), and it scans `Projects/*/task_plan.md` for open `- [ ]` items, dropping any line that carries a Wiktor-gate marker (`.claude/hooks/proactivity-check.py:159`). Only when an idle marker, no stop directive, and at least one reversible open item coincide does it print a JSON block decision listing up to five reversible items (`.claude/hooks/proactivity-check.py:224`, print at `.claude/hooks/proactivity-check.py:248`).

Every run logs a fire to `hook-activity.jsonl`, and a block logs a second record with the reversible-item count (`.claude/hooks/proactivity-check.py:198`, `.claude/hooks/proactivity-check.py:240`). Any unexpected condition exits 0: better to let the turn complete than to block on a hook bug (`.claude/hooks/proactivity-check.py:29`).
<!-- PROSE:END -->
