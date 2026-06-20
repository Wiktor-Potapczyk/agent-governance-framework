---
name: process-governance-mine
description: Weekly skill that mines governance-log.jsonl for recurring failure patterns and emits a proposal artifact. Read-only except for one output file. Complements /hookify (reactive) with a retrospective/aggregate view.
---

# process-governance-mine: Governance-Log Failure Miner

You have been routed here to mine `.claude/hooks/governance-log.jsonl` for recurring failure patterns and produce a structured proposal for review.

**HARD INVARIANT: PROPOSAL-ONLY (NON-NEGOTIABLE):**
This skill writes EXACTLY ONE content file:
`<project>/work/YYYY-MM-DD-governance-mine-proposals.md`
(where `<project>` is your active project directory, e.g. `Projects/My-Project/work/`)
- PLUS one bookkeeping-only timestamp file, its own cadence state `.claude/hooks/_state/governance-mine-cadence.json` (Step 5), exactly as `process-lint` writes `lint-cadence.json`. That is the complete write set.

It reads everything else. It NEVER edits `CLAUDE.md`, any hook **logic** under `.claude/hooks/` (the `mine_governance.py` helper, any `*.py` hook), `.claude/skills/*`, the governance log, or the resolved ledger `miner-resolved.jsonl`. The only write under `.claude/hooks/` it is permitted is the `_state/governance-mine-cadence.json` timestamp. Any attempt to edit doctrine, hook logic, skills, the log, or the ledger is unauthorized and hook-blocked regardless. This is the proposal boundary: the repository owner decides what gets actioned.

---

## Use-when

- User says `/process-governance-mine` or "run governance mine" or "what recurring failures are in the log?"
- Weekly cadence reminder fires from `lint-cadence-trigger.py` (SessionStart) when configured: state file at `.claude/hooks/_state/governance-mine-cadence.json`
- After a high-incident period (multiple `fabrication_detected` or `dark-zone` bursts) to confirm the pattern is persistent
- Before a retrospective or harness-architecture review session

## Do-NOT-use-when

- You want to FIX a hook or CLAUDE.md: this skill proposes only; fixes go through `/hookify` (reactive) or a direct Build task with explicit approval
- The log file does not exist or is empty: nothing to mine
- You want to validate wiki structure: use `process-lint` (different concern)
- A single specific incident needs investigation: use `process-qa` on the specific session; the miner aggregates over weeks, not sessions

## Gotchas

- **Proposal-only boundary.** The output path is the only writable target. Everything else is read. Hard-failing this boundary invalidates the invariant this skill exists to enforce.
- **sig_ids invalidate if the normalization function changes.** When `mine_governance.py` normalization logic is updated, old `sig_id` values in `miner-resolved.jsonl` no longer match. Re-baseline the ledger after any normalization change: review current proposals and re-enter still-valid suppressions with new sig_ids.
- **Ledger is human-written.** The miner reads `miner-resolved.jsonl` but never writes it. Append a suppression entry manually when a proposal is actioned. The miner re-surfaces a suppressed sig if it regresses past the resolved threshold after the `resolved_ts`.
- **`surfaced_count` is per-proposal-file grep, not a DB counter.** It reflects how many prior `*-governance-mine-proposals.md` files contain this sig_id. A sig_id not in any prior file has `surfaced_count=0` (first appearance). Use this to spot chronic unactioned proposals.
- **Window is rolling 30 days.** Ancient resolved noise ages out automatically. A sig that stops occurring will eventually fall below the gate and disappear without needing a ledger entry.
- **Paired `*_blocked` twins produce two adjacent sig_ids.** Some events emit a companion blocked variant (e.g. `reviewer_scope_violation` + `reviewer_scope_violation_blocked`). A single underlying behavioral failure therefore appears as two adjacent sig_ids in the proposal: this is expected, not a bug. The resolved-ledger suppresses both independently; add two entries if you want both suppressed.
- **High-severity gate is C=3 (not C=10).** `fabrication_detected` is unconditionally high-severity and surfaces at count >= 3 over >= 3 distinct days. `dark-zone` events carry their OWN per-record `severity` field; a dark-zone sig is high-severity only when at least one admitted record has `severity=high`: otherwise it is normal-severity and uses the C=10 gate. Do not dismiss a 3-count high-severity proposal as noise: it is intentionally sensitive.

---

## Steps

### Step 1: Run the miner

Execute `mine_governance.py` against the live log. The helper lives at `hooks/mine_governance.py` in this repo, or at `.claude/hooks/mine_governance.py` in a deployed project.

```bash
python .claude/hooks/mine_governance.py
```

Or import and call programmatically:

