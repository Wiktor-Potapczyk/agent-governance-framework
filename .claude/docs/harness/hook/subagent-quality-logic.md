---
component: "_subagent_quality_logic"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: _subagent_quality_logic

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/_subagent_quality_logic.py`
- **Provenance:** authored-in-harness
- **Reachability:** none recorded; blocked: `BLK-001`
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:** (no edges recorded)
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Pure logic for subagent-quality-check (extracted 2026-06-02, boundary-test harness sprint 6).

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

The decision function for the subagent-quality-check Stop-hook wrapper, extracted so the three structural checks can be unit-tested without the wrapper's governance-log writes polluting the live log (.claude/hooks/_subagent_quality_logic.py:1). classify_subagent_output takes a sub-agent's last message and returns (blocked, check_failed, reason) (.claude/hooks/_subagent_quality_logic.py:47).

CHECK 1 blocks output under 5 chars as empty (.claude/hooks/_subagent_quality_logic.py:59). CHECK 2 blocks an under-100-char message containing a refusal keyword, unless a result-signal token such as "found", "works", or "no defects" marks it as a valid negative finding rather than a refusal (.claude/hooks/_subagent_quality_logic.py:66, .claude/hooks/_subagent_quality_logic.py:29). CHECK 3 blocks over-500-char output with no structural markup at all, where unfenced label:value report blocks and bold text count as structure (.claude/hooks/_subagent_quality_logic.py:75). A passing message returns (False, "", "") (.claude/hooks/_subagent_quality_logic.py:91).
<!-- PROSE:END -->
