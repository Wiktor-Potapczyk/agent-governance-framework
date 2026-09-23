---
component: "subagent-quality-check"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: subagent-quality-check

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/subagent-quality-check.py`
- **Provenance:** authored-in-harness
- **Reachability:** none recorded; blocked: `BLK-001`
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:** (no edges recorded)
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

SubagentStop Hook - L2 exit gate: structural quality check on agent output.

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

Fires on SubagentStop with an empty matcher. After the stop_hook_active loop guard (.claude/hooks/subagent-quality-check.py:138-140) it scores the subagent's last_assistant_message with the pure detection logic extracted to _subagent_quality_logic.classify_subagent_output (.claude/hooks/subagent-quality-check.py:14, .claude/hooks/subagent-quality-check.py:219-224). An empty message gets one rescue check first: when the final turn of the subagent's own transcript ended in a tool_use (a structured answer), a short sentinel string stands in instead of a block (.claude/hooks/subagent-quality-check.py:20, .claude/hooks/subagent-quality-check.py:28-62, .claude/hooks/subagent-quality-check.py:155-157).

A failed check prints {"decision": "block"} with the reason and exits 0, after appending a line to subagent-quality.log and a block event with a violation excerpt to governance-log.jsonl (.claude/hooks/subagent-quality-check.py:179-217). A pass appends a PASS line and a structured pass event so per-agent pass rates stay computable (.claude/hooks/subagent-quality-check.py:227-255). Neither sink is hook-activity.jsonl, which is why the Usage line above reads zero.

For workflow subagents it also recovers workflow identity: the WORKFLOW-ID marker read from the head of the subagent's own transcript plus the run id parsed from its path, attached to both emits as fail-open telemetry that never gates the decision (.claude/hooks/subagent-quality-check.py:65-121, .claude/hooks/subagent-quality-check.py:171-174).
<!-- PROSE:END -->
