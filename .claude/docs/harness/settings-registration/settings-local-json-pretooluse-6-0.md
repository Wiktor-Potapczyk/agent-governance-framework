---
component: "settings.local.json:PreToolUse[6.0]"
kind: "settings-registration"
source_inventory_generated_at: "2026-09-15T09:07:05Z"
---

# settings-registration: settings.local.json:PreToolUse[6.0]

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

mcp-circuit-breaker.py — PreToolUse guard for MCP tool calls (ECC-LEARN-E1).

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

This registration is declared in `.claude/settings.local.json` (.claude/settings.local.json). It registers hook event `PreToolUse` (matcher: 'mcp__.*') with command `"C:\\Program Files\\Python314\\python.exe" "C:\\Users\\WiktorPotapczyk\\Desktop\\Vault\\.claude\\hooks\\mcp-circuit-breaker.py"`.

(template-derived from the registration's reachability detail; not hand prose)
<!-- PROSE:END -->
