---
component: "settings.local.json:SessionStart[0.7]"
kind: "settings-registration"
source_inventory_generated_at: "2026-09-15T09:07:05Z"
---

# settings-registration: settings.local.json:SessionStart[0.7]

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/settings.local.json`
- **Provenance:** authored-in-harness
- **Reachability:** `EVD-001` (.claude/settings.local.json), `EVD-009` (.claude/settings.local.json)
- **Usage:** Recorded use count 404 (source: `hook-activity.jsonl:hook_fire.hook (via resolved hook registration)`). First seen 2026-08-01T15:15:10; last seen 2026-09-15T10:10:15. Days since last use: 0; dormant: false.
- **Edges:**
  - inbound declared_in settings.local.json
  - inbound registered_in settings.local.json
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Empirical trigger (2026-07-29): the framework repo went 39 days and the research
repo 48 days without an update, and nothing surfaced it. Every other periodic
sweep in this vault (lint, governance-mine, work-triage, setup-audit, ingest)
emits an overdue reminder at SessionStart; repo maintenance emitted none, so the
lapse produced no signal until the owner happened to notice. This closes that
asym

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

This registration is declared in `.claude/settings.local.json` (.claude/settings.local.json). It registers hook event `SessionStart` (matcher: 'startup') with command `"C:\\Program Files\\Python314\\python.exe" "C:\\Users\\WiktorPotapczyk\\Desktop\\Vault\\.claude\\hooks\\repo-sync-cadence-trigger.py"`.

(template-derived from the registration's reachability detail; not hand prose)
<!-- PROSE:END -->
