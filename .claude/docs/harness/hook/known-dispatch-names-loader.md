---
component: "_known_dispatch_names_loader"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: _known_dispatch_names_loader

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/_known_dispatch_names_loader.py`
- **Provenance:** authored-in-harness
- **Reachability:** none recorded; blocked: `BLK-001`
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:** (no edges recorded)
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Shared loader for the generated KNOWN_DISPATCH_NAMES data file.

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

A small shared loader that runs only when one of its three importers (agent-dispatch-check, _dispatch_compliance_logic for the dispatch-compliance-check Stop hook, and governance-log) calls load_known_dispatch_names at import time (.claude/hooks/_known_dispatch_names_loader.py:9). It reads .claude/hooks/_known_dispatch_names.json and returns the known_dispatch_names list as a set (.claude/hooks/_known_dispatch_names_loader.py:44).

On any read, parse, or schema failure it returns the caller-supplied fallback unchanged and, when warn_label is given, prints one stderr line naming the failure and the regeneration command, so a broken generated file is loud instead of a silent enforcement change (.claude/hooks/_known_dispatch_names_loader.py:50). The safe fallback direction differs per caller (never-deny vs can-block vs log-only), which is why the fallback set is a parameter rather than a constant (.claude/hooks/_known_dispatch_names_loader.py:19).
<!-- PROSE:END -->
