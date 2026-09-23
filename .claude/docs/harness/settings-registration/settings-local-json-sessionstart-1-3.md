---
component: "settings.local.json:SessionStart[1.3]"
kind: "settings-registration"
source_inventory_generated_at: "2026-09-15T09:07:05Z"
---

# settings-registration: settings.local.json:SessionStart[1.3]

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

Session Start Logger - SessionStart Hook Helper
P1-B (2026-04-09): Writes a session_start event to governance-log.jsonl so
analytics scripts can detect session boundaries cleanly (instead of inferring
from first classification entry).

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

This registration is declared in `.claude/settings.local.json` (.claude/settings.local.json). It registers hook event `SessionStart` (matcher: 'resume') with command `"C:\\Program Files\\Python314\\python.exe" "C:\\Users\\WiktorPotapczyk\\Desktop\\Vault\\.claude\\hooks\\session-start-log.py"`.

(template-derived from the registration's reachability detail; not hand prose)
<!-- PROSE:END -->
