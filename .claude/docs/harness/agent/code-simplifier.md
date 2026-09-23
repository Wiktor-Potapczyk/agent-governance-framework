---
component: "code-simplifier"
kind: "agent"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# agent: code-simplifier

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/agents/code-simplifier.md`
- **Provenance:** authored-in-harness
- **Reachability:** `EVD-004` (.claude/registry.json)
- **Usage:** Recorded use count 0 (source: `governance-log.jsonl:agent_dispatched.agent_type`).
- **Edges:**
  - inbound mentioned_in_prose CLAUDE.md [unresolved: prose mention only]
  - inbound cataloged_in registry.json
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Use after authoring or editing code/config in the vault to clean up mechanical hygiene WITHOUT changing functionality.

(machine-filled from rationale-index.json; extraction locus: frontmatter)

## How

Nothing fires it automatically: the definition closes with an on-demand-only operating mode, ruling out auto-trigger on every Write/Edit for rate-limit hygiene (`.claude/agents/code-simplifier.md:89-91`). It is reached by a discretionary Agent-tool dispatch after code or config in the vault was just edited (`.claude/agents/code-simplifier.md:3`); this page's Reachability line shows only the registry catalog, no MUST DISPATCH row.

Tool surface: Read, Write, Edit, Grep, Glob, Bash (`.claude/agents/code-simplifier.md:8`). Scope is mechanical hygiene on three vault artifact classes (n8n workflow JSON, Python hooks, Markdown skills); architecture, SOLID, and security findings must be flagged OUT OF SCOPE and routed to architect-reviewer (`.claude/agents/code-simplifier.md:11`, `.claude/agents/code-simplifier.md:83`).

Contract: one block per refinement with File, Why, Before, and After; default mode is diff-proposal, and it must not write to disk unless the dispatcher explicitly says apply (`.claude/agents/code-simplifier.md:70-81`). No output-checking hook is named in the definition.
<!-- PROSE:END -->
