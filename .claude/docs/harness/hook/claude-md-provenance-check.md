---
component: "claude-md-provenance-check"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: claude-md-provenance-check

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/claude-md-provenance-check.py`
- **Provenance:** authored-in-harness
- **Reachability:** none recorded; blocked: `BLK-001`
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:** (no edges recorded)
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Mechanism A countermeasure from the caveman postmortem
(Projects/Agent-Governance-Research/work/2026-08-10-caveman-postmortem.md):
the caveman-lite rule survived four months while the pointer to its own origin
died, because CLAUDE.md requires no inline provenance the way wiki pages
require a source: field. This guard extends that discipline to the
constitution: a rule-shaped change to the vault-root
CLAUDE.md with no inline origin citation gets a one-line warning
(.claude/hooks/claude-md-provenance-check.py:9).

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

This PostToolUse hook matches Write and Edit but acts only when the target file is the vault-root CLAUDE.md, by exact normalized-path comparison; nested CLAUDE.md files are out of scope (.claude/hooks/claude-md-provenance-check.py:69). The examined text is new_string for an Edit and the full content for a Write (.claude/hooks/claude-md-provenance-check.py:108).

That text is tested against two regex families: rule-shaped signals (a new heading, a "CRITICAL RULE" marker, a bold line carrying a modal rule verb, .claude/hooks/claude-md-provenance-check.py:53) and provenance signals (a wikilink, a feedback_/finding_/decision_/reference_ memo name, a Projects/*/work/ path, a dated parenthetical, .claude/hooks/claude-md-provenance-check.py:61). Rule-shaped text with no provenance produces one stderr WARN line asking for an inline origin citation, plus a "warn" record via log_fire; the edit itself is kept (.claude/hooks/claude-md-provenance-check.py:114). Everything else logs "allow", and the hook exits 0 in every case, failing open on any internal error (.claude/hooks/claude-md-provenance-check.py:130).
<!-- PROSE:END -->
