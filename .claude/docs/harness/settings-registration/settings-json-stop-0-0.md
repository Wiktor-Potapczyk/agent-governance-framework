---
component: "settings.json:Stop[0.0]"
kind: "settings-registration"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# settings-registration: settings.json:Stop[0.0]

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

Ralph Loop Stop Hook - Windows PowerShell reimplementation
Replaces bash stop-hook.sh which requires jq/cat/sed unavailable in hook context.
Registered in .claude/settings.json as a Stop hook alongside the plugin's bash hook.
The bash hook fails (non-blocking); this hook succeeds and blocks the session.

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

This registration is declared in `.claude/settings.json` (.claude/settings.json). It registers hook event `Stop` (matcher: None) with command `powershell -ExecutionPolicy Bypass -NonInteractive -File "C:\\Users\\WiktorPotapczyk\\Desktop\\Vault\\.claude\\hooks\\ralph-stop-hook.ps1"`.

(template-derived from the registration's reachability detail; not hand prose)
<!-- PROSE:END -->
