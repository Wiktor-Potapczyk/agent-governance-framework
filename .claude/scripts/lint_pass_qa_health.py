#!/usr/bin/env python3
"""Lint Pass W: QA_HEALTH (2026-09-21).

Weekly measurement of the per-task QA contract from the monitoring the vault
already keeps: governance-log.jsonl and every Projects/*/work/qa-log.md.
Built after the adversarial review of the contract showed that the signal of
its decay (QA reports filed without the skill, "Untested: none deliberately"
on every workflow-path entry, task-plan items ticked on a partial PASS) had
sat unread in those files for months.

Measurements over the last WINDOW_DAYS:
  qa_turns          turns that carried a QA REPORT (work-verification-check records)
  inline_qa         of those, turns flagged inline-qa-without-skill
  entries           qa-log entries dated inside the window that carry a QA REPORT
  none_deliberately entries whose Untested line is the null phrase
  fail_entries      entries with n < N or a FAIL other than none
  run_entries       entries with at least one run-class claim ("- [run" in QA SCOPE)
  verifier_stated   entries carrying a Verifier: line
  partial_stamps    task_plan.md lines ticked [x] whose appended PASS line reads n < N
                    (all time; compared against the baseline in the state file)

CLI contract (shared by all lint_pass_* scripts):
  - always prints one measurement line:
      QA_HEALTH window_days=<w> qa_turns=<a> inline_qa=<b> entries=<c> none_deliberately=<d> fail_entries=<e> run_entries=<f> verifier_stated=<g> partial_stamps=<h> baseline_partial_stamps=<p>
  - finding: `QA_HEALTH_DEGRADED  metric=<name> value=<v> threshold=<t>`
  - exit 0 clean, 1 findings, 2 derivation failure
  - writes _state/qa-health.json (last metrics, findings, baseline) which
    _daily_aggregate.py turns into a dashboard alert

Thresholds are module constants, proposed, tunable, never inline literals.
RUN-1-IS-BASELINE for partial_stamps: the first run records the count and
prints baseline=none; a later run finds only growth above the baseline, so a
legacy stamp does not fire forever (the guard-over-a-growing-log rule).
"""
import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
VAULT = SCRIPTS.parent.parent

WINDOW_DAYS = 30
MIN_ENTRIES_FOR_RATES = 10       # rate findings need a denominator
INLINE_QA_MAX = 0.10             # share of QA-report turns filed without the skill
NONE_DELIBERATELY_MAX = 0.60     # share of entries with the null Untested phrase
RUN_CLASS_MIN = 0.20             # share of entries with at least one run-class claim
FAIL_ENTRIES_MIN = 0.02          # an instrument that never says no is not measuring (finding 19)
PARTIAL_STAMPS_GROWTH_MAX = 0    # new ticked items on a partial PASS since the baseline
VERIFIER_STATED_MIN = 0.50       # share of entries that say who verified
WORKFLOW_NULL_MAX = 0.60         # null Untested share on the workflow path alone
ENTRIES_LOGGED_MIN = 10          # qa-log entries expected when QA reports were filed

ENTRY_HEAD = re.compile(r"(?m)^## (\d{4}-\d{2}-\d{2})")
COUNTS = re.compile(r"(?m)^\s*PASS:\s*(\d+)\s*/\s*(\d+)")
FAIL = re.compile(r"(?m)(?:^|\|)\s*FAIL:\s*(.*?)\s*(?=\|\s*Untested:|$)")
UNTESTED = re.compile(r"(?m)(?:^|\|)\s*Untested:\s*(.*?)\s*(?=\|\s*Verifier:|$)")
VERIFIER = re.compile(r"(?m)(?:^|\|)\s*Verifier:\s*(workflow|main-session)")
RUN_CLAIM = re.compile(r"(?m)^- \[run\b")
STAMP = re.compile(r"(?m)^\s*-\s*\[x\].*(?:←|<-)\s*(?:QA PASS[^\n]*?)?PASS:\s*(\d+)\s*/\s*(\d+)")
NULL_UNTESTED = {"", "none", "none deliberately", "none deliberately.", "none."}
# "none", "none deliberately", "none deliberately (reason)", and the workflow's
# own "named no untested path and gave no reason" are all null surfaces.
NULL_UNTESTED_RE = re.compile(r"^(?:none\b.*|.*gave no reason.*)$", re.IGNORECASE | re.DOTALL)


def _window_start(today, days):
    return (today - dt.timedelta(days=days)).isoformat()


def scan_governance(log_path, start_iso):
    """qa_turns and inline_qa from work-verification-check records."""
    qa_turns = inline = 0
    if not log_path.is_file():
        return None
    with log_path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if '"work-verification-check"' not in line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = str(e.get("ts", ""))[:10]
            if ts < start_iso:
                continue
            if e.get("hook") != "work-verification-check":
                continue
            if e.get("has_qa_report") is True:
                qa_turns += 1
            if e.get("check") == "inline-qa-without-skill":
                inline += 1
    # an inline report never reaches the pass/warn record with has_qa_report, so
    # the denominator is both populations together
    return qa_turns + inline, inline


