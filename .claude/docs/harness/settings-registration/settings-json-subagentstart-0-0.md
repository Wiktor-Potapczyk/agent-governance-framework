---
component: "settings.json:SubagentStart[0.0]"
kind: "settings-registration"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# settings-registration: settings.json:SubagentStart[0.0]

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/settings.json`
- **Provenance:** authored-in-harness
- **Reachability:** `EVD-001` (.claude/settings.json), `EVD-009` (.claude/settings.json)
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook (via resolved hook registration)`).
- **Edges:**
  - inbound declared_in settings.json
  - inbound registered_in settings.json
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

SubagentStart hook — inject Blind Analysis Rule reminder into evaluator agents.

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

This registration is declared in `.claude/settings.json` (.claude/settings.json). It registers hook event `SubagentStart` (matcher: None) with command `"C:\\Program Files\\Python314\\python.exe" "C:\\Users\\WiktorPotapczyk\\Desktop\\Vault\\.claude\\hooks\\bias-guard.py"`.

(template-derived from the registration's reachability detail; not hand prose)
<!-- PROSE:END -->
