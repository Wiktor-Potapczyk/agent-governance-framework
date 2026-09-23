---
component: "settings.local.json:Stop[0.13]"
kind: "settings-registration"
source_inventory_generated_at: "2026-09-15T09:07:05Z"
---

# settings-registration: settings.local.json:Stop[0.13]

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/settings.local.json`
- **Provenance:** authored-in-harness
- **Reachability:** `EVD-001` (.claude/settings.local.json), `EVD-009` (.claude/settings.local.json)
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook (via resolved hook registration)`).
- **Edges:**
  - inbound declared_in settings.local.json
  - inbound registered_in settings.local.json
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

memory-nudge.py: memory-persistence counter and nudge. Hermes P2 Mechanism B.

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

This registration is declared in `.claude/settings.local.json` (.claude/settings.local.json). It registers hook event `Stop` (matcher: None) with command `"C:\\Program Files\\Python314\\python.exe" "C:\\Users\\WiktorPotapczyk\\Desktop\\Vault\\.claude\\hooks\\memory-nudge.py"`.

(template-derived from the registration's reachability detail; not hand prose)
<!-- PROSE:END -->
