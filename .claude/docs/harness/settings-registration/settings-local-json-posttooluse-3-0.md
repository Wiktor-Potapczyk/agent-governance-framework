---
component: "settings.local.json:PostToolUse[3.0]"
kind: "settings-registration"
source_inventory_generated_at: "2026-09-15T09:07:05Z"
---

# settings-registration: settings.local.json:PostToolUse[3.0]

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/settings.local.json`
- **Provenance:** authored-in-harness
- **Reachability:** `EVD-001` (.claude/settings.local.json), `EVD-009` (.claude/settings.local.json)
- **Usage:** Recorded use count 13304 (source: `hook-activity.jsonl:hook_fire.hook (via resolved hook registration)`). First seen 2026-05-31T23:24:41; last seen 2026-09-08T16:31:31. Days since last use: 6; dormant: false.
- **Edges:**
  - inbound declared_in settings.local.json
  - inbound registered_in settings.local.json
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

wiki-citation-check.py — PostToolUse Write hook (M2 Layer 2).

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

This registration is declared in `.claude/settings.local.json` (.claude/settings.local.json). It registers hook event `PostToolUse` (matcher: 'Write|Edit') with command `"C:\\Program Files\\Python314\\python.exe" "C:\\Users\\WiktorPotapczyk\\Desktop\\Vault\\.claude\\hooks\\wiki-citation-check.py"`.

(template-derived from the registration's reachability detail; not hand prose)
<!-- PROSE:END -->
