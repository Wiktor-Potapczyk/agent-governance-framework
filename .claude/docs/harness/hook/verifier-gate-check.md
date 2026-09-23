---
component: "verifier-gate-check"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: verifier-gate-check

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/verifier-gate-check.py`
- **Provenance:** authored-in-harness
- **Reachability:** none recorded; blocked: `BLK-001`
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:**
  - inbound mentioned_in_prose CLAUDE.md [unresolved: prose mention only]
  - inbound mentioned_in_prose process-lint [unresolved: prose mention only]
  - inbound mentioned_in_prose verification-gated-research [unresolved: prose mention only]
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Verifier Gate Check - Stop Hook
Enforces the contract of the `verification-gated-research` skill (SOTA-RECON-2,
Candidate 1E): if that skill was invoked this session, completion is blocked
until a SEPARATE verifier agent was dispatched.

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

A Stop hook that stays dormant unless a Skill tool_use for `verification-gated-research` appears in the last 200 KB of the transcript (.claude/hooks/verifier-gate-check.py:129, .claude/hooks/verifier-gate-check.py:75). It also skips stop-hook retries via `stop_hook_active` (.claude/hooks/verifier-gate-check.py:91).

Once armed, it collects every post-skill Agent dispatch in order (.claude/hooks/verifier-gate-check.py:135) and looks for one VALID verifier passing three structural parts: it appears after all worker dispatches, its prompt is not byte-identical to any worker prompt, and its prompt carries a re-derivation contract, either a keyword like re-derive or recompute or a reference to an artifact path (.claude/hooks/verifier-gate-check.py:154, .claude/hooks/verifier-gate-check.py:58). Dispatch `subagent_type` values are recorded as audit data but never enforced (.claude/hooks/verifier-gate-check.py:151).

If no valid verifier exists it prints a `{"decision": "block"}` payload telling the session to dispatch a re-deriving verifier before completing (.claude/hooks/verifier-gate-check.py:178). Pass and block outcomes append records to governance-log.jsonl (.claude/hooks/verifier-gate-check.py:174, .claude/hooks/verifier-gate-check.py:237), with the destination honouring both the `GOVERNANCE_LOG_PATH` env seam and a test-redirected hook directory (.claude/hooks/verifier-gate-check.py:210).
<!-- PROSE:END -->
