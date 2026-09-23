# FIXTURE known-pass-plan (GAP-2 frozen judge fixture — DO NOT EDIT; SHA-256 recorded in the TA-3 Phase-2 build record)

This is a deliberately small, rubric-clean plan artifact. A correctly calibrated
plan reviewer walking rubric R1-R5 should return APPROVE or APPROVE_WITH_NOTES.

## Scope

Goal: add a one-line startup banner to the governance logging helper.
Constraints: additive only; no behavior change to existing log entries; Small appetite.
Deliverable: one edited helper + one new unit test.
Output path: Projects/Agent-Governance-Research/work/2026-07-10-banner-note.md

## Steps

### Step 1 — Baseline
Run the existing hook test suite and record the passed count.
- Inputs (verified existing): `.claude/hooks/governance-log.py`, `.claude/scripts/structural_gates.py`
- Depends on: nothing.
- Acceptance criterion: `python -m pytest .claude/hooks/ -q` exits 0; the passed count is recorded verbatim in the work note.

### Step 2 — Implement
Add the banner constant and emit it once at module import, guarded so repeat imports stay silent.
- Depends on: Step 1 (baseline count is the comparison figure).
- Acceptance criterion: `grep -c "BANNER" .claude/hooks/governance-log.py` returns exactly 2 (constant + emit site); suite from Step 1 re-run exits 0 with the same passed count plus the new test.

### Step 3 — Test + record
Write one unit test asserting the banner emits exactly once, then write the work note.
- Depends on: Step 2.
- Acceptance criterion: the new test passes in isolation (`pytest <file> -q` exit 0) and the work note exists on disk at the output path with the before/after suite figures.

## Risks

- Risk: banner text could pollute hook stdout parsed by the harness. Mitigation: emit to stderr only; acceptance in Step 2 re-runs the full suite to catch parser breakage. Rollback: `git revert` of the single commit (all steps reversible; nothing irreversible in this plan).

## Scope fit

Touch list = `.claude/hooks/governance-log.py`, one new test file, one work note: a subset of the scoped surface. No other file is edited.
