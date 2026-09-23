---
component: "settings.local.json:PreToolUse[8.0]"
kind: "settings-registration"
source_inventory_generated_at: "2026-09-15T09:07:05Z"
---

# settings-registration: settings.local.json:PreToolUse[8.0]

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/settings.local.json`
- **Provenance:** authored-in-harness
- **Reachability:** `EVD-001` (.claude/settings.local.json), `EVD-009` (.claude/settings.local.json)
- **Usage:** Recorded use count 64 (source: `hook-activity.jsonl:hook_fire.hook (via resolved hook registration)`). First seen 2026-08-08T13:17:38; last seen 2026-09-09T17:28:49. Days since last use: 5; dormant: false.
- **Edges:**
  - inbound declared_in settings.local.json
  - inbound registered_in settings.local.json
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

aggregate-write-guard.py: PreToolUse guard (matcher: Write|Edit|MultiEdit)
protecting the memory-layer aggregates from a wholesale-loss write.

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

This registration is declared in `.claude/settings.local.json` (.claude/settings.local.json). It registers hook event `PreToolUse` (matcher: 'Write|Edit|MultiEdit') with command `"C:\\Program Files\\Python314\\python.exe" "C:\\Users\\WiktorPotapczyk\\Desktop\\Vault\\.claude\\hooks\\aggregate-write-guard.py"`.

(template-derived from the registration's reachability detail; not hand prose)
<!-- PROSE:END -->
