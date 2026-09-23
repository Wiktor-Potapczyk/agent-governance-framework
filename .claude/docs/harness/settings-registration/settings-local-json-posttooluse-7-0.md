---
component: "settings.local.json:PostToolUse[7.0]"
kind: "settings-registration"
source_inventory_generated_at: "2026-09-15T09:07:05Z"
---

# settings-registration: settings.local.json:PostToolUse[7.0]

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/settings.local.json`
- **Provenance:** authored-in-harness
- **Reachability:** `EVD-001` (.claude/settings.local.json), `EVD-009` (.claude/settings.local.json)
- **Usage:** Recorded use count 1355 (source: `hook-activity.jsonl:hook_fire.hook (via resolved hook registration)`). First seen 2026-08-07T17:47:30; last seen 2026-09-15T11:04:37. Days since last use: 0; dormant: false.
- **Edges:**
  - inbound declared_in settings.local.json
  - inbound registered_in settings.local.json
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

WHY THIS EXISTS
---------------
The recurring defect: a new, accurate status block is written at the top of STATE.md or
task_plan.md, and the older entries below it are left describing the previous state. The
file then says two things, and which one a reader believes depends on where they stop
reading. A PM checkpoint reading only the top reports the work done; one reading further
down reports it 

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

This registration is declared in `.claude/settings.local.json` (.claude/settings.local.json). It registers hook event `PostToolUse` (matcher: 'Write|Edit') with command `"C:\\Program Files\\Python314\\python.exe" "C:\\Users\\WiktorPotapczyk\\Desktop\\Vault\\.claude\\hooks\\state-reconcile-check.py"`.

(template-derived from the registration's reachability detail; not hand prose)
<!-- PROSE:END -->