def scan_qa_logs(vault, start_iso):
    entries = none_delib = fails = runs = verifier = 0
    wf_entries = wf_null = 0
    for log in list(vault.glob("Projects/*/work/qa-log.md")) + list(vault.glob("Projects/*/*/work/qa-log.md")):
        try:
            text = log.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        parts = re.split(r"(?m)^(?=## )", text)
        for part in parts:
            m = ENTRY_HEAD.match(part)
            if not m or m.group(1) < start_iso:
                continue
            counts = COUNTS.search(part)
            if not counts:
                continue
            entries += 1
            n, total = int(counts.group(1)), int(counts.group(2))
            fm = FAIL.search(part)
            fail_text = (fm.group(1).strip().lower().rstrip(".") if fm else "none")
            if n < total or fail_text not in ("", "none"):
                fails += 1
            um = UNTESTED.search(part)
            is_null = bool(um) and (um.group(1).strip().lower() in NULL_UNTESTED or bool(NULL_UNTESTED_RE.match(um.group(1).strip())))
            if is_null:
                none_delib += 1
            if RUN_CLAIM.search(part):
                runs += 1
            vm = VERIFIER.search(part)
            if vm:
                verifier += 1
                if vm.group(1) == "workflow":
                    wf_entries += 1
                    if is_null:
                        wf_null += 1
    return entries, none_delib, fails, runs, verifier, wf_entries, wf_null


def scan_partial_stamps(vault):
    n = 0
    for plan in list(vault.glob("Projects/*/task_plan.md")) + list(vault.glob("Projects/*/*/task_plan.md")):
        try:
            text = plan.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in STAMP.finditer(text):
            if int(m.group(1)) < int(m.group(2)):
                n += 1
    return n


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--vault", default=str(VAULT))
    ap.add_argument("--gov-log", default=None, help="default <vault>/.claude/hooks/governance-log.jsonl")
    ap.add_argument("--state-dir", default=None, help="default <vault>/.claude/hooks/_state")
    ap.add_argument("--days", type=int, default=WINDOW_DAYS)
    ap.add_argument("--today", default=None, help="YYYY-MM-DD override for tests")
    args = ap.parse_args(argv)

    vault = Path(args.vault)
    gov = Path(args.gov_log) if args.gov_log else vault / ".claude" / "hooks" / "governance-log.jsonl"
    state_dir = Path(args.state_dir) if args.state_dir else vault / ".claude" / "hooks" / "_state"
    today = dt.date.fromisoformat(args.today) if args.today else dt.date.today()
    start = _window_start(today, args.days)

    if not (vault / "Projects").is_dir():
        print(f"DERIVATION FAILURE: no Projects dir under {vault}")
        return 2
    gov_res = scan_governance(gov, start)
    if gov_res is None:
        print(f"DERIVATION FAILURE: governance log missing: {gov}")
        return 2
    qa_turns, inline = gov_res
    entries, none_delib, fails, runs, verifier, wf_entries, wf_null = scan_qa_logs(vault, start)
    partial = scan_partial_stamps(vault)

    state_path = state_dir / "qa-health.json"
    baseline = None
    if state_path.is_file():
        try:
            baseline = json.loads(state_path.read_text(encoding="utf-8")).get("baseline_partial_stamps")
        except (json.JSONDecodeError, OSError) as e:
            print(f"DERIVATION FAILURE: unreadable state {state_path}: {e}")
            return 2

    print(f"QA_HEALTH window_days={args.days} qa_turns={qa_turns} inline_qa={inline} entries={entries} "
          f"none_deliberately={none_delib} fail_entries={fails} run_entries={runs} verifier_stated={verifier} "
          f"workflow_entries={wf_entries} workflow_null={wf_null} "
          f"partial_stamps={partial} baseline_partial_stamps={'none' if baseline is None else baseline}")

    findings = []

    def rate(num, den):
        return round(num / den, 3) if den else 0.0

    if qa_turns >= MIN_ENTRIES_FOR_RATES:
        r = rate(inline, qa_turns)
        if r > INLINE_QA_MAX:
            findings.append(("inline_qa", r, INLINE_QA_MAX))
    if entries >= MIN_ENTRIES_FOR_RATES:
        r = rate(none_delib, entries)
        if r > NONE_DELIBERATELY_MAX:
            findings.append(("none_deliberately", r, NONE_DELIBERATELY_MAX))
        r = rate(runs, entries)
        if r < RUN_CLASS_MIN:
            findings.append(("run_class", r, RUN_CLASS_MIN))
        r = rate(fails, entries)
        if r < FAIL_ENTRIES_MIN:
            findings.append(("fail_entries", r, FAIL_ENTRIES_MIN))
        r = rate(verifier, entries)
        if r < VERIFIER_STATED_MIN:
            findings.append(("verifier_stated", r, VERIFIER_STATED_MIN))
    if wf_entries >= MIN_ENTRIES_FOR_RATES:
        r = rate(wf_null, wf_entries)
        if r > WORKFLOW_NULL_MAX:
            findings.append(("workflow_null_share", r, WORKFLOW_NULL_MAX))
    if qa_turns >= MIN_ENTRIES_FOR_RATES and entries < ENTRIES_LOGGED_MIN:
        findings.append(("entries_logged", entries, ENTRIES_LOGGED_MIN))
    if baseline is not None and partial - baseline > PARTIAL_STAMPS_GROWTH_MAX:
        findings.append(("partial_stamps_growth", partial - baseline, PARTIAL_STAMPS_GROWTH_MAX))

    for name, value, threshold in findings:
        print(f"QA_HEALTH_DEGRADED  metric={name} value={value} threshold={threshold}")

    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps({
            "last_run": today.isoformat(),
            "window_days": args.days,
            "qa_turns": qa_turns, "inline_qa": inline, "entries": entries,
            "none_deliberately": none_delib, "fail_entries": fails, "run_entries": runs,
            "verifier_stated": verifier, "workflow_entries": wf_entries, "workflow_null": wf_null,
            "partial_stamps": partial,
            "baseline_partial_stamps": partial if baseline is None else baseline,
            "findings": [{"metric": n, "value": v, "threshold": t} for n, v, t in findings],
        }, indent=2), encoding="utf-8")
    except OSError as e:
        print(f"DERIVATION FAILURE: cannot write state {state_path}: {e}")
        return 2
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
