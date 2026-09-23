---
component: "settings.local.json:Stop[1.0]"
kind: "settings-registration"
source_inventory_generated_at: "2026-09-15T09:07:05Z"
---

# settings-registration: settings.local.json:Stop[1.0]

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/settings.local.json`
- **Provenance:** authored-in-harness
- **Reachability:** `EVD-001` (.claude/settings.local.json), `EVD-009` (.claude/settings.local.json)
- **Usage:** Recorded use count 1449 (source: `hook-activity.jsonl:hook_fire.hook (via resolved hook registration)`). First seen 2026-08-27T11:29:46; last seen 2026-09-15T11:04:49. Days since last use: 0; dormant: false.
- **Edges:**
  - inbound declared_in settings.local.json
  - inbound registered_in settings.local.json
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

WHY A STOP HOOK AND NOT A WRITE HOOK. This vault already ran the experiment.
`em-dash-guard.py` is a Stop hook returning exit 2; its own activity log shows
153 blocks against 1,386 allows, and the behaviour it polices has held.
`plain-language-guard.py` is PostToolUse and warn-only; it logged 446 in-scope
writes, 266 of them carrying findings, and changed nothing. That guard's own
docstring record

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

This registration is declared in `.claude/settings.local.json` (.claude/settings.local.json). It registers hook event `Stop` (matcher: None) with command `"C:\\Program Files\\Python314\\python.exe" "C:\\Users\\WiktorPotapczyk\\Desktop\\Vault\\.claude\\hooks\\reply-style-guard.py"`.

(template-derived from the registration's reachability detail; not hand prose)
<!-- PROSE:END -->
