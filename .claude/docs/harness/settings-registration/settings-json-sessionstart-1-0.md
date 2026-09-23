---
component: "settings.json:SessionStart[1.0]"
kind: "settings-registration"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# settings-registration: settings.json:SessionStart[1.0]

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

SessionStart hook (matcher: compact) — inject saved state after compaction
Reads the recovery file written by pre-compact.sh and injects it into context.
Also emits session_start event with source=compact to governance-log.jsonl
(observability v2 gap #1 fix 2026-04-19).

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

This registration is declared in `.claude/settings.json` (.claude/settings.json). It registers hook event `SessionStart` (matcher: 'compact') with command `bash "C:/Users/WiktorPotapczyk/Desktop/Vault/.claude/hooks/restore-compact.sh"`.

(template-derived from the registration's reachability detail; not hand prose)
<!-- PROSE:END -->