```python
import sys, os
from datetime import date
sys.path.insert(0, ".claude/hooks")
from mine_governance import mine, WINDOW_DAYS

LOG    = ".claude/hooks/governance-log.jsonl"
LEDGER = ".claude/hooks/aggregates/miner-resolved.jsonl"

flagged = mine(LOG, date.today(), WINDOW_DAYS,
               resolved_ledger_path=LEDGER if os.path.isfile(LEDGER) else None)
```

Capture the returned list of sig records. Each record contains:
`sig_id`, `severity`, `event_label`, `agent_type`, `hook`, `normalized_signature`,
`count`, `distinct_days`, `first_seen`, `last_seen`, `top_tool_name`, `raw_samples`,
`bucket`, `suppressed`, `regression`.

### Step 2: Compute `surfaced_count` per sig_id

For each flagged sig_id, count how many existing proposal files already contain it:

```python
import glob
# Substitute your active project's work dir for the path below,
# e.g. "Projects/My-Project/work/*-governance-mine-proposals.md"
proposal_files = glob.glob(
    "PROJECT_WORK_DIR/*-governance-mine-proposals.md"
)
for rec in flagged:
    sid = rec["sig_id"]
    def _contains(path, sid):
        with open(path, encoding="utf-8") as fh:
            return sid in fh.read()
    prior_count = sum(1 for p in proposal_files if _contains(p, sid))
    rec["surfaced_count"] = prior_count
```

A `surfaced_count >= 2` is an unactioned-drift signal: mention it in the proposal block.

### Step 3: Write the proposal file

Output path: `<project>/work/YYYY-MM-DD-governance-mine-proposals.md`
(where YYYY-MM-DD is today's date; substitute your active project path for `<project>`)

**Frontmatter:**
```yaml
---
date: YYYY-MM-DD
tags: [hooks, governance]
status: active
---
```

**Header:**
```
# Governance Mine Proposals: YYYY-MM-DD

Helper: `mine_governance.py` | Window: 30 days | Gates: normal C=10/D=3, high-sev C=3/D=3
```

**Per flagged sig_id, emit one block in this exact schema:**
```
### <sig_id>: <bucket>: count N over D days
- Normalized signature: <normalized_signature>
- First seen / last seen: <first_seen> / <last_seen>
- Top hook / agent_type / tool: <hook> / <agent_type> / <top_tool_name>
- Severity: <severity>
- Regression: <yes/no>
- Surfaced count (prior runs): <surfaced_count>
- Sample raw lines (<=3, verbatim):
  ```
  <raw_samples[0]>
  <raw_samples[1] if present>
  <raw_samples[2] if present>
  ```
- Hypothesis: <bucket letter + one sentence: e.g. "b over-firing: reviewer-scope-violation-check accounts for >50% of all admitted failure lines; the hook may be misconfigured.">
- Proposed action: <concrete: e.g. "tune hook X", "add CLAUDE.md note Y", "decide">
- To suppress next run: add {"sig_id": "<sig_id>", "resolved_ts": "YYYY-MM-DD", "resolution": "<action>", "note": "<note>"} to .claude/hooks/aggregates/miner-resolved.jsonl
```

Order: high-severity sigs first, then by count descending (matches `mine()` sort order).

If no flagged sigs: write a single section "## No flagged patterns" with the window and gate parameters used.

### Step 4: Surface summary

After writing the file, emit a one-line summary:

```
N proposals written to <project>/work/YYYY-MM-DD-governance-mine-proposals.md
Top sig: <sig_id>: severity=<sev>: <event_label>: count=<count> over <distinct_days> days (bucket: <bucket>)
```

### Step 5: Update cadence state file

Write `.claude/hooks/_state/governance-mine-cadence.json`:
```json
{
  "last_iso": "YYYY-MM-DDTHH:MM:SSZ",
  "report_path": "<project>/work/YYYY-MM-DD-governance-mine-proposals.md",
  "proposal_count": <N>
}
```

Used by `lint-cadence-trigger.py` (if installed) to suppress the "consider running" reminder until next cadence.

---

## Notes

- **Complementary to `/hookify`, not a replacement.** `/hookify` fires immediately when a live behavior is corrected; the miner catches silent recurring failures nobody corrected. Both are needed.
- **The ledger solves the re-proposal problem.** Without it, every run re-proposes a fix that was already shipped. Add a ledger entry when a proposal is actioned; the miner suppresses it going forward.
- **Regression detection is automatic.** If a suppressed sig re-occurs above threshold after its `resolved_ts`, it re-surfaces with `regression=True` in the proposal: no manual monitoring needed.
- **v2 deferred.** General normalization-clustering miner is explicitly deferred until the log's distinct-block_reason count grows materially. v1-minimal covers ~80% of today's value.
