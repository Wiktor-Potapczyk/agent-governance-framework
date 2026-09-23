---
component: "subagent-scope-check"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: subagent-scope-check

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/subagent-scope-check.py`
- **Provenance:** authored-in-harness
- **Reachability:** none recorded; blocked: `BLK-001`
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:** (no edges recorded)
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Empirical trigger (2026-05-26 W-D2 ensemble, loop iter 2):
- prompt-engineer sub-agent self-extended scope to mark its own task_plan ticket
  AND made a tag-policy decision (ensemble → unclassified-pending) — both outside
  the design-only ticket scope.
- Substance was accurate; scope was wrong. Documented as the first scope-extension
  event in [[finding_subagent_reviewer_write_grant_pattern]].

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

Registered twice in `.claude/settings.local.json`, on SubagentStart and on SubagentStop, and branches on the `hook_event_name` field of its stdin payload (.claude/hooks/subagent-scope-check.py:99). On SubagentStart it runs `git status --porcelain` in the vault (.claude/hooks/subagent-scope-check.py:45) and stores the result as a baseline keyed by `agent_id` in `.claude/hooks/_state/subagent-scope-baselines.json` (.claude/hooks/subagent-scope-check.py:121).

On SubagentStop it pops that baseline, re-runs git status, and diffs the two sets (.claude/hooks/subagent-scope-check.py:134). A stop with no stored baseline records only the fact, never the dirty tree, because that delta would be the repository state rather than the subagent's writes (.claude/hooks/subagent-scope-check.py:150). Each stop appends one JSONL record to `subagent-scope-log.jsonl`, with paths capped at 20 per list but full counts kept (.claude/hooks/subagent-scope-check.py:166).

It never blocks: every branch returns 0 (.claude/hooks/subagent-scope-check.py:200). When new modifications exist it prints one `[SCOPE-CHECK]` warning to stderr pointing at the log (.claude/hooks/subagent-scope-check.py:190), and every invocation records a pass, warn, allow, or skip verdict to hook-activity.jsonl through `_governance_logger.log_fire` (.claude/hooks/subagent-scope-check.py:104).
<!-- PROSE:END -->
