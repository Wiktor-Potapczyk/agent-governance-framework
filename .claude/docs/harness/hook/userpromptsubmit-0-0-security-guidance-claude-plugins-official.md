---
component: "UserPromptSubmit[0.0]@security-guidance@claude-plugins-official"
kind: "hook"
source_inventory_generated_at: "2026-09-15T09:07:05Z"
---

# hook: UserPromptSubmit[0.0]@security-guidance@claude-plugins-official

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `C:/Users/WiktorPotapczyk/.claude/plugins/cache/claude-plugins-official/security-guidance/2.0.8/hooks/sg-python.sh`
- **Provenance:** plugin:claude-plugins-official/security-guidance
- **Reachability:** `EVD-007` (C:/Users/WiktorPotapczyk/.claude/plugins/cache/claude-plugins-official/security-guidance/2.0.8/hooks/hooks.json)
- **Usage:** No telemetry path exists for this row: plugin hook fires are not recorded in any harness sink (sentinel `NO_SOURCE_FOR_PLUGIN_HOOK`).
- **Edges:**
  - inbound registered_by_plugin plugin:claude-plugins-official/security-guidance
- **Twin state:** not-applicable
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Security review for Claude-generated code in three layers: instant pattern-based warnings on Edit/Write for known-dangerous constructs, an LLM-powered diff review when a turn ends, and an agentic commit reviewer covering injection, XSS, SSRF, hardcoded secrets, and 25+ other vulnerability classes, per its plugin.json and README. Installed as an always-on safety net over code the harness writes.

Upstream: `C:/Users/WiktorPotapczyk/.claude/plugins/cache/claude-plugins-official/security-guidance/2.0.7`

(plugin-level WHY; per-component WHY declined by ruling)

## How

UNFILLED-HOW (see tier policy in README.md; plugin-internal mechanism, upstream source at `C:/Users/WiktorPotapczyk/.claude/plugins/cache/claude-plugins-official/security-guidance/2.0.7/hooks/sg-python.sh`)
<!-- PROSE:END -->
