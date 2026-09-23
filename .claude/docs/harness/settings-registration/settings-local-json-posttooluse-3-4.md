---
component: "settings.local.json:PostToolUse[3.4]"
kind: "settings-registration"
source_inventory_generated_at: "2026-09-15T09:07:05Z"
---

# settings-registration: settings.local.json:PostToolUse[3.4]

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/settings.local.json`
- **Provenance:** authored-in-harness
- **Reachability:** `EVD-001` (.claude/settings.local.json), `EVD-009` (.claude/settings.local.json)
- **Usage:** Recorded use count 12 (source: `hook-activity.jsonl:hook_fire.hook (via resolved hook registration)`). First seen 2026-08-11T12:08:38; last seen 2026-09-09T22:03:19. Days since last use: 5; dormant: false.
- **Edges:**
  - inbound declared_in settings.local.json
  - inbound registered_in settings.local.json
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Mechanism A countermeasure from the caveman postmortem
(Projects/Agent-Governance-Research/work/2026-08-10-caveman-postmortem.md):
the caveman-lite rule survived four months while the pointer to its own origin
died, because CLAUDE.md requires no inline provenance the way wiki pages
require a source: field. This guard extends that discipline to the
constitution: a rule-shaped change to the vault-ro

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

This registration is declared in `.claude/settings.local.json` (.claude/settings.local.json). It registers hook event `PostToolUse` (matcher: 'Write|Edit') with command `"C:\\Program Files\\Python314\\python.exe" "C:\\Users\\WiktorPotapczyk\\Desktop\\Vault\\.claude\\hooks\\claude-md-provenance-check.py"`.

(template-derived from the registration's reachability detail; not hand prose)
<!-- PROSE:END -->
