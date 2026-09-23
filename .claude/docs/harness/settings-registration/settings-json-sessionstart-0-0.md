---
component: "settings.json:SessionStart[0.0]"
kind: "settings-registration"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# settings-registration: settings.json:SessionStart[0.0]

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/settings.json`
- **Provenance:** authored-in-harness
- **Reachability:** `EVD-009` (.claude/settings.json)
- **Usage:** No telemetry path exists for this row: the registration does not resolve to a trackable component (sentinel `UNRESOLVED_REGISTRATION`).
- **Edges:**
  - inbound declared_in settings.json
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

SessionStart hook (matcher: startup) — remind Claude to read STATE.md on fresh sessions
P1-B (2026-04-09): Also writes session_start event to governance-log.jsonl for session boundary detection

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

This registration is declared in `.claude/settings.json` (.claude/settings.json). It registers hook event `SessionStart` (matcher: 'startup') with command `bash "C:/Users/WiktorPotapczyk/Desktop/Vault/.claude/hooks/session-start.sh"`.

(template-derived from the registration's reachability detail; not hand prose)
<!-- PROSE:END -->
