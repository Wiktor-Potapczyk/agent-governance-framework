---
component: "dispatch-compliance-check"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: dispatch-compliance-check

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/dispatch-compliance-check.py`
- **Provenance:** authored-in-harness
- **Reachability:** none recorded; blocked: `BLK-001`
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:**
  - inbound mentioned_in_prose process-lint [unresolved: prose mention only]
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Dispatch Compliance Check - Stop Hook
Verifies that skills/agents declared in MUST DISPATCH were actually invoked.
Reads transcript tail, finds last MUST DISPATCH field, checks Skill, Agent, and
Workflow tool_use blocks for matching dispatches. Blocks if any declared item is missing.

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

This Stop hook is the thin I/O wrapper around _dispatch_compliance_logic, which holds the pure logic (.claude/hooks/dispatch-compliance-check.py:13). It reads the last 200KB of the transcript (.claude/hooks/dispatch-compliance-check.py:69), lets scan_assistant_text_block track the last MUST DISPATCH contract in assistant text, and collects dispatched names from Skill, Agent, and Workflow tool_use blocks, normalizing plugin-namespaced names to their bare suffix so both sides compare on equal footing (.claude/hooks/dispatch-compliance-check.py:196).

When no classification block is found but a trackable process-* skill ran, the H11 sidecar fallback loads a merged mandatory-dispatch contract from the skills' DISPATCHES.json sidecars and logs the activation (.claude/hooks/dispatch-compliance-check.py:243). An empty MUST DISPATCH on a non-Quick task blocks on its own (.claude/hooks/dispatch-compliance-check.py:279).

Declared names that were never dispatched produce a stdout {"decision": "block"} plus a block event in governance-log.jsonl, with a soft warning when general-purpose was substituted (.claude/hooks/dispatch-compliance-check.py:304); a full match logs a pass event with the alias-aware matched set (.claude/hooks/dispatch-compliance-check.py:350). Every entry one invocation emits shares a single correlation_id (.claude/hooks/dispatch-compliance-check.py:140).
<!-- PROSE:END -->
