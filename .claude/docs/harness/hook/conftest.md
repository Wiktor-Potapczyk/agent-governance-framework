---
component: "conftest"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: conftest

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/conftest.py`
- **Provenance:** authored-in-harness
- **Reachability:** none recorded; blocked: `BLK-001`
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:** (no edges recorded)
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Pytest configuration for the hooks suite.

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

Not a runtime hook: this is the pytest configuration for the hooks test suite, so no event or matcher ever fires it, which matches the generated Reachability line above. Its one autouse session fixture redirects the two shared log writers by setting GOVERNANCE_LOG_PATH and HOOK_ACTIVITY_LOG_PATH to files in a throwaway temp directory for the whole run, then restores the prior values afterwards (.claude/hooks/conftest.py:39).

The docstring records the measured reason it exists: before this file, one suite run appended 128 records to the live governance-log.jsonl and 117 to hook-activity.jsonl (.claude/hooks/conftest.py:5). It also sets collect_ignore for the retired/ directory, so retired hooks' test files stay uncollected (.claude/hooks/conftest.py:56).
<!-- PROSE:END -->
