---
name: process-governance-mine
description: Weekly skill that mines governance-log.jsonl for recurring failure patterns and emits a proposal artifact. Read-only except for one output file. Complements /hookify (reactive) with a retrospective/aggregate view.
---

# process-governance-mine: Governance-Log Failure Miner

You have been routed here to mine `.claude/hooks/governance-log.jsonl` for recurring failure patterns and produce a structured proposal for the owner.

**HARD INVARIANT: PROPOSAL-ONLY (NON-NEGOTIABLE):**
This skill writes EXACTLY ONE content file:
`Projects/your-project/work/YYYY-MM-DD-governance-mine-proposals.md`
: PLUS one bookkeeping-only timestamp file, its own cadence state `.claude/hooks/_state/governance-mine-cadence.json` (Step 5), exactly as `/process-lint` writes `lint-cadence.json`. That is the complete write set.

It reads everything else. It NEVER edits `CLAUDE.md`, any hook **logic** under `.claude/hooks/` (the `mine_governance.py` helper, any `*.py` hook), `.claude/skills/*`, the governance log, or the resolved ledger `miner-resolved.jsonl`. The only write under `.claude/hooks/` it is permitted is the `_state/governance-mine-cadence.json` timestamp. Any attempt to edit doctrine, hook logic, skills, the log, or the ledger is unauthorized and hook-blocked regardless. This is the proposal boundary: the owner decides what gets actioned.

Spec: `Projects/your-project/work/2026-06-07-governance-miner-spec.md`

---

## Use-when

- User says `/process-governance-mine` or "run governance mine" or "what recurring failures are in the log?"
- Weekly cadence reminder fires from `lint-cadence-trigger.py` (SessionStart): state file at `.claude/hooks/_state/governance-mine-cadence.json`
- After a high-incident period (multiple `fabrication_detected` or `dark-zone` bursts) to confirm the pattern is persistent
- Before a retrospective or harness-architecture review session

## Do-NOT-use-when

- You want to FIX a hook or CLAUDE.md: this skill proposes only; fixes go through `/hookify` (reactive) or a direct Build task with the owner's approval
- The log file does not exist or is empty: nothing to mine
- You want to validate wiki structure: use `process-lint` (different concern)
- A single specific incident needs investigation: use `process-qa` on the specific session; the miner aggregates over weeks, not sessions

## Gotchas

