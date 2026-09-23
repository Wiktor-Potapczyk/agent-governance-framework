---
component: "repo-sync"
kind: "skill"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# skill: repo-sync

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/skills/repo-sync`
- **Provenance:** authored-in-harness
- **Reachability:** `EVD-004` (.claude/registry.json)
- **Usage:** Recorded use count 0 (source: `governance-log.jsonl:agent_dispatched.skill_context[]`).
- **Edges:**
  - inbound cataloged_in registry.json
  - outbound mentions_in_prose content-marketer [unresolved: prose mention only]
  - outbound mentions_in_prose doc-consistency [unresolved: prose mention only]
  - outbound mentions_in_prose maintain [unresolved: prose mention only]
  - outbound mentions_in_prose verify [unresolved: prose mention only]
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Use to update/maintain/sync the two PUBLIC GitHub repos (agent-governance-framework / AGF, agent-governance-research / AGR). When Wiktor explicitly says "update/sync/push repo X" this means the FULL definition-of-done — ship the actual new artifacts (agents/hooks/skills/workflows), update the README + all docs to cover every functionality, run doc-consistency, run the HARD pre-push NDA gate, commit gmail-authored + fast-forward push + verify. Do NOT ship a partial doc-note (documented failure).

(machine-filled from rationale-index.json; extraction locus: frontmatter)

## How

Invoked via the Skill tool in two modes: Mode A when Wiktor explicitly directs an update, which authorizes the full Definition of Done including new artifacts and README rewrites, and Mode B as an unsolicited autonomous run bounded to routine doc maintenance (`.claude/skills/repo-sync/SKILL.md:27-29`). It is hard-scoped to the AGF and AGR public repos in either mode (lines 31, 43).

The tool surface is Bash-driven git plus the skill's own scripts: fetch and rev-list to prove a clean fast-forward base (`.claude/skills/repo-sync/SKILL.md:58-62`), the doc-consistency checker plus the repo's own CI checks reproduced locally (lines 73-75), `nda_gate.py` run on content before the commit, on the draft commit message, and again after the commit (lines 90-97, 102-106), and `repo_release.py` for the local-only changelog entry and tag (line 129).

The contract is the full Definition of Done checklist: artifacts land, README checked, complete doc coverage, NDA hard gate, gmail-authored fast-forward push, completeness re-check (`.claude/skills/repo-sync/SKILL.md:16-21`), followed by a Stage 7 per-repo report naming drift, fixes, the gate verdict, the commit SHA, and the sync confirmation (line 122). Enforcement is the gate itself: exit 1 on either gate run blocks commit and push (line 97), and a non-fast-forward state or a failed push is a hard STOP with no force retry (lines 112-117).
<!-- PROSE:END -->
