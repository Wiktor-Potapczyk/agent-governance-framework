---
component: "sidecar_loader"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: sidecar_loader

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/sidecar_loader.py`
- **Provenance:** authored-in-harness
- **Reachability:** none recorded; blocked: `BLK-001`
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:** (no edges recorded)
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Sidecar loader: H11 proof-of-concept (2026-04-18).

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

This file is a library, not an event hook: nothing registers it in settings.local.json and it never fires on its own, which is why the Usage line above reads zero. Other hooks import it to consult a process skill's DISPATCHES.json as fallback ground truth when transcript classification is missing or truncated (.claude/hooks/sidecar_loader.py:1-24); the edge list above shows dispatch-compliance-check as the importer.

load_dispatches(skill_name) looks for the sidecar under both layouts, skills/<skill>/ and skills/core/<skill>/, so the same file works in the vault and in the framework repo (.claude/hooks/sidecar_loader.py:30-35, .claude/hooks/sidecar_loader.py:63-72). It returns the parsed dict with the mandatory, conditional, and exemption keys defaulted to empty lists (.claude/hooks/sidecar_loader.py:82-86); a malformed or non-object sidecar returns {} after appending a warn record to governance-log.jsonl (.claude/hooks/sidecar_loader.py:39-53, .claude/hooks/sidecar_loader.py:73-81).

Two wrappers flatten the data for callers: mandatory_agent_names for the required list, all_allowed_agent_names for everything a hook should treat as legitimate inside the skill (.claude/hooks/sidecar_loader.py:89-113). Run directly, the file self-tests by loading a named skill's sidecar (.claude/hooks/sidecar_loader.py:116-128).
<!-- PROSE:END -->
