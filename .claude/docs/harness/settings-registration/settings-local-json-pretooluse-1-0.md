---
component: "settings.local.json:PreToolUse[1.0]"
kind: "settings-registration"
source_inventory_generated_at: "2026-09-15T09:07:05Z"
---

# settings-registration: settings.local.json:PreToolUse[1.0]

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

Bash Safety Guard - PreToolUse Hook (matcher: Bash)
Blocks dangerous shell commands before execution.
Denies: rm -rf, force-push, credential exposure, destructive git ops, git-hook bypass
(--no-verify / -n on commit-class subcommands, -c core.hooksPath= overrides).

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

This registration is declared in `.claude/settings.local.json` (.claude/settings.local.json). It registers hook event `PreToolUse` (matcher: 'Bash') with command `"C:\\Program Files\\Python314\\python.exe" "C:\\Users\\WiktorPotapczyk\\Desktop\\Vault\\.claude\\hooks\\bash-safety-guard.py"`.

(template-derived from the registration's reachability detail; not hand prose)
<!-- PROSE:END -->
