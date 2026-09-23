---
component: "settings.local.json:SessionStart[2.0]"
kind: "settings-registration"
source_inventory_generated_at: "2026-09-15T09:07:05Z"
---

# settings-registration: settings.local.json:SessionStart[2.0]

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

Origin: O4 of Projects/Agent-Governance-Research/work/2026-08-30-harness-spec-objectives.md.
Generalizes .claude/hooks/registry-staleness-check.py's age-threshold pattern (one
artifact, one max age) into a declarative manifest of many artifacts, rather than
cloning a new one-off script per artifact (per R5, extend-not-clone).

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

This registration is declared in `.claude/settings.local.json` (.claude/settings.local.json). It registers hook event `SessionStart` (matcher: None) with command `"C:\\Program Files\\Python314\\python.exe" "C:\\Users\\WiktorPotapczyk\\Desktop\\Vault\\.claude\\scripts\\staleness_check.py" --hook`.

(template-derived from the registration's reachability detail; not hand prose)
<!-- PROSE:END -->
