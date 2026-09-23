---
component: "settings.local.json:SubagentStop[0.1]"
kind: "settings-registration"
source_inventory_generated_at: "2026-09-15T09:07:05Z"
---

# settings-registration: settings.local.json:SubagentStop[0.1]

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/settings.local.json`
- **Provenance:** authored-in-harness
- **Reachability:** `EVD-001` (.claude/settings.local.json), `EVD-009` (.claude/settings.local.json)
- **Usage:** Recorded use count 23336 (source: `hook-activity.jsonl:hook_fire.hook (via resolved hook registration)`). First seen 2026-05-31T23:25:02; last seen 2026-09-15T11:03:13. Days since last use: 0; dormant: false.
- **Edges:**
  - inbound declared_in settings.local.json
  - inbound registered_in settings.local.json
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Empirical trigger (2026-05-26 W-D2 ensemble, loop iter 2):
- prompt-engineer sub-agent self-extended scope to mark its own task_plan ticket
  AND made a tag-policy decision (ensemble → unclassified-pending) — both outside
  the design-only ticket scope.
- Substance was accurate; scope was wrong. Documented as the first scope-extension
  event in [[finding_subagent_reviewer_write_grant_pattern]].

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

This registration is declared in `.claude/settings.local.json` (.claude/settings.local.json). It registers hook event `SubagentStop` (matcher: None) with command `"C:\\Program Files\\Python314\\python.exe" "C:\\Users\\WiktorPotapczyk\\Desktop\\Vault\\.claude\\hooks\\subagent-scope-check.py"`.

(template-derived from the registration's reachability detail; not hand prose)
<!-- PROSE:END -->