- **Proposal-only boundary.** The output path is the only writable target. Everything else is read. Hard-failing this boundary invalidates the invariant this skill exists to enforce.
- **sig_ids invalidate if the normalization function changes (REV-6).** When `mine_governance.py` normalization logic is updated, old `sig_id` values in `miner-resolved.jsonl` no longer match. Re-baseline the ledger after any normalization change: review current proposals and re-enter still-valid suppressions with new sig_ids.
- **Ledger is human-written.** The miner reads `miner-resolved.jsonl` but never writes it. the owner (or Claude on the owner's explicit instruction) appends a suppression entry. The miner re-surfaces a suppressed sig if it regresses past the resolved threshold after the resolved_ts.
- **`surfaced_count` is per-proposal-file grep, not a DB counter.** It reflects how many prior `*-governance-mine-proposals.md` files contain this sig_id. A sig_id not in any prior file has surfaced_count=0 (first appearance). Use this to spot chronic unactioned proposals.
- **Window is rolling 30 days.** Ancient resolved noise ages out automatically. A sig that stops occurring will eventually fall below the gate and disappear without needing a ledger entry.
- **Paired `*_blocked` twins produce two adjacent sig_ids.** Some events emit a companion blocked variant (e.g. `reviewer_scope_violation` + `reviewer_scope_violation_blocked`, each ~4007 occurrences). A single underlying behavioral failure therefore appears as two adjacent sig_ids in the proposal: this is expected, not a bug. The resolved-ledger suppresses both independently; add two entries if you want both suppressed.
- **High-severity gate is C=3 (not C=10).** `fabrication_detected` is unconditionally high-severity and surfaces at count ≥ 3 over ≥ 3 distinct days. `dark-zone` events carry their OWN per-record `severity` field; a dark-zone sig is high-severity only when at least one admitted record has `severity=high`: otherwise it is normal-severity and uses the C=10 gate. Do not dismiss a 3-count high-severity proposal as noise: it is intentionally sensitive.

---

## Steps

### Step 1: Run the miner

Execute `mine_governance.py` against the live log:

```
python .claude/hooks/mine_governance.py
```

Or import and call programmatically:

```python
import sys, os
from datetime import date
sys.path.insert(0, ".claude/hooks")
from mine_governance import mine, WINDOW_DAYS

VAULT = "C:/Users/exampleuser/Workspace"
LOG   = os.path.join(VAULT, ".claude/hooks/governance-log.jsonl")
LEDGER = os.path.join(VAULT, ".claude/hooks/aggregates/miner-resolved.jsonl")

flagged = mine(LOG, date.today(), WINDOW_DAYS,
               resolved_ledger_path=LEDGER if os.path.isfile(LEDGER) else None)
```

Capture the returned list of sig records. Each record contains:
`sig_id`, `severity`, `event_label`, `agent_type`, `hook`, `normalized_signature`,
`count`, `distinct_days`, `first_seen`, `last_seen`, `top_tool_name`, `raw_samples`,
`bucket`, `suppressed`, `regression`.

### Step 2: Compute `surfaced_count` per sig_id (REV-6)

For each flagged sig_id, count how many existing proposal files already contain it:

```python
import glob
proposal_files = glob.glob(
    "Projects/your-project/work/*-governance-mine-proposals.md"
)
for rec in flagged:
    sid = rec["sig_id"]
    def _contains(path, sid):
        with open(path, encoding="utf-8") as fh:
            return sid in fh.read()
    prior_count = sum(1 for p in proposal_files if _contains(p, sid))
    rec["surfaced_count"] = prior_count
```

A `surfaced_count ≥ 2` is an unactioned-drift signal: mention it in the proposal block.

### Step 3: Write the proposal file

Output path: `Projects/your-project/work/YYYY-MM-DD-governance-mine-proposals.md`
(where YYYY-MM-DD is today's date)

**Frontmatter:**
```yaml
---
date: YYYY-MM-DD
tags: [project/your-project, hooks, governance]
status: active
---
```

**Header (orphan-rule wikilink):**
```
# Governance Mine Proposals: YYYY-MM-DD

Hub [[moc-agent-governance]] · Spec [[2026-06-07-governance-miner-spec]] · Helper `mine_governance.py`
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
- Sample raw lines (≤3, verbatim):
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

### Step 3b - Warn-tier promotion candidates section (Hermes P4, 2026-08-18)

Run the warn pass and render one extra section in the SAME proposal file, placed after the failure findings. Plan of record: `Projects/your-project/work/2026-08-17-hermes-p4-warn-event-miner-plan.md`.

```python
from mine_governance import mine_warns
warn_result = mine_warns(LOG, date.today(), WINDOW_DAYS,
                         resolved_ledger_path=LEDGER if os.path.isfile(LEDGER) else None)
```

`warn_result` keys: `candidates`, `exclusion_unavailable`, `drift_lines`, `warn_variant_counts`, `unrecognized_counts`, `family_counts`.

Section header: `## Warn-tier promotion candidates`.

If `exclusion_unavailable` is true, print the module constant `WARN_DERIVATION_UNAVAILABLE_NOTE` ("WARN MINING SKIPPED THIS RUN: canonical-surface derivation failed, zero proposals emitted.") as the whole section body and stop this step. Zero candidates render on a failed derivation. No fallback exists by design.

Print every line in `drift_lines` verbatim. Each starts with the module constant `WARN_DENY_TIER_DRIFT_PREFIX` ("DENY-TIER PATTERN SEEN IN WARN LOG"). A drift line means log spoofing, fixture pollution, or an un-owner-gated demotion. It needs owner attention.

Compute `surfaced_count` for each warn sig_id with the same Step 2 grep. No code change is needed; warn sig_ids are plain sig_ids.

**Per candidate, emit one block in this schema:**
```
### <sig_id> - warn promotion candidate - count N over D days, S sessions
- Pattern: <pattern>
- Hook / agent_type: <hook> / <agent_type>
- Severity: normal (warn sigs are always normal severity)
- Count / distinct days / distinct sessions: <count> / <distinct_days> / <distinct_sessions>
- Top session share: <top_session_share as a percentage>
- First seen / last seen: <first_seen> / <last_seen>
- Accepted count (proxy): <accepted_count> of <count>
- Acceptance note: <acceptance_note - carries the mandatory blindness sentence>
- Surfaced count (prior runs): <surfaced_count>
- Regression: <yes/no>
- Sample command prefixes (<=3): <command_prefix_samples>
- To suppress next run: add {"sig_id": "<sig_id>", "resolved_ts": "YYYY-MM-DD", "resolution": "<action>", "note": "<note>"} to .claude/hooks/aggregates/miner-resolved.jsonl

Proposal only. No auto-apply path exists. The Gate-1 deny surface is out of scope by construction.
```

The footer line ("Proposal only. No auto-apply path exists. The Gate-1 deny surface is out of scope by construction.") is fixed text on every candidate block. The blindness sentence inside `acceptance_note` is mandatory and comes from the module constant `WARN_ACCEPTANCE_BLINDNESS_NOTE`.

When `candidates` is empty (and derivation succeeded), render the explicit line: `no warn-tier candidates this window`. The section never disappears.

**Measurement table (always rendered):** list `family_counts` (warn families with no pattern field: work-verification-check, agent-dispatch-check, and siblings), `warn_variant_counts`, and `unrecognized_counts` as count lines. These are measured, never proposable.

**v1 scope note:** only pattern-carrying PreToolUse warn-and-allow events are candidates. Non-pattern warn families have advisory semantics where "waved through" is not observable even by proxy; they appear in the measurement table only. The curl self-hosted warn variant is measured via `warn_variant_counts`, not proposable (its suffix exists nowhere importable; deriving it would need a private copy, the exact drift risk the exclusion filter forbids).

### Step 4: Surface summary to the owner

After writing the file, emit a one-line summary:

```
N proposals written to Projects/your-project/work/YYYY-MM-DD-governance-mine-proposals.md
Top sig: <sig_id>: severity=<sev>: <event_label>: count=<count> over <distinct_days> days (bucket: <bucket>)
```

### Step 5: Update cadence state file

Write `.claude/hooks/_state/governance-mine-cadence.json`:
```json
{
  "last_iso": "YYYY-MM-DDTHH:MM:SSZ",
  "report_path": "Projects/your-project/work/YYYY-MM-DD-governance-mine-proposals.md",
  "proposal_count": <N>
}
```

Used by `lint-cadence-trigger.py` to suppress the "consider running" reminder until next cadence.

---

## Notes

- **Complementary to `/hookify`, not a replacement.** `/hookify` fires immediately when the owner corrects a live behavior; the miner catches silent recurring failures nobody corrected. Both are needed.
- **The ledger solves the re-proposal problem.** Without it, every run re-proposes the reviewer-scope fix that was already shipped. Add a ledger entry when a proposal is actioned; the miner suppresses it going forward.
- **Regression detection is automatic.** If a suppressed sig re-occurs above threshold after its `resolved_ts`, it re-surfaces with `regression=True` in the proposal: no manual monitoring needed.
- **v2 deferred.** General normalization-clustering miner (§1) is explicitly deferred until the log's distinct-block_reason count grows materially. v1-minimal covers ~80% of today's value.

---

## Closed-loop protocol

This section codifies where the miner sits in the vault's five-phase self-improvement loop: DETECT -> PROPOSE -> RATIFY -> IMPLEMENT -> MEASURE. It is the operational procedure; the spec-of-record is `Projects/your-project/work/2026-07-13-self-improvement-loop-spec.md` (RATIFIED 2026-07-14). This section EXTENDS the skill; it does not change, weaken, or reword the HARD INVARIANT block above. The miner's runtime write-set stays exactly as that block defines it. The loop procedure below tells you which OTHER organs run the other phases; the miner itself only ever produces its one proposal file plus its cadence timestamp.

### The five phases (organ map summary)

The loop is assembled from organs already on disk. Pointers, not re-copies (see the spec Section 1 tables for the full inventory):

- **DETECT**: `mine_governance.py` + this skill (recurring failure patterns), `process-lint` Pass A (wiki/structure drift), `hook-write-regression-gate.py` (change-time), infrastructure probes, `/hookify` self-invoke triggers, and Step-11 competence events when built. `lint-cadence-trigger.py` (SessionStart) is the scheduler: it emits the ">7d since last governance-mine" and ">7d since last lint" reminders.
- **PROPOSE**: this skill's proposal artifact, the triage-verdict pattern (ensemble triage into ADOPT-NOW / OWNER-GATED / REJECT), `/hookify` generated rules, `process-lint` findings. All proposal-only.
- **RATIFY**: the owner decision-walkthrough pattern (the owner rules the bundled families in one sitting), recorded as `miner-resolved.jsonl` ledger notes for Track H and wiki `bootstrap -> ratified` promotion for Track V.
- **IMPLEMENT**: ONLY the mechanical + reversible + regression-gated + audit-trailed class (see the autonomy boundary below). Every change is a single commit under `git revert`.
- **MEASURE**: the recurrence-diff script `.claude/scripts/diff_miner_runs.py` (N3), full hook suite green vs the recorded Step-0 baseline, `verify_vault_metrics.py` dual-derivation, per-hook fire-rate windows (with the mandatory `session != 'session'` filter), and `process-lint` finding trends.

### The in-loop autonomy boundary (Section 3)

An action is auto-implementable inside the loop ONLY if ALL FOUR criteria hold:

| Criterion | Test |
|---|---|
| **Mechanical** | The exact edit is fully specified by an already-ratified verdict or a deterministic rule (spec R3-R5 normalization, ledger append with pre-written note, registry regeneration). Zero design judgment remains at execution time. |
| **Reversible** | One `git revert` of one commit restores prior state completely; no external side effects (the Gate-1 surface is untouchable by construction). |
| **Regression-gated** | Hook/script touches: full hook suite green vs the recorded baseline + `hook-write-regression-gate.py` evidence logged. Vault-file touches: lint/structure checks pass on the touched set. |
| **Audit-trailed** | Loop-run record entry (N1) + manifest commit (N2) + ledger line where applicable, written in the same session as the change. |

**ALWAYS owner-gated (never auto-implemented, regardless of size):** CLAUDE.md / doctrine text and `n8n-working-patterns.md`; thresholds of any kind (deny patterns, miner severity/recurrence gates, competence thresholds, lint staleness windows); enforcement semantics (warn -> deny flips, ALWAYS_ALLOWED membership, block-class hookify rules, any new blocking behavior); new hooks / hook registration / `settings*.json` permission entries; skill procedure text beyond this ratified loop-protocol section and the typo class; evaluator/judge prompts, rubric text, verifier contracts; anything referencing `_irreversible_surface.py` or the Gate-1 hooks (not even proposals for auto-implementation: owner-track only); skill/prompt TEXT optimization of the SkillOpt/GEPA kind (blocked until a held-out eval oracle exists).

**Boundary edge rule:** when classification is ambiguous, the item is owner-gated. Burden of proof is on auto-implementation.

### OWNER-GATED bundling (5-family format)

Bundle OWNER-GATED items into decision families for one owner walkthrough (the demonstrated 2026-07-13 pattern):

- **Family A**: `no_classification` cluster (per-agent observability-noise dispatches).
- **Family B**: research-pipeline direct-dispatch (rows the hook source flags as process violations must NOT be auto-suppressed).
- **Family C**: high-volume calibration (high-count hooks working as designed; owner verification before suppression).
- **Family D**: reviewer / `check_3` calibration.
- **Family E**: behavioral gaps.

### Decision-brief template (OWNER-GATED families)

For each open family, present a Step-7-style brief: the sig distribution (which sig_ids, counts, distinct days), the fire-rate / false-positive rates where knowable, and 2 to 3 options with a recommendation and what each unblocks. Ratification cadence is batched, not per-item: run the walkthrough when OWNER-GATED families have accumulated (guideline: >= 5 open items or 14 days since the last walkthrough, whichever first). This is a guideline for surfacing the brief, not an enforced gate; the owner rules when the owner rules.

### Measured-worse definition + revert path

A loop-implemented change is MEASURED-WORSE if ANY of:

- (a) its target sig_id REGRESSED per `diff_miner_runs.py` in the next window;
- (b) the hook suite is red on any subsequent baseline run and bisects to the change;
- (c) a NEW sig_id appears whose samples trace to the change (manifest join via N2 + `correlation_id`/session proximity);
- (d) Track V: lint findings in the touched class increased run-over-run.

**Revert path:** a single `git revert` of the manifest commit + a ledger line `{"sig_id": S, "resolution": "reverted-measured-worse", "note": ...}` + a loop-run record update. The revert is itself in the auto-implement class (mechanical, reversible, regression-gated, trailed). If the revert does not restore the measurement, HALT the loop and escalate to the owner: that is evidence the causal model is wrong.

### Loop-run record (N1) + change-manifest convention (N2)

Every loop cycle appends one entry to `.claude/hooks/aggregates/loop-runs.jsonl` (operational data, NOT a wiki page). Schema:

```json
{
  "run_date": "YYYY-MM-DD",
  "detect_inputs": { "miner_run": "<path|null>", "lint_report": "<path|null>" },
  "proposal_artifact": "<path|null>",
  "rulings": [ { "family": "<id|null>", "sig_id": "<id|null>", "verdict": "<str>", "ruled_by": "<str|null>", "date": "YYYY-MM-DD" } ],
  "implemented": [ { "commit": "<sha|null>", "sig_ids": ["..."], "class": "<str>" } ],
  "measurement": { "status": "pending|complete", "verdicts": [], "window_end": "<date|null>" }
}
```

Entries are keyed by run date (overlapping MEASURE-of-N / DETECT-of-N+1 cycles are unambiguous). Backfill and every populated field is citation-or-null: an unrecoverable field is literal `null`, never a reconstructed value.

**N2 convention:** every loop-implemented commit message carries a `loop-run:<run_date>` trailer plus the `sig_id(s)` it addresses. This enables the commit -> signal join for measurement and the single-commit revert path.

### Documentation leg (N5)

At the end of every loop run's IMPLEMENT phase, run this three-part documentation checklist:

1. **Regenerate `registry.json`** via `python .claude/scripts/generate_registry.py` IF any skill / agent / hook changed in the run. A no-op run leaves the file unmodified.
2. **Run lint Pass A** scoped to wiki pages whose `source:` paths intersect the run's touched files (existing `process-lint`). SOURCE_DRIFT / MISSING_ANCHOR findings route into the NEXT cycle's DETECT; they do not block the current run. If scoping is unsupported, run full Pass A and record the cost as a finding.
3. **Append one `log.md` entry** for the run (append-only; an erroneous entry is corrected by a follow-up entry, never edited).
4. Any doc found stale is fixed in-run only if mechanical (per the autonomy boundary above); otherwise it is filed as a proposal (the `doc-consistency` skill is the escalation path for non-mechanical reconciliation).
