---
component: "mine_governance"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: mine_governance

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/mine_governance.py`
- **Provenance:** authored-in-harness
- **Reachability:** none recorded; blocked: `BLK-001`
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:**
  - inbound mentioned_in_prose process-governance-mine [unresolved: prose mention only]
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Governance-log failure miner — v1-minimal (REV-1..REV-6, 2026-06-08).

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

This file is not wired to any hook event; the generated block above records no reachability, and no `.claude/settings.local.json` entry names it. It is a pure-stdlib library and CLI: run as a script it mines the live `.claude/hooks/governance-log.jsonl` over a rolling 30-day window and prints flagged signatures to stdout (`.claude/hooks/mine_governance.py:888`, `.claude/hooks/mine_governance.py:26`). The weekly `/process-governance-mine` skill is its caller of record.

`mine()` admits only failure-shaped records: a named allowlist (`deny`, `dark-zone`, `fabrication_detected`, and siblings) plus any event ending in `_blocked` (`.claude/hooks/mine_governance.py:47`, `.claude/hooks/mine_governance.py:156`). Admitted records are grouped by (event_label, agent_type, hook, normalized reason), and a signature is flagged when it clears the recurrence gate: 10 occurrences across 3 distinct days, or 3 occurrences for high severity (`.claude/hooks/mine_governance.py:23`, `.claude/hooks/mine_governance.py:446`). A ledger of resolved sig_ids suppresses known findings unless they regress past the same gate after resolution (`.claude/hooks/mine_governance.py:231`, `.claude/hooks/mine_governance.py:461`).

A second pass, `mine_warns()`, scans the same log for warn-tier promotion candidates and is proposal-only by construction: it computes and returns, writes nothing, and fails closed to zero candidates when the live Gate-1 exclusion sets cannot be derived from the guard and surface modules (`.claude/hooks/mine_governance.py:628`, `.claude/hooks/mine_governance.py:518`).
<!-- PROSE:END -->
