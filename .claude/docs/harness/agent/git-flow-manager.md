---
component: "git-flow-manager"
kind: "agent"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# agent: git-flow-manager

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/agents/git-flow-manager.md`
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

Git Flow workflow manager.

(machine-filled from rationale-index.json; extraction locus: frontmatter)

## How

Reached only by discretionary Agent-tool dispatch; the description asks for PROACTIVE use on Git Flow operations: branch creation, merging, validation, release management, and pull request generation (`.claude/agents/git-flow-manager.md:3`). No MUST DISPATCH row binds it; this page's Reachability line lists only the registry catalog.

Tool surface: Read, Bash, Grep, Glob, Edit, Write (`.claude/agents/git-flow-manager.md:4`). It enforces the Git Flow branch hierarchy (main, develop, feature/, release/vX.Y.Z, hotfix/) with base-branch and branch-name validation before creating or merging (`.claude/agents/git-flow-manager.md:13-17`, `.claude/agents/git-flow-manager.md:164-170`).

Contract: every response reports the action taken, current repository status, next steps, and any warnings (`.claude/agents/git-flow-manager.md:275-282`). No output-checking hook is named in the definition. Caveat for this vault: the agent's model assumes develop and feature branches (`.claude/agents/git-flow-manager.md:14-17`), while vault doctrine per CLAUDE.md is main-only with no feature branches, so its contract fits external repos rather than the vault repo itself.
<!-- PROSE:END -->
