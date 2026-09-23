---
component: "vault-keeper"
kind: "agent"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# agent: vault-keeper

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/agents/vault-keeper.md`
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

Use this agent for vault organization — processing Inbox files, creating daily notes, moving or archiving notes, fixing frontmatter, updating wiki-links, or vault health checks.

(machine-filled from rationale-index.json; extraction locus: frontmatter)

## How

Dispatched via the Agent tool for vault organization: inbox triage, note moves and archiving, frontmatter fixes, wiki-link updates, and health checks; content writing, research, and automation builds are explicitly out of scope (.claude/agents/vault-keeper.md:3). It is this roster's only haiku agent and carries project-scoped memory (.claude/agents/vault-keeper.md:5). It must re-read CLAUDE.md at the vault root before every operation (.claude/agents/vault-keeper.md:11).

Tool surface: Read, Write, Edit, Glob, Grep, Bash (.claude/agents/vault-keeper.md:4). Per-mode contracts: inbox processing reports one line per note as filename, classification, destination (.claude/agents/vault-keeper.md:16); moves are read, write to the new location, then Bash rm of the original, never a permanent delete (.claude/agents/vault-keeper.md:20); health checks report fixed items, flagged items, and items needing a user decision (.claude/agents/vault-keeper.md:22).

No structured metadata block checks its output; the standing constraints are the never-delete rule (.claude/agents/vault-keeper.md:20) and the Anti-Sycophancy section (.claude/agents/vault-keeper.md:24).
<!-- PROSE:END -->
