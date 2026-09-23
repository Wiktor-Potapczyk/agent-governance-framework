---
component: "_competence_signal"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: _competence_signal

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/_competence_signal.py`
- **Provenance:** authored-in-harness
- **Reachability:** none recorded; blocked: `BLK-001`
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:** (no edges recorded)
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Structural reliability signal for the Step-11 competence gate (2026-07-13).

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

No hook event fires this module directly. It is a stdlib-only library with no side effects at import (.claude/hooks/_competence_signal.py:27), imported by agent-dispatch-check for the Step-11 competence gate. The entry point get_verdict(log_path, agent_type) reads governance-log.jsonl backwards in 64 KB chunks until it holds the last 50 completion events for that agent, so a sparse agent in a huge log still gets a correct window (.claude/hooks/_competence_signal.py:61).

It counts three completion shapes per agent_type: subagent-quality-check pass, subagent-quality-check block, and reviewer_scope_violation events (.claude/hooks/_competence_signal.py:145). Rows whose session equals "session" are synthetic subprocess-test pollution and are dropped first (.claude/hooks/_competence_signal.py:112). The score is passes / n over the window; the verdict is NO_SIGNAL below 5 events, OK at score >= 0.8, otherwise BELOW (.claude/hooks/_competence_signal.py:166).

It emits nothing: no log write, no stdout. It returns a {score, n, verdict} dict, and every failure path returns the fail-open NO_SIGNAL object instead of raising (.claude/hooks/_competence_signal.py:180). MODE is the constant "ADVISORY"; the ENFORCE flip is deliberately not implemented here (.claude/hooks/_competence_signal.py:41).
<!-- PROSE:END -->
