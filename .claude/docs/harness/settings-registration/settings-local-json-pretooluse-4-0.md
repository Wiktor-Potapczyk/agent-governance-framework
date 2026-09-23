---
component: "settings.local.json:PreToolUse[4.0]"
kind: "settings-registration"
source_inventory_generated_at: "2026-09-15T09:07:05Z"
---

# settings-registration: settings.local.json:PreToolUse[4.0]

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/settings.local.json`
- **Provenance:** authored-in-harness
- **Reachability:** `EVD-009` (.claude/settings.local.json)
- **Usage:** No telemetry path exists for this row: the registration does not resolve to a trackable component (sentinel `UNRESOLVED_REGISTRATION`).
- **Edges:**
  - inbound declared_in settings.local.json
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

PreToolUse hook (matcher: Write|Edit) — block writes containing forbidden tokens.

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

This registration is declared in `.claude/settings.local.json` (.claude/settings.local.json). It registers hook event `PreToolUse` (matcher: 'Write|Edit|MultiEdit') with command `"C:\\Program Files\\Python314\\python.exe" "C:\\Users\\WiktorPotapczyk\\Desktop\\Vault\\.claude\\scripts\\check_forbidden_tokens.py"`.

(template-derived from the registration's reachability detail; not hand prose)
<!-- PROSE:END -->
