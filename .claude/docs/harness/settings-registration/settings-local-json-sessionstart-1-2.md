---
component: "settings.local.json:SessionStart[1.2]"
kind: "settings-registration"
source_inventory_generated_at: "2026-09-15T09:07:05Z"
---

# settings-registration: settings.local.json:SessionStart[1.2]

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/settings.local.json`
- **Provenance:** authored-in-harness
- **Reachability:** `EVD-001` (.claude/settings.local.json), `EVD-009` (.claude/settings.local.json)
- **Usage:** Recorded use count 835 (source: `hook-activity.jsonl:hook_fire.hook (via resolved hook registration)`). First seen 2026-05-30T02:41:49; last seen 2026-09-14T19:26:10. Days since last use: 0; dormant: false.
- **Edges:**
  - inbound declared_in settings.local.json
  - inbound registered_in settings.local.json
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

SessionStart cadence trigger for /process-lint, /process-governance-mine, and the rolling setup-audit (2026-06-08).

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

This registration is declared in `.claude/settings.local.json` (.claude/settings.local.json). It registers hook event `SessionStart` (matcher: 'resume') with command `"C:\\Program Files\\Python314\\python.exe" "C:\\Users\\WiktorPotapczyk\\Desktop\\Vault\\.claude\\hooks\\lint-cadence-trigger.py"`.

(template-derived from the registration's reachability detail; not hand prose)
<!-- PROSE:END -->
