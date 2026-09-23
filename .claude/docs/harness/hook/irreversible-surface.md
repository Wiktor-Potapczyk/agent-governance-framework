---
component: "_irreversible_surface"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: _irreversible_surface

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/_irreversible_surface.py`
- **Provenance:** authored-in-harness
- **Reachability:** none recorded; blocked: `BLK-001`
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:**
  - inbound mentioned_in_prose CLAUDE.md [unresolved: prose mention only]
  - inbound mentioned_in_prose process-governance-mine [unresolved: prose mention only]
  - inbound mentioned_in_prose process-lint [unresolved: prose mention only]
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

_irreversible_surface.py: single source of the NEW canonical irreversible surface.

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

The single definition of the Gate-1 irreversible surface, imported by both Gate-1 hooks: bash-safety-guard appends IRREVERSIBLE_BASH_PATTERNS to its deny list and mcp-irreversible-guard consumes IRREVERSIBLE_MCP_TOOLS (.claude/hooks/_irreversible_surface.py:8). The Bash patterns deny an unflagged relative rm, every git push form including global-option variants, destructive SQL (DROP, TRUNCATE, unbounded DELETE), and prod-deploy shapes such as docker compose up and the git archive | ssh pipe (.claude/hooks/_irreversible_surface.py:40).

The MCP surface maps exact tool names either to NAME_SUFFICIENT (deny on the name alone) or to a predicate that denies only on a dangerous payload, such as an n8n workflow update that flips active:true (.claude/hooks/_irreversible_surface.py:153, .claude/hooks/_irreversible_surface.py:130). mcp_tool_is_irreversible returns (False, None) for unknown tools and on predicate errors, so read tools stay allowed (.claude/hooks/_irreversible_surface.py:176).

curl_external_write parses every curl invocation in a chain and reports a deny when a write method or body targets a non-loopback host, ignoring loopback tokens in headers, bodies, and query strings (.claude/hooks/_irreversible_surface.py:476); curl_write_targets_warn_hosts_only backs the warn carve-out for allowlisted hosts (.claude/hooks/_irreversible_surface.py:632). Every pattern is compiled at import as a self-screen, so a broken regex fails loudly at load; the module itself emits nothing, the importing hooks emit the deny decisions (.claude/hooks/_irreversible_surface.py:671).
<!-- PROSE:END -->
